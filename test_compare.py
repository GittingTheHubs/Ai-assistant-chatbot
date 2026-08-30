"""
test_compare.py
---------------
Offline test suite for the product comparison engine in main.py.

Same approach as test_recommend.py: the LLM, the prompt template
and the vector retriever are stubbed out, so the whole comparison
pipeline -- intent detection, two-product resolution, CSV lookup,
table building, price/feature comparison and follow-up memory --
runs exactly as it does in production but without Ollama.

The retriever stub raises. That is deliberate: a comparison that
reaches vector search is a routing bug, because similarity search
is what drags unrelated products into a comparison.

Run:
    python test_compare.py

Set STUB_LLM = False to run the same cases against real Ollama.
"""

import os
import sys
import types


STUB_LLM = True

os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")


# ============================================================
# STUBS
# ============================================================

def install_stubs():

    class FakeChain:
        def invoke(self, _payload):
            return ""

    class FakePrompt:
        @classmethod
        def from_template(cls, _template):
            return cls()

        def __or__(self, _model):
            return FakeChain()

    core = types.ModuleType("langchain_core")
    prompts = types.ModuleType("langchain_core.prompts")
    prompts.ChatPromptTemplate = FakePrompt
    core.prompts = prompts

    sys.modules.setdefault("langchain_core", core)
    sys.modules["langchain_core.prompts"] = prompts

    class FakeLLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke(self, _payload):
            return ""

    ollama = types.ModuleType("langchain_ollama")
    llms = types.ModuleType("langchain_ollama.llms")
    llms.OllamaLLM = FakeLLM
    ollama.llms = llms

    sys.modules.setdefault("langchain_ollama", ollama)
    sys.modules["langchain_ollama.llms"] = llms

    class FakeRetriever:
        def invoke(self, query):
            raise AssertionError(
                "Vector search was called for a question the "
                "comparison engine should have answered from the "
                f"CSV: {query!r}"
            )

    vector = types.ModuleType("vector_v2")
    vector.retriever = FakeRetriever()

    sys.modules["vector_v2"] = vector


if STUB_LLM:
    install_stubs()


import main as bot  # noqa: E402


if STUB_LLM:
    bot.USE_LLM_FOR_COMPARISON = False
    bot.USE_LLM_FOR_RECOMMENDATIONS = False


CATALOG_TITLES = set(bot.df["Title"].astype(str))

BASE = "safetica"
PRO = "safetica Pro"
PREMIUM = "safetica Premium"


# ============================================================
# TINY TEST FRAMEWORK
# ============================================================

FAILURES = []
CHECKS = 0


def check(condition, message):
    global CHECKS
    CHECKS += 1

    if not condition:
        FAILURES.append(message)
        print(f"    FAIL  {message}")
    else:
        print(f"    ok    {message}")


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ============================================================
# CONVERSATION HELPER
# ============================================================

class Session:
    """
    Mirrors exactly what chat_app.py does per message.
    """

    def __init__(self, debug=False):
        self.memory = []
        self.active_product = None
        self.current_category = None
        self.debug = debug

    def ask(self, question):
        (
            answer,
            self.active_product,
            self.current_category,
            answer_type,
        ) = bot.process_question(
            question=question,
            active_product=self.active_product,
            current_category=self.current_category,
            memory=self.memory,
            debug=self.debug,
        )

        pair = list(bot._PENDING_COMPARISON)

        bot.add_memory(
            memory=self.memory,
            question=question,
            answer=answer,
            product=self.active_product,
        )

        return Turn(question, answer, answer_type, pair, self)


class Turn:
    def __init__(self, question, answer, answer_type, pair, session):
        self.question = question
        self.answer = answer
        self.answer_type = answer_type
        self.pair = pair
        self.session = session

    @property
    def is_comparison(self):
        return self.answer_type == "Comparison Engine"

    def show(self):
        print()
        print(f"  Q: {self.question}")
        print(f"  [{self.answer_type}] pair={self.pair} "
              f"active={self.session.active_product!r}")

        for line in self.answer.splitlines():
            print(f"  | {line}")

        return self


