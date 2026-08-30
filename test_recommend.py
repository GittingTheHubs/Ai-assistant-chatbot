"""
test_recommend.py
-----------------
Offline test suite for the recommendation engine in main.py.

It stubs out the three things that need a running Ollama server
(the chat model, the embedding-backed retriever and the prompt
template) so the whole routing / filtering / ranking pipeline can
be exercised without downloading a model. Everything that is
actually under test -- intent detection, category and brand
filtering, price thresholds, ranking, context reset, shortlist
follow-ups and the catalog-only guard -- is pure Python and pandas
and runs exactly as it does in production.

Run:
    python test_recommend.py

Set STUB_LLM = False below to run the same suite against the real
Ollama model instead.
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
    """
    Register fake modules under the names main.py imports, so the
    import of main.py does not require Ollama.
    """

    # ---- langchain_core.prompts ----------------------------

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

    # ---- langchain_ollama.llms -----------------------------

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

    # ---- vector_v2 -----------------------------------------
    #
    # Importing the real vector_v2 would load the embedding model
    # and open the Chroma store. The recommendation paths never
    # touch the retriever; any test that reaches it is a routing
    # bug and should fail loudly.

    class FakeRetriever:
        def invoke(self, query):
            raise AssertionError(
                "The retriever was called for a query that the "
                "recommendation engine should have answered: "
                f"{query!r}"
            )

    vector = types.ModuleType("vector_v2")
    vector.retriever = FakeRetriever()

    sys.modules["vector_v2"] = vector


if STUB_LLM:
    install_stubs()


import main as bot  # noqa: E402


if STUB_LLM:
    # No model, so no LLM commentary. The structured shortlist is
    # produced entirely by the engine.
    bot.USE_LLM_FOR_RECOMMENDATIONS = False


CATALOG_TITLES = set(bot.df["Title"].astype(str))


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

        shortlist = list(bot._PENDING_RECOMMENDATIONS)

        bot.add_memory(
            memory=self.memory,
            question=question,
            answer=answer,
            product=self.active_product,
        )

        return Turn(question, answer, answer_type, shortlist, self)


class Turn:
    def __init__(self, question, answer, answer_type, shortlist, session):
        self.question = question
        self.answer = answer
        self.answer_type = answer_type
        self.shortlist = shortlist
        self.session = session

    def show(self):
        print()
        print(f"  Q: {self.question}")
        print(f"  [{self.answer_type}] active={self.session.active_product!r} "
              f"category={self.session.current_category!r}")

        for line in self.answer.splitlines():
            print(f"  | {line}")

        return self


# ============================================================
# SHARED ASSERTIONS
# ============================================================

def assert_in_catalog(turn):
    """
    Requirement 7: never recommend something that is not in
    products_enriched.csv.
    """

    for title in turn.shortlist:
        check(
            title in CATALOG_TITLES,
            f"'{title}' exists in products_enriched.csv",
        )


BANNED_PRODUCTS = [
    "rog zephyrus",
    "zephyrus g14",
    "msi gs66",
    "gs66 stealth",
    "razer blade",
    "macbook pro",
]


def assert_no_invented_products(turn):
    lowered = turn.answer.lower()

    for banned in BANNED_PRODUCTS:
        if banned in CATALOG_TITLES:
            continue

        check(
            banned not in lowered,
            f"answer does not invent '{banned}'",
        )


CATEGORY_MEMBERS = {
    name: set(bot.filter_category(bot.df, name)["Title"].astype(str))
    for name, _rule in bot.CATEGORY_RULES
}


def assert_category(turn, category):
    """
    Every recommended product must belong to the requested
    category.

    The check runs against the engine's own category filter
    rather than against the raw Category column, because the
    dataset's Category column is unreliable -- several laptops
    are filed as "Other Software" or "Endpoint Security".
    """

    members = CATEGORY_MEMBERS[category]

    for title in turn.shortlist:
        check(
            title in members,
            f"'{title}' is in the '{category}' category",
        )


def prices_of(turn):
    values = []

    for title in turn.shortlist:
        row = bot.get_row_by_title(title)
        price = row.get("Price_num")

        if price == price and price not in (None, ""):
            values.append(float(price))

    return values


# ============================================================
# 1. CATEGORY / BRAND / PRICE RECOMMENDATIONS
# ============================================================

def test_basic_recommendations():
    section("1. Recommendation engine - the ten queries from the brief")

    # --- Recommend me a laptop. -----------------------------

    turn = Session().ask("Recommend me a laptop.").show()

    check(turn.answer_type == "Recommendation Engine",
          "'Recommend me a laptop.' is handled by the engine")
    check(2 <= len(turn.shortlist) <= 4,
          f"returns a shortlist of about 3 (got {len(turn.shortlist)})")
    assert_category(turn, "laptop")
    assert_in_catalog(turn)
    assert_no_invented_products(turn)

    # --- Recommend me a Lenovo laptop. ----------------------

    turn = Session().ask("Recommend me a Lenovo laptop.").show()

    check(bool(turn.shortlist), "Lenovo laptops were found")
    assert_category(turn, "laptop")
    assert_in_catalog(turn)

    for title in turn.shortlist:
        row = bot.get_row_by_title(title)
        blob = str(row.get("_brand_blob", "")).lower()

        check(
            any(alias in blob for alias in bot.BRAND_ALIASES["lenovo"]),
            f"'{title}' really is a Lenovo product",
        )

    # --- Recommend me a laptop under 30,000 THB. ------------

    turn = Session().ask("Recommend me a laptop under 30,000 THB.").show()

    check(bool(turn.shortlist), "laptops under 30,000 THB were found")
    assert_category(turn, "laptop")
    assert_in_catalog(turn)

    for price in prices_of(turn):
        check(price <= 30000,
              f"price {price:,.0f} is within the 30,000 THB budget")

    # --- What's the cheapest laptop? ------------------------

    turn = Session().ask("What's the cheapest laptop?").show()

    check(len(turn.shortlist) == 1,
          f"singular question returns one product (got {len(turn.shortlist)})")
    assert_category(turn, "laptop")
    assert_in_catalog(turn)

    cheapest = prices_of(turn)
    all_laptops = bot.filter_category(bot.df, "laptop")
    true_min = all_laptops["Price_num"].dropna().min()

    check(
        bool(cheapest) and abs(cheapest[0] - float(true_min)) < 0.01,
        "the cheapest laptop really is the lowest-priced laptop "
        f"(engine {cheapest[0] if cheapest else None} vs data {true_min})",
    )

    # --- What are the cheapest laptops? ---------------------

    turn = Session().ask("What are the cheapest laptops?").show()

    check(len(turn.shortlist) > 1,
          f"plural question returns several products "
          f"(got {len(turn.shortlist)})")
    assert_in_catalog(turn)

    ordered = prices_of(turn)
    check(ordered == sorted(ordered),
          "cheapest-first ordering is ascending by price")

    # --- What's the best laptop for gaming? -----------------

    turn = Session().ask("What's the best laptop for gaming?").show()

    check(bool(turn.shortlist), "a gaming answer was produced")
    assert_category(turn, "laptop")
    assert_in_catalog(turn)
    assert_no_invented_products(turn)

    # Requirement 2: "best" must not silently mean "cheapest".
    cheap_turn = Session().ask("What's the cheapest laptop?")

    check(
        turn.shortlist[:1] != cheap_turn.shortlist[:1],
        "'best for gaming' does not simply return the cheapest laptop",
    )

    # --- The three software categories ----------------------

    for question, expected in [
        ("Recommend me an antivirus.", "antivirus"),
        ("Recommend me a firewall.", "firewall"),
        ("Recommend me a backup solution.", "backup"),
    ]:
        turn = Session().ask(question).show()

        check(bool(turn.shortlist), f"'{question}' returns products")
        assert_category(turn, expected)
        assert_in_catalog(turn)
        assert_no_invented_products(turn)

    # --- Combined constraints -------------------------------

    turn = Session().ask(
        "Recommend me a Lenovo laptop under 30,000 THB."
    ).show()

    assert_in_catalog(turn)

    for title in turn.shortlist:
        row = bot.get_row_by_title(title)
        blob = str(row.get("_brand_blob", "")).lower()

        check(
            any(alias in blob for alias in bot.BRAND_ALIASES["lenovo"]),
            f"'{title}' is Lenovo",
        )

    for price in prices_of(turn):
        check(price <= 30000, f"price {price:,.0f} is under 30,000 THB")


# ============================================================
# 2. BEST vs CHEAPEST vs MOST EXPENSIVE
# ============================================================

def test_sort_modes():
    section("2. 'best' vs 'cheapest' vs 'most expensive'")

    check(bot.detect_sort_mode("What's the cheapest laptop?") == "cheapest",
          "'cheapest' -> cheapest")
    check(bot.detect_sort_mode("What's the most expensive laptop?")
          == "expensive",
          "'most expensive' -> expensive")
    check(bot.detect_sort_mode("What's the best laptop for gaming?")
          == "relevance",
          "'best' -> relevance, not price")
    check(bot.detect_sort_mode("Recommend me a laptop.") == "relevance",
          "'recommend' -> relevance, not price")

    cheap = Session().ask("What's the cheapest laptop?")
    pricey = Session().ask("What's the most expensive laptop?").show()

    cheap_price = prices_of(cheap)
    pricey_price = prices_of(pricey)

    check(
        bool(cheap_price) and bool(pricey_price)
        and pricey_price[0] > cheap_price[0],
        "the most expensive laptop costs more than the cheapest one",
    )


# ============================================================
# 3. USE-CASE DETECTION
# ============================================================

def test_use_cases():
    section("3. Use-case detection")

    cases = [
        ("What's the best laptop for gaming?", "gaming"),
        ("Recommend me a laptop for business.", "business"),
        ("I need a laptop for the office.", "office"),
        ("Recommend me a laptop for students.", "student"),
        ("I need a laptop for work.", "work"),
        ("Recommend me an enterprise solution.", "enterprise"),
        ("Recommend me a security solution.", "security"),
    ]

    for question, expected in cases:
        detected = bot.detect_use_case(question)

        check(detected == expected,
              f"'{question}' -> use case {expected} (got {detected})")

    # Requirement 3: no invented specifications.
    turn = Session().ask("What's the best laptop for gaming?")

    assert_no_invented_products(turn)

    for title in turn.shortlist:
        check(title in CATALOG_TITLES,
              f"gaming pick '{title}' comes from the dataset")


# ============================================================
# 4. CONTEXT BLEED
# ============================================================

def test_context_reset():
    section("4. Conversation bugs - a new search drops the old product")

    session = Session()

    first = session.ask("What is Safetica Pro?")

    check(
        session.active_product is not None
        and "safetica" in str(session.active_product).lower(),
        f"Safetica became the active product (got {session.active_product})",
    )

    second = session.ask("Recommend me a laptop.").show()

    check(second.answer_type == "Recommendation Engine",
          "the laptop question reaches the recommendation engine")
    check("safetica" not in second.answer.lower(),
          "the laptop answer does not mention Safetica")
    check(session.active_product != first.session.active_product
          or session.active_product is None
          or "safetica" not in str(session.active_product).lower(),
          "the active product is no longer Safetica")

    assert_category(second, "laptop")
    assert_in_catalog(second)

    # ...but ordinary follow-ups must still work.

    session = Session()
    session.ask("What is Safetica Pro?")
    before = session.active_product

    session.ask("What features does it have?")

    check(session.active_product == before,
          f"'What features does it have?' keeps {before!r}")

    session.ask("How much does it cost?")

    check(session.active_product == before,
          f"'How much does it cost?' keeps {before!r}")


# ============================================================
# 5. SHORTLIST FOLLOW-UPS
# ============================================================

def test_shortlist_followups():
    section("5. 'Which one...' follow-ups")

    # --- Recommend 3 laptops -> which one is the cheapest? --

    session = Session()
    first = session.ask("Recommend me 3 laptops.").show()

    check(len(first.shortlist) == 3,
          f"asked for 3, got {len(first.shortlist)}")

    second = session.ask("Which one is the cheapest?").show()

    check(len(second.shortlist) == 1,
          "'which one' narrows down to a single product")
    check(second.shortlist and second.shortlist[0] in first.shortlist,
          "the answer comes from the products just recommended")

    prices = [
        bot.get_row_by_title(t).get("Price_num")
        for t in first.shortlist
    ]
    priced = [
        (p, t) for p, t in zip(prices, first.shortlist)
        if p == p and p not in (None, "")
    ]

    if priced:
        expected = min(priced)[1]
        check(second.shortlist[0] == expected,
              f"picked the cheapest of the three ({expected})")

    # --- Recommend some laptops -> best for gaming? ---------

    session = Session()
    first = session.ask("Recommend me some laptops.").show()

    check(len(first.shortlist) > 1, "'some laptops' returns several")

    second = session.ask("Which one is best for gaming?").show()

    check(bool(second.shortlist), "the gaming follow-up returns a product")
    check(all(t in first.shortlist for t in second.shortlist),
          "the gaming pick comes from the previous shortlist")
    assert_no_invented_products(second)

    third = session.ask("How much does that one cost?").show()

    check("Recommendation" in third.answer_type
          or "Data Engine" in third.answer_type,
          "the price follow-up is answered structurally")
    check(
        any(
            title.lower() in third.answer.lower()
            for title in second.shortlist
        ),
        "the price answer is about the product just chosen",
    )

    # --- Recommend a Lenovo laptop -> how much does it cost? -

    session = Session()
    first = session.ask("Recommend me a Lenovo laptop.").show()
    second = session.ask("How much does it cost?").show()

    check(
        any(
            title.lower() in second.answer.lower()
            for title in first.shortlist
        ),
        "the price answer refers to the recommended Lenovo product(s)",
    )


# ============================================================
# 6. BRAND MATCHING AND TYPOS
# ============================================================

def test_brand_matching():
    section("6. Product / brand matching, including typos")

    for query, expected in [
        ("Recommend me a Lenovo laptop.", "lenovo"),
        ("Recommend me an ASUS laptop.", "asus"),
        ("Recommend me a Dell laptop.", "dell"),
        ("Recommend me a lenvo laptop.", "lenovo"),
        ("Recommend me a lenov laptop.", "lenovo"),
    ]:
        detected = bot.detect_brand(query)

        check(detected == expected,
              f"'{query}' -> brand {expected} (got {detected})")

    for query, expected in [
        ("Recommend me a lapto.", "laptop"),
        ("Recommend me a laptop p.", "laptop"),
        ("Recommend me a laptop.", "laptop"),
    ]:
        detected = bot.detect_category(query)

        check(detected == expected,
              f"'{query}' -> category {expected} (got {detected})")

    # Generic questions must not latch onto a random product.

    for query in [
        "Hello",
        "What can you help me with?",
        "Do you offer support?",
        "Recommend me a laptop.",
        "Recommend me a security solution.",
    ]:
        matched = bot.resolve_product(query, None)

        check(matched is None,
              f"'{query}' does not accidentally match a product "
              f"(got {matched!r})")

    # Brand detection must not fire on ordinary words.

    for query in [
        "What's the cheapest laptop?",
        "Recommend me a backup solution.",
        "I need something for the office.",
    ]:
        detected = bot.detect_brand(query)

        check(detected is None,
              f"'{query}' does not invent a brand (got {detected!r})")


# ============================================================
# 7. CATALOG-ONLY GUARD
# ============================================================

def test_catalog_guard():
    section("7. Catalog-only recommendations")

    rows = [
        bot.get_row_by_title(t)
        for t in list(CATALOG_TITLES)[:3]
    ]

    hallucinated = (
        "I would suggest the ASUS ROG Zephyrus G14 or the MSI GS66 "
        "for gaming."
    )

    check(not bot.answer_stays_in_catalog(hallucinated, rows),
          "an answer naming ASUS ROG Zephyrus G14 / MSI GS66 is rejected")

    grounded = f"The best fit here is the {rows[0]['Title']}."

    check(bot.answer_stays_in_catalog(grounded, rows),
          "an answer naming a real shortlisted product is accepted")

    # Every recommendation the engine produces, across a broad
    # sweep of questions, must come from the CSV.

    questions = [
        "Recommend me a laptop.",
        "Recommend me a Lenovo laptop.",
        "Recommend me a laptop under 30,000 THB.",
        "What's the cheapest laptop?",
        "What are the cheapest laptops?",
        "What's the best laptop for gaming?",
        "Recommend me an antivirus.",
        "Recommend me a firewall.",
        "Recommend me a backup solution.",
        "Recommend me a gaming laptop with an RTX 4090.",
    ]

    for question in questions:
        turn = Session().ask(question)

        for title in turn.shortlist:
            check(title in CATALOG_TITLES,
                  f"'{question}' -> '{title}' is in the catalog")

        assert_no_invented_products(turn)


# ============================================================
# 8. OUTPUT SHAPE
# ============================================================

def test_output_shape():
    section("8. Output shape - singular vs plural vs shortlist")

    singular = Session().ask("What's the cheapest laptop?")
    plural = Session().ask("What are the cheapest laptops?")
    shortlist = Session().ask("Recommend me a laptop.")

    check(len(singular.shortlist) == 1,
          f"singular -> 1 product (got {len(singular.shortlist)})")
    check(len(plural.shortlist) > 1,
          f"plural -> several products (got {len(plural.shortlist)})")
    check(2 <= len(shortlist.shortlist) <= 4,
          f"'recommend me a laptop' -> ~3 products "
          f"(got {len(shortlist.shortlist)})")

    for turn in (singular, plural, shortlist):
        check(len(turn.answer) < 2000,
              f"answer stays concise ({len(turn.answer)} characters)")

    # A shortlist must not repeat the same machine three times.
    check(len(set(shortlist.shortlist)) == len(shortlist.shortlist),
          "no duplicate products in a shortlist")


# ============================================================
# 9. PIPELINE INTEGRATION
# ============================================================

def test_integration():
    section("9. Integration with the existing pipeline")

    check(callable(bot.process_question),
          "process_question is still the single entry point")

    session = Session()
    turn = session.ask("Recommend me a laptop.")

    check(isinstance(turn.answer, str) and turn.answer,
          "process_question returns a non-empty answer string")
    check(len(session.memory) == 1,
          "the turn was written to memory")
    check("recommendations" in session.memory[-1],
          "the shortlist was persisted alongside the conversation")
    check(bot.get_last_recommendations(session.memory) == turn.shortlist,
          "get_last_recommendations reads the shortlist back")

    # chat_app.py unpacks exactly four values.
    result = bot.process_question(
        question="Recommend me an antivirus.",
        active_product=None,
        current_category=None,
        memory=[],
        debug=False,
    )

    check(isinstance(result, tuple) and len(result) == 4,
          "process_question still returns the 4-tuple chat_app.py expects")

    # Internal helper columns must never reach the LLM.
    row = bot.get_row_by_title(turn.shortlist[0])
    context = bot.row_to_context(row)

    for hidden in ("_blob", "_brand_blob", "Price_num"):
        check(hidden not in context,
              f"'{hidden}' is not leaked into the LLM context")


# ============================================================
# 10. CATEGORY RULE SANITY
# ============================================================

def test_category_rules():
    section("10. Category rules against the real dataset")

    for name, _rule in bot.CATEGORY_RULES:
        subset = bot.filter_category(bot.df, name)

        print(f"    {name:<22} {len(subset):>4} products")

        check(len(subset) > 0,
              f"category '{name}' matches at least one product")

    laptops = bot.filter_category(bot.df, "laptop")

    check(len(laptops) < 200,
          f"the laptop filter is not matching the whole catalog "
          f"({len(laptops)} of {len(bot.df)})")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    tests = [
        test_basic_recommendations,
        test_sort_modes,
        test_use_cases,
        test_context_reset,
        test_shortlist_followups,
        test_brand_matching,
        test_catalog_guard,
        test_output_shape,
        test_integration,
        test_category_rules,
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