# ============================================================
# SHARED ASSERTIONS
# ============================================================

def assert_pair(turn, expected):
    check(
        turn.pair == expected,
        f"compared exactly {expected} (got {turn.pair})",
    )


def assert_only_mentions(turn, allowed):
    """
    Requirement 9: an answer about two products must not name a
    third one.
    """

    lowered = turn.answer.lower()
    allowed_lower = [title.lower() for title in allowed]

    strays = []

    for title in CATALOG_TITLES:

        normalized = bot.normalize_text(title)

        if len(normalized) < 6:
            continue

        if normalized in [bot.normalize_text(a) for a in allowed_lower]:
            continue

        # A title that is a substring of an allowed one (Safetica
        # inside Safetica Pro) is not a stray product.
        if any(normalized in bot.normalize_text(a) for a in allowed_lower):
            continue

        if bot.has_phrase(lowered, normalized):
            strays.append(title)

    check(
        not strays,
        f"answer mentions no product outside {allowed} "
        f"(strays: {strays[:3]})",
    )


def assert_prices_are_real(turn, titles):
    """
    Requirement 4: every price in the answer belongs to the
    product it is printed next to.
    """

    for title in titles:
        row = bot.get_row_by_title(title)
        price = bot.row_price(row)

        check(
            price in turn.answer,
            f"the answer shows {title}'s real price ({price})",
        )


# ============================================================
# 1. DETECTION
# ============================================================

def test_detection():
    section("1. Comparison detection - English and Thai")

    positive = [
        "Compare Safetica and Safetica Pro.",
        "What is the difference between Safetica and Safetica Pro?",
        "Safetica vs Safetica Pro",
        "Compare these two products.",
        "Which is better, Safetica or Safetica Pro?",
        "Safetica Pro compared to Safetica",
        "เปรียบเทียบ Safetica กับ Safetica Pro",
        "Safetica กับ Safetica Pro ต่างกันอย่างไร?",
        "Safetica กับ Safetica Pro",
        "Compare two laptop products from the catalog.",
    ]

    for question in positive:
        check(
            bot.is_comparison_question(question),
            f"detected as a comparison: {question!r}",
        )

    # These must NOT be hijacked by the comparison engine.
    negative = [
        "Recommend me a laptop.",
        "How much does Safetica cost?",
        "What features does it have?",
        "Show me Lenovo laptops.",
        "I need a firewall for a small office.",
    ]

    for question in negative:
        check(
            not bot.is_comparison_question(question),
            f"not a comparison: {question!r}",
        )


def test_product_extraction():
    section("2. Both products are identified, and they differ")

    cases = [
        "Compare Safetica and Safetica Pro.",
        "What is the difference between Safetica and Safetica Pro?",
        "Safetica vs Safetica Pro",
        "Which is better, Safetica or Safetica Pro?",
        "เปรียบเทียบ Safetica กับ Safetica Pro",
        "Safetica กับ Safetica Pro ต่างกันอย่างไร?",
    ]

    for question in cases:

        mentions = bot.find_product_mentions(question)

        check(
            mentions[:2] == [BASE, PRO],
            f"{question!r} -> {[BASE, PRO]} (got {mentions})",
        )

    # The old bug: exact_product_match() returns the longest
    # title, so both sides used to become Safetica Pro.
    single = bot.exact_product_match("Compare Safetica and Safetica Pro.")

    check(
        single == PRO,
        "exact_product_match() still returns one title "
        f"(got {single!r}) - which is why find_product_mentions() "
        "exists",
    )

    # Three products named, order preserved.
    mentions = bot.find_product_mentions(
        "Compare Safetica, Safetica Pro and Safetica Premium"
    )

    check(
        mentions[:3] == [BASE, PRO, PREMIUM],
        f"three products keep their order (got {mentions})",
    )


# ============================================================
# 3. THE TWELVE CASES FROM THE BRIEF
# ============================================================

def test_brief_cases():
    section("3. The twelve questions from the brief")

    pair = [BASE, PRO]

    for question in [
        "Compare Safetica and Safetica Pro.",
        "What is the difference between Safetica and Safetica Pro?",
        "Safetica vs Safetica Pro",
        "Which is better, Safetica or Safetica Pro?",
        "เปรียบเทียบ Safetica กับ Safetica Pro",
        "Safetica กับ Safetica Pro ต่างกันอย่างไร?",
    ]:

        turn = Session().ask(question).show()

        check(turn.is_comparison, f"{question!r} used the comparison engine")
        assert_pair(turn, pair)
        assert_only_mentions(turn, pair)
        assert_prices_are_real(turn, pair)

        check(
            "|" in turn.answer,
            "the answer contains a comparison table",
        )

    # --- 5 & 6: follow-ups on the pair ----------------------

    chat = Session()
    chat.ask("Compare Safetica and Safetica Pro.")

    turn = chat.ask("Which one is cheaper?").show()

    check(turn.is_comparison, "'Which one is cheaper?' stayed on the pair")
    assert_pair(turn, pair)
    assert_prices_are_real(turn, pair)
    assert_only_mentions(turn, pair)

    turn = chat.ask("Which one has more features?").show()

    check(turn.is_comparison, "'Which one has more features?' stayed on the pair")
    assert_pair(turn, pair)
    assert_only_mentions(turn, pair)

    check(
        "feature" in turn.answer.lower(),
        "the feature answer talks about features",
    )

    # --- 7: "Compare these two." ----------------------------

    turn = chat.ask("Compare these two.").show()

    check(turn.is_comparison, "'Compare these two.' reused the pair")
    assert_pair(turn, pair)
    assert_only_mentions(turn, pair)

    # --- 10: two laptops ------------------------------------

    turn = Session().ask(
        "Compare two laptop products from the catalog."
    ).show()

    check(turn.is_comparison, "category comparison used the engine")
    check(len(turn.pair) == 2, f"two products were compared: {turn.pair}")

    laptops = set(
        bot.filter_category(bot.df, "laptop")["Title"].astype(str)
    )

    for title in turn.pair:
        check(title in laptops, f"'{title}' is a laptop")
        check(title in CATALOG_TITLES, f"'{title}' is in the catalog")

    check(
        turn.pair[0] != turn.pair[1],
        "the two laptops are different products",
    )

    # --- 11: two antivirus products -------------------------

    turn = Session().ask(
        "Compare two antivirus products from the catalog."
    ).show()

    check(turn.is_comparison, "antivirus comparison used the engine")
    check(len(turn.pair) == 2, f"two products were compared: {turn.pair}")

    antivirus = set(
        bot.filter_category(bot.df, "antivirus")["Title"].astype(str)
    )

    for title in turn.pair:
        check(title in antivirus, f"'{title}' is an antivirus product")

    # --- 12: a product that does not exist ------------------

    turn = Session().ask(
        "Compare Safetica with SomeRandomProduct."
    ).show()

    check(
        turn.is_comparison,
        "the unknown product was handled by the comparison engine",
    )

    check(
        not turn.pair,
        "nothing was compared, so no pair was remembered",
    )

    lowered = turn.answer.lower()

    check(
        "somerandomproduct" in lowered,
        "the answer names the product it could not find",
    )

    check(
        "could not find" in lowered or "not find" in lowered,
        "the answer says the product was not found",
    )


# ============================================================
# 4. FOLLOW-UP CHAIN FROM THE BRIEF
# ============================================================

def test_followup_chain():
    section("4. The follow-up chain")

    pair = [BASE, PRO]

    chat = Session()

    turn = chat.ask("Compare Safetica and Safetica Pro.").show()
    assert_pair(turn, pair)

    turn = chat.ask("Which one is cheaper?").show()
    check(turn.is_comparison, "cheaper -> comparison engine")
    assert_pair(turn, pair)

    turn = chat.ask("Which one is better?").show()
    check(turn.is_comparison, "better -> comparison engine")
    assert_pair(turn, pair)
    assert_only_mentions(turn, pair)

    turn = chat.ask("What about the features?").show()
    check(turn.is_comparison, "features -> comparison engine")
    assert_pair(turn, pair)

    turn = chat.ask("What about the price?").show()
    check(turn.is_comparison, "price -> comparison engine")
    assert_prices_are_real(turn, pair)

    # --- ordinal references ---------------------------------

    turn = chat.ask("Tell me about the first one.").show()

    check(
        chat.active_product == BASE,
        f"'the first one' resolved to {BASE} "
        f"(got {chat.active_product!r})",
    )

    turn = chat.ask("How much does the second one cost?").show()

    check(
        chat.active_product == PRO,
        f"'the second one' resolved to {PRO} "
        f"(got {chat.active_product!r})",
    )

    check(
        bot.row_price(bot.get_row_by_title(PRO)) in turn.answer,
        "the price shown is Safetica Pro's own price",
    )

    check(
        BASE.lower() not in turn.answer.lower().replace(PRO.lower(), ""),
        "the answer is about the second product only",
    )


# ============================================================
# 5. NO REGRESSIONS IN THE EXISTING FEATURES
# ============================================================

def test_no_regressions():
    section("5. The existing pipeline still behaves")

    # --- a plain product question is NOT a comparison -------

    chat = Session()

    turn = chat.ask("How much does Safetica cost?").show()

    check(
        turn.answer_type == "Data Engine",
        "a plain price question still uses the price engine",
    )

    check(
        chat.active_product == BASE,
        f"active_product is still set normally "
        f"(got {chat.active_product!r})",
    )

    # --- recommendation shortlist follow-up is untouched ----

    chat = Session()

    chat.ask("Recommend me 3 laptops.")

    turn = chat.ask("Which one is the cheapest?").show()

    check(
        turn.answer_type == "Recommendation Engine",
        "a shortlist follow-up still goes to the recommendation "
        "engine, not to the comparison engine",
    )

    # --- a comparison after a shortlist takes over ----------

    chat = Session()

    chat.ask("Recommend me 3 laptops.")
    turn = chat.ask("Compare Safetica and Safetica Pro.").show()

    check(turn.is_comparison, "an explicit comparison overrides the shortlist")
    assert_pair(turn, [BASE, PRO])

    turn = chat.ask("Which one is cheaper?").show()

    check(
        turn.is_comparison,
        "after a comparison, 'which one is cheaper?' is about the "
        "pair, not about the older shortlist",
    )

    # --- context reset still works --------------------------

    chat = Session()

    chat.ask("Compare Safetica and Safetica Pro.")
    turn = chat.ask("Recommend me a laptop.").show()

    check(
        turn.answer_type == "Recommendation Engine",
        "a new search after a comparison is not hijacked",
    )

    # --- pronoun follow-up on a single product --------------

    chat = Session()

    chat.ask("How much does Safetica cost?")

    check(
        chat.active_product == BASE,
        "single-product conversation memory is intact",
    )


# ============================================================
# 6. COMPARISON DATA COMES FROM THE CSV
# ============================================================

def test_data_is_from_csv():
    section("6. Every compared value exists in products_enriched.csv")

    rows = [bot.get_row_by_title(BASE), bot.get_row_by_title(PRO)]

    fields = bot.comparison_field_values(rows, thai=False)

    check(bool(fields), "the comparison produced at least one field")

    labels = [label for label, _a, _b, _d in fields]

    check("Price" in labels, "price is one of the compared fields")

    for label, value_a, value_b, _differs in fields:

        for row, value in zip(rows, (value_a, value_b)):

            if value == bot.MISSING_EN:
                continue

            head = value.split("...")[0][:40].strip()

            if not head:
                continue

            blob = " ".join(
                str(row.get(column, ""))
                for column in bot.df.columns
            )

            check(
                head in blob or head in bot.row_price(row),
                f"'{label}' value for {row['Title']} comes from the CSV",
            )

    # Each product keeps its own price.
    price_a = bot.row_price(rows[0])
    price_b = bot.row_price(rows[1])

    table = bot.comparison_table(rows, thai=False)

    price_line = [
        line
        for line in table.splitlines()
        if line.startswith("| Price ")
    ]

    check(len(price_line) == 1, "the table has exactly one price row")

    if price_line:
        check(
            price_a in price_line[0] and price_b in price_line[0],
            "the price row holds a separate price for each product",
        )


def test_missing_fields_are_declared():
    section("7. Missing information is declared, never invented")

    rows = [bot.get_row_by_title(BASE), bot.get_row_by_title(PRO)]

    # Variants is empty for both Safetica rows, so it must not
    # appear at all rather than appear as an empty cell.
    labels = [
        label
        for label, _a, _b, _d in bot.comparison_field_values(
            rows, thai=False
        )
    ]

    check(
        "Variants" not in labels,
        "a field that is empty for BOTH products is dropped",
    )

    # Force the one-sided case.
    left = bot.get_row_by_title(BASE).copy()
    right = bot.get_row_by_title(PRO).copy()

    right["Best_For"] = ""

    fields = dict(
        (label, (value_a, value_b))
        for label, value_a, value_b, _d in bot.comparison_field_values(
            [left, right], thai=False
        )
    )

    check(
        "Best For" in fields,
        "a field present on one side only is still compared",
    )

    if "Best For" in fields:
        check(
            fields["Best For"][1] == bot.MISSING_EN,
            "the missing side says the catalog does not list it "
            f"(got {fields['Best For'][1]!r})",
        )


# ============================================================
# 8. THAI
# ============================================================

def test_thai():
    section("8. Thai comparisons answer in Thai")

    turn = Session().ask(
        "เปรียบเทียบ Safetica กับ Safetica Pro"
    ).show()

    check(turn.is_comparison, "the Thai comparison used the engine")
    assert_pair(turn, [BASE, PRO])

    check(
        "เทียบกับ" in turn.answer or "ราคา" in turn.answer,
        "the Thai answer is written in Thai",
    )

    check(
        "Feature |" not in turn.answer,
        "the table header is not the English one",
    )

    chat = Session()
    chat.ask("Safetica กับ Safetica Pro ต่างกันอย่างไร?")

    turn = chat.ask("ตัวไหนถูกกว่า?").show()

    check(turn.is_comparison, "the Thai follow-up stayed on the pair")
    assert_pair(turn, [BASE, PRO])


# ============================================================
# 9. VECTOR SEARCH IS NEVER USED FOR A KNOWN PAIR
# ============================================================

def test_no_vector_search():
    section("9. A resolved comparison never reaches vector search")

    # The stubbed retriever raises, so simply completing these
    # turns proves the comparison path answered them from the
    # CSV. The check is explicit anyway.

    questions = [
        "Compare Safetica and Safetica Pro.",
        "Safetica vs Safetica Pro",
        "เปรียบเทียบ Safetica กับ Safetica Pro",
    ]

    for question in questions:

        try:
            turn = Session().ask(question)
            reached_vector = False
        except AssertionError:
            reached_vector = True

        check(
            not reached_vector,
            f"{question!r} was answered without vector search",
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    tests = [
        test_detection,
        test_product_extraction,
        test_brief_cases,
        test_followup_chain,
        test_no_regressions,
        test_data_is_from_csv,
        test_missing_fields_are_declared,
        test_thai,
        test_no_vector_search,
    ]

    for test in tests:
        try:
            test()
        except Exception as exc:
            FAILURES.append(f"{test.__name__} crashed: {exc!r}")
            print(f"    CRASH {test.__name__}: {exc!r}")

            import traceback
            traceback.print_exc()

    print()
    print("=" * 70)
    print(f"{CHECKS - len(FAILURES)} / {CHECKS} checks passed")
    print("=" * 70)

    if FAILURES:
        print()
        for failure in FAILURES:
            print(f"  FAIL  {failure}")

    sys.exit(1 if FAILURES else 0)
