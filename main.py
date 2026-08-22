import re
import pandas as pd

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever


# ============================================================
# CONFIGURATION
# ============================================================

MODEL = "qwen2.5:7b"

NUM_CTX = 16384
NUM_PREDICT = 800
TEMPERATURE = 0.1

MAX_TRIES = 3
MAX_DOC_CHARS = 1800

DATASET = "products_enriched.csv"

MAX_MEMORY_TURNS = 6

# Retrieval count for normal RAG
RAG_K = 6

# ============================================================
# DATASET
# ============================================================

df = pd.read_csv(
    DATASET,
    encoding="utf-8-sig"
).fillna("")

# Make sure expected columns exist
required_columns = [
    "Title",
    "Price_Min",
    "Price_Display",
]

missing_columns = [
    col for col in required_columns
    if col not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )

# Numeric price for structured queries
df["Price_num"] = pd.to_numeric(
    df["Price_Min"],
    errors="coerce"
)

print(
    f"Loaded {len(df)} products, "
    f"{len(df.columns)} columns"
)


# ============================================================
# PRODUCT TITLE CACHE
# ============================================================

PRODUCT_TITLES = sorted(
    [
        str(x).strip()
        for x in df["Title"].unique()
        if str(x).strip()
    ],
    key=len,
    reverse=True,
)


# ============================================================
# LLM
# ============================================================

model = OllamaLLM(
    model=MODEL,
    temperature=TEMPERATURE,
    num_ctx=NUM_CTX,
    num_predict=NUM_PREDICT,
)


# ============================================================
# PROMPT
# ============================================================

TEMPLATE = """
You are a professional sales consultant for Monster Connect
(mon.co.th), an IT solutions company in Thailand.

Answer the customer's question using ONLY the product information
provided below.

============================================================
PRODUCT INFORMATION
============================================================

{products}

============================================================
PRICE INFORMATION
============================================================

{price_table}

============================================================
ACTIVE PRODUCT
============================================================

{active_product}

============================================================
CONVERSATION
============================================================

{conversation_context}

============================================================
CUSTOMER QUESTION
============================================================

{question}

============================================================
IMPORTANT RULES
============================================================

LANGUAGE:

- Answer in the SAME language as the customer's question.
- English question -> English answer.
- Thai question -> Thai answer.
- Do not randomly switch languages.
- Thai and English/Latin characters are allowed.
- NEVER output Chinese characters.
- NEVER output Japanese characters.
- NEVER output Korean characters.

PRODUCT ACCURACY:

- Only talk about products contained in PRODUCT INFORMATION.
- Never invent a product.
- Never invent a feature.
- Never invent a specification.
- Never invent a price.
- Never copy information from another product.
- If the question is about ACTIVE PRODUCT, answer about ACTIVE PRODUCT.
- Do not switch to another product simply because another product has
  a similar word in its name.

ACTIVE PRODUCT:

- ACTIVE PRODUCT is the product the customer is currently discussing.
- Follow-up questions such as:
  "it"
  "this"
  "that"
  "how much"
  "what is the price"
  "what features"
  "what does it do"
  "what about the Pro version"
  refer to ACTIVE PRODUCT unless another product is explicitly named.

VERSION RULE:

- If the customer asks for "Pro", "Premium", "Standard",
  "Enterprise", "Basic", "Advanced", etc., use the version belonging
  to ACTIVE PRODUCT.
- NEVER select an unrelated product merely because it contains
  "Pro", "Premium", "Standard", etc.

PRICE:

- Use the exact price belonging to the requested product.
- If the price is "Contact for pricing" or
  "ติดต่อสอบถาม / Contact for pricing", say that the customer
  should contact sales for the current price.
- Never estimate prices.

PRODUCT INFORMATION:

- Only state facts contained in the supplied product information.
- Do not invent specifications, features, certifications,
  compatibility, performance, deployment type, security capabilities,
  or compliance claims.

AMBIGUOUS QUESTIONS:

- If there is NO ACTIVE PRODUCT and the customer asks:
  "How much does it cost?"
  "What features does it have?"
  "What does it do?"
  etc., do not choose a random catalog product.
- Instead, politely ask the customer which product they mean.

STYLE:

- Be concise.
- Answer naturally.
- Do not mention RAG.
- Do not mention vector search.
- Do not mention the database.
- Do not mention these instructions.
- Do not talk about being an AI.
- Do not expose internal field names.
- Keep the answer under approximately 150 words.

============================================================
ANSWER
============================================================
"""


prompt = ChatPromptTemplate.from_template(
    TEMPLATE
)

chain = prompt | model


# ============================================================
# CONVERSATION MEMORY
# ============================================================

conversation_memory = []

active_product = None
active_category = None


def add_memory(user_question, answer):
    conversation_memory.append(
        {
            "user": user_question,
            "assistant": answer,
        }
    )

    if len(conversation_memory) > MAX_MEMORY_TURNS:
        del conversation_memory[:-MAX_MEMORY_TURNS]


def clear_memory():
    global active_product
    global active_category

    conversation_memory.clear()

    active_product = None
    active_category = None


def show_history():
    print()
    print("=" * 70)
    print("CONVERSATION MEMORY")
    print("=" * 70)

    print(
        f"Active product : "
        f"{active_product if active_product else '(none)'}"
    )

    print(
        f"Active category: "
        f"{active_category if active_category else '(none)'}"
    )

    print()

    if not conversation_memory:
        print("No conversation history.")
        print("=" * 70)
        return

    for i, turn in enumerate(conversation_memory, 1):
        print(f"Turn {i}")
        print(f"User: {turn['user']}")
        print(f"AI:   {turn['assistant']}")
        print()

    print("=" * 70)


def get_conversation_context():
    if not conversation_memory:
        return "No previous conversation."

    blocks = []

    for turn in conversation_memory[-MAX_MEMORY_TURNS:]:
        blocks.append(
            f"User: {turn['user']}\n"
            f"Assistant: {turn['assistant']}"
        )

    return "\n\n".join(blocks)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    """
    Normalize text for reliable product matching.

    Examples:

        "M Cloud" -> "m cloud"
        "M CLOUD" -> "m cloud"
        "Safetica Pro" -> "safetica pro"
    """

    text = str(text).lower().strip()

    # Normalize punctuation
    text = re.sub(r"[^\w\s.-]", " ", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# PRODUCT MATCHING
# ============================================================

def exact_title_in_question(question):
    """
    Match a complete product title inside the question.

    IMPORTANT:
    We do NOT use arbitrary substring matching.

    This prevents:

        M Cloud
        ->
        NetEvidCloud

    because "cloud" is not enough to identify NetEvidCloud.
    """

    q = normalize_text(question)

    if not q:
        return None

    # Longest first
    for title in PRODUCT_TITLES:

        title_norm = normalize_text(title)

        if not title_norm:
            continue

        # Exact full phrase
        if re.search(
            rf"(?<!\w){re.escape(title_norm)}(?!\w)",
            q,
        ):
            return title

    return None


def get_product_tokens(title):
    """
    Return meaningful tokens from a product title.
    """

    normalized = normalize_text(title)

    tokens = normalized.split()

    # Remove extremely generic tokens.
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "of",
        "a",
        "an",
        "รุ่น",
    }

    return [
        token
        for token in tokens
        if token not in stopwords
    ]


def product_starts_with_phrase(title, phrase):
    """
    Check whether a product starts with an explicit phrase.

    This is important for:

        M Cloud รุ่น S ...

    so "M Cloud" can be recognized.

    But:

        NetEvidCloud

    will NOT match "M Cloud".
    """

    title_norm = normalize_text(title)
    phrase_norm = normalize_text(phrase)

    if not title_norm or not phrase_norm:
        return False

    return (
        title_norm == phrase_norm
        or title_norm.startswith(
            phrase_norm + " "
        )
    )


def find_product_alias(question):
    """
    Safely identify common shortened product names.

    Examples:

        "What is M Cloud?"
            -> M Cloud รุ่น S ราคาประหยัด (รายเดือน)

        "Tell me about Safetica"
            -> safetica

    We only accept aliases that are clearly anchored to the
    beginning of a product title.
    """

    q = normalize_text(question)

    if not q:
        return None

    # --------------------------------------------------------
    # Two-word explicit aliases
    # --------------------------------------------------------

    for title in PRODUCT_TITLES:

        tokens = get_product_tokens(title)

        if len(tokens) < 2:
            continue

        # Test first two meaningful tokens.
        alias = " ".join(tokens[:2])

        if len(alias) < 4:
            continue

        if re.search(
            rf"(?<!\w){re.escape(alias)}(?!\w)",
            q,
        ):
            if product_starts_with_phrase(
                title,
                alias,
            ):
                return title

    # --------------------------------------------------------
    # Single-token product names
    # --------------------------------------------------------

    for title in PRODUCT_TITLES:

        tokens = get_product_tokens(title)

        if len(tokens) != 1:
            continue

        token = tokens[0]

        if len(token) < 4:
            continue

        if re.search(
            rf"(?<!\w){re.escape(token)}(?!\w)",
            q,
        ):
            return title

    return None


def find_explicit_product(question):
    """
    Deterministic product identification.

    Priority:

    1. Exact complete product title
    2. Safe product alias

    Never uses vector similarity.
    Never guesses based on generic words.
    """

    exact = exact_title_in_question(question)

    if exact:
        return exact

    alias = find_product_alias(question)

    if alias:
        return alias

    return None


# ============================================================
# PRODUCT FAMILY
# ============================================================

VERSION_WORDS = [
    "pro",
    "premium",
    "standard",
    "enterprise",
    "basic",
    "advanced",
    "professional",
    "business",
    "essentials",
]


def get_product_family_name(product_name):
    """
    Get the base family name.

    Example:

        Safetica
        Safetica Pro
        Safetica Premium

    -> Safetica
    """

    if not product_name:
        return None

    title = normalize_text(product_name)

    tokens = title.split()

    if not tokens:
        return None

    # For "safetica pro", base is safetica.
    return tokens[0]


def find_family_products(product_name):
    """
    Find products belonging to the same product family.

    This is intentionally conservative.

    For Safetica:

        safetica
        safetica Pro
        safetica Premium

    are related.

    But:

        Windows 10 Pro

    is NOT related.
    """

    if not product_name:
        return pd.DataFrame()

    family = get_product_family_name(
        product_name
    )

    if not family:
        return pd.DataFrame()

    matches = []

    for _, row in df.iterrows():

        title = str(row["Title"]).strip()

        if not title:
            continue

        title_norm = normalize_text(title)

        tokens = title_norm.split()

        if not tokens:
            continue

        if tokens[0] == family:
            matches.append(row)

    if not matches:
        return pd.DataFrame()

    return pd.DataFrame(matches)


def find_version_product(
    base_product,
    requested_version,
):
    """
    Find a version only inside the active product family.

    Example:

        active = safetica
        version = pro

    -> safetica Pro

    Never returns Windows 10 Pro.
    """

    family_df = find_family_products(
        base_product
    )

    if family_df.empty:
        return None

    version = normalize_text(
        requested_version
    )

    candidates = []

    for _, row in family_df.iterrows():

        title = str(row["Title"]).strip()
        title_norm = normalize_text(title)

        if re.search(
            rf"(?<!\w){re.escape(version)}(?!\w)",
            title_norm,
        ):
            candidates.append(title)

    if not candidates:
        return None

    # Prefer the shortest matching title.
    # Example:
    #
    # safetica Pro
    # safetica Pro Enterprise
    #
    # choose safetica Pro.
    candidates.sort(
        key=len
    )

    return candidates[0]


# ============================================================
# INTENT DETECTION
# ============================================================

def is_price_question(question):
    q = normalize_text(question)

    phrases = [
        "how much",
        "price",
        "cost",
        "pricing",
        "how expensive",
        "ราคา",
        "ราคาเท่าไหร่",
        "ราคาเท่าไร",
        "กี่บาท",
        "คิดเงิน",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )


def is_feature_question(question):
    q = normalize_text(question)

    phrases = [
        "feature",
        "features",
        "what can it do",
        "what does it do",
        "what does this do",
        "what does that do",
        "capabilities",
        "ฟีเจอร์",
        "มีฟีเจอร์อะไร",
        "มีฟีเจอร์อะไรบ้าง",
        "ทำอะไรได้บ้าง",
        "มีอะไรบ้าง",
        "ความสามารถ",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )


def is_what_is_question(question):
    q = normalize_text(question)

    phrases = [
        "what is",
        "what are",
        "tell me about",
        "คืออะไร",
        "คือ",
        "เกี่ยวกับ",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )


def is_version_question(question):
    q = normalize_text(question)

    return bool(
        re.search(
            r"\b(?:pro|premium|standard|enterprise|"
            r"basic|advanced|professional|business|"
            r"essentials)\b",
            q,
        )
    )


def extract_version(question):
    q = normalize_text(question)

    match = re.search(
        r"\b(?:pro|premium|standard|enterprise|"
        r"basic|advanced|professional|business|"
        r"essentials)\b",
        q,
    )

    if match:
        return match.group(0)

    return None


def is_generic_followup(question):
    """
    Questions that normally refer to the active product.
    """

    q = normalize_text(question)

    patterns = [
        "how much",
        "price",
        "cost",
        "pricing",
        "what features",
        "what feature",
        "what does it do",
        "what can it do",
        "tell me more",
        "what about it",
        "what about this",
        "what about that",
        "the product",
        "this product",
        "that product",
        "it",
        "this",
        "that",
        "ราคา",
        "ฟีเจอร์",
        "ทำอะไรได้บ้าง",
        "มีฟีเจอร์อะไร",
    ]

    return any(
        pattern in q
        for pattern in patterns
    )


# ============================================================
# PRODUCT RESOLUTION
# ============================================================

def resolve_product(question):
    """
    Resolve the product WITHOUT using vector search.

    Order:

    1. Explicit exact product.
    2. Explicit safe alias.
    3. Explicit version of active product.
    4. Generic follow-up -> active product.
    5. Otherwise -> None.
    """

    global active_product

    # --------------------------------------------------------
    # STEP 1: Explicit product
    # --------------------------------------------------------

    explicit = find_explicit_product(
        question
    )

    if explicit:

        active_product = explicit

        return explicit

    # --------------------------------------------------------
    # STEP 2: Version request
    # --------------------------------------------------------

    if active_product and is_version_question(
        question
    ):

        version = extract_version(
            question
        )

        if version:

            version_product = (
                find_version_product(
                    active_product,
                    version,
                )
            )

            if version_product:

                active_product = (
                    version_product
                )

                return version_product

    # --------------------------------------------------------
    # STEP 3: Generic follow-up
    # --------------------------------------------------------

    if active_product and is_generic_followup(
        question
    ):
        return active_product

    return None


# ============================================================
# FOLLOW-UP QUERY REWRITING
# ============================================================

def rewrite_question(
    question,
    product,
):
    """
    Convert follow-ups into deterministic product-specific
    questions.

    Example:

        active = M Cloud

        "How much does it cost?"
        ->
        "What is the price of M Cloud?"

    """

    if not product:
        return question

    q = normalize_text(question)

    # --------------------------------------------------------
    # Price
    # --------------------------------------------------------

    if is_price_question(q):
        return (
            f"What is the price of "
            f"{product}?"
        )

    # --------------------------------------------------------
    # Features
    # --------------------------------------------------------

    if is_feature_question(q):
        return (
            f"What features does "
            f"{product} have?"
        )

    # --------------------------------------------------------
    # What is
    # --------------------------------------------------------

    if (
        is_what_is_question(q)
        and (
            "what is it" in q
            or "what is this" in q
            or "what is that" in q
            or "คืออะไร" in q
        )
    ):
        return (
            f"What is {product}?"
        )

    # --------------------------------------------------------
    # Generic follow-up
    # --------------------------------------------------------

    if is_generic_followup(q):

        return (
            f"Tell me about {product}. "
            f"Customer question: {question}"
        )

    return question


# ============================================================
# PRICE HELPERS
# ============================================================

def extract_price_thresholds(question):
    q = normalize_text(question)

    min_price = None
    max_price = None

    # Maximum
    max_match = re.search(
        r"""
        (?:
            under |
            below |
            less\ than |
            lower\ than |
            <=? |
            ไม่เกิน |
            ต่ำกว่า |
            น้อยกว่า
        )
        \s*
        ([\d,]+)
        """,
        q,
        re.VERBOSE,
    )

    if max_match:
        max_price = float(
            max_match.group(1)
            .replace(",", "")
        )

    # Minimum
    min_match = re.search(
        r"""
        (?:
            over |
            above |
            more\ than |
            higher\ than |
            greater\ than |
            >=? |
            มากกว่า |
            สูงกว่า
        )
        \s*
        ([\d,]+)
        """,
        q,
        re.VERBOSE,
    )

    if min_match:
        min_price = float(
            min_match.group(1)
            .replace(",", "")
        )

    return min_price, max_price


def is_ranking_query(question):
    q = normalize_text(question)

    words = [
        "top",
        "cheapest",
        "cheap",
        "lowest",
        "highest",
        "most expensive",
        "best",
        "recommend",
        "recommendation",
        "แนะนำ",
        "ถูกที่สุด",
        "แพงที่สุด",
        "ราคาถูก",
        "ราคาแพง",
        "อันดับ",
    ]

    return any(
        word in q
        for word in words
    )


# ============================================================
# CATEGORY
# ============================================================

def detect_category(
    question,
    current_category=None,
):

    q = normalize_text(question)

    if any(
        word in q
        for word in [
            "laptop",
            "notebook",
            "computer",
            "macbook",
            "thinkpad",
        ]
    ):
        return "laptop"

    if any(
        word in q
        for word in [
            "antivirus",
            "virus",
            "security",
            "protection",
            "edr",
            "xdr",
        ]
    ):
        return "antivirus"

    if any(
        word in q
        for word in [
            "firewall",
            "router",
            "networking",
            "network security",
        ]
    ):
        return "firewall"

    if any(
        word in q
        for word in [
            "backup",
            "recovery",
        ]
    ):
        return "backup"

    if any(
        word in q
        for word in [
            "siem",
            "log management",
            "log",
        ]
    ):
        return "log"

    return current_category


def filter_category(
    dataframe,
    category,
):

    if category is None:
        return dataframe

    data = dataframe.copy()

    title = data["Title"].astype(str)

    product_type = (
        data["Product_Type"]
        .astype(str)
        if "Product_Type" in data.columns
        else pd.Series(
            "",
            index=data.index,
        )
    )

    catalog_category = (
        data["Category"]
        .astype(str)
        if "Category" in data.columns
        else pd.Series(
            "",
            index=data.index,
        )
    )

    if category == "laptop":

        mask = (
            title.str.contains(
                r"laptop|notebook|expertbook|latitude|"
                r"thinkpad|thinkbook|travelmate|macbook",
                case=False,
                na=False,
            )
            |
            product_type.str.contains(
                "Laptop",
                case=False,
                na=False,
            )
        )

        exclude = title.str.contains(
            r"monitor|display|optiplex|thinkvision|aio|"
            r"all-in-one|sff",
            case=False,
            na=False,
        )

        return data[
            mask & ~exclude
        ]

    if category == "antivirus":

        mask = (
            title.str.contains(
                r"antivirus|falcon|sentinelone|sophos|"
                r"security|crowdstrike|singularity",
                case=False,
                na=False,
            )
            |
            product_type.str.contains(
                r"Antivirus|EDR|XDR",
                case=False,
                na=False,
            )
            |
            catalog_category.str.contains(
                r"Antivirus|Security",
                case=False,
                na=False,
            )
        )

        return data[mask]

    if category == "firewall":

        mask = (
            title.str.contains(
                r"fortigate|sophos|sonicwall|watchguard|firewall",
                case=False,
                na=False,
            )
            |
            product_type.str.contains(
                "Firewall",
                case=False,
                na=False,
            )
        )

        return data[mask]

    if category == "backup":

        mask = (
            title.str.contains(
                r"backup|recovery",
                case=False,
                na=False,
            )
            |
            product_type.str.contains(
                r"Backup|Recovery",
                case=False,
                na=False,
            )
        )

        return data[mask]

    if category == "log":

        mask = (
            title.str.contains(
                r"log|siem|zcrlog",
                case=False,
                na=False,
            )
            |
            product_type.str.contains(
                r"SIEM|Log Management",
                case=False,
                na=False,
            )
        )

        return data[mask]

    return data


# ============================================================
# EXACT PRODUCT DATA
# ============================================================

def get_exact_product_rows(
    product,
):
    """
    Return exact product rows.

    This is intentionally NOT a substring search.

    Safetica -> safetica
    Safetica Pro -> safetica Pro

    They are separate products.
    """

    if not product:
        return pd.DataFrame()

    target = normalize_text(
        product
    )

    matches = df[
        df["Title"]
        .astype(str)
        .apply(
            normalize_text
        )
        == target
    ].copy()

    return matches


# ============================================================
# STRUCTURED PRICE ENGINE
# ============================================================

def format_product_price(row):
    title = str(
        row["Title"]
    ).strip()

    price = str(
        row["Price_Display"]
    ).strip()

    if not price:
        price = (
            "ติดต่อสอบถาม / "
            "Contact for pricing"
        )

    return (
        f"• {title} — {price}"
    )


def handle_structured_query(
    question,
    product=None,
    category=None,
):
    """
    Handle deterministic catalog queries.

    IMPORTANT:
    Generic price questions NEVER return random products
    when an active product exists.
    """

    q = normalize_text(
        question
    )

    min_price, max_price = (
        extract_price_thresholds(q)
    )

    # ========================================================
    # PRODUCT-SPECIFIC PRICE
    # ========================================================

    if (
        product
        and is_price_question(q)
        and min_price is None
        and max_price is None
    ):

        matches = get_exact_product_rows(
            product
        )

        if not matches.empty:

            results = []

            for _, row in matches.iterrows():
                results.append(
                    format_product_price(
                        row
                    )
                )

            return "\n".join(results)

        return (
            f"• {product} — "
            f"ติดต่อสอบถาม / Contact for pricing"
        )

    # ========================================================
    # NO ACTIVE PRODUCT + GENERIC PRICE
    # ========================================================

    if (
        not product
        and is_price_question(q)
        and min_price is None
        and max_price is None
    ):

        return (
            "Which product would you like to "
            "check the price for?"
        )

    # ========================================================
    # RANKING / PRICE RANGE
    # ========================================================

    if (
        is_ranking_query(q)
        or min_price is not None
        or max_price is not None
    ):

        filtered = df.dropna(
            subset=["Price_num"]
        ).copy()

        filtered = filter_category(
            filtered,
            category,
        )

        if max_price is not None:
            filtered = filtered[
                filtered["Price_num"]
                <= max_price
            ]

        if min_price is not None:
            filtered = filtered[
                filtered["Price_num"]
                >= min_price
            ]

        if filtered.empty:
            return (
                "No matching products were found "
                "for the requested criteria."
            )

        expensive = any(
            word in q
            for word in [
                "expensive",
                "highest",
                "most expensive",
                "แพงที่สุด",
                "ราคาแพง",
                "สูงสุด",
            ]
        )

        ascending = not expensive

        # Try to extract requested number
        number_match = re.search(
            r"\b(\d+)\b",
            q,
        )

        if number_match:
            n = int(
                number_match.group(1)
            )
        else:
            n = 5

        n = max(
            1,
            min(n, 10),
        )

        top_df = (
            filtered
            .sort_values(
                by="Price_num",
                ascending=ascending,
            )
            .head(n)
        )

        results = []

        for _, row in top_df.iterrows():
            results.append(
                format_product_price(
                    row
                )
            )

        return "\n".join(results)

    return None


# ============================================================
# RAG CONTEXT
# ============================================================

def build_rag_context(
    docs,
    preferred_product=None,
):
    """
    Build RAG context.

    If a specific product is active, we prefer that product
    and avoid feeding unrelated products to the LLM.
    """

    if not docs:
        return "", ""

    # --------------------------------------------------------
    # If active product exists, find exact document first.
    # --------------------------------------------------------

    if preferred_product:

        preferred_norm = normalize_text(
            preferred_product
        )

        exact_docs = []

        for doc in docs:

            title = str(
                doc.metadata.get(
                    "title",
                    "",
                )
            ).strip()

            if (
                normalize_text(title)
                == preferred_norm
            ):
                exact_docs.append(doc)

        # If exact document exists, ONLY use it.
        if exact_docs:
            docs = exact_docs[:1]

    blocks = []
    price_rows = []

    for i, doc in enumerate(
        docs,
        1,
    ):

        metadata = doc.metadata

        title = str(
            metadata.get(
                "title",
                "Unknown product",
            )
        ).strip()

        vendor = str(
            metadata.get(
                "vendor",
                "",
            )
        ).strip()

        price = str(
            metadata.get(
                "price",
                "",
            )
        ).strip()

        if not price:
            price = (
                "ติดต่อสอบถาม / "
                "Contact for pricing"
            )

        content = str(
            doc.page_content
        )[:MAX_DOC_CHARS]

        blocks.append(
            f"### PRODUCT {i}\n"
            f"NAME: {title}\n"
            f"VENDOR: {vendor}\n"
            f"PRICE: {price}\n"
            f"{content}"
        )

        price_rows.append(
            f"{i}. {title} = {price}"
        )

    return (
        "\n\n".join(blocks),
        "\n".join(price_rows),
    )


# ============================================================
# RAG RETRIEVAL
# ============================================================

def retrieve_documents(
    question,
    active_product=None,
):
    """
    Retrieve documents.

    If there is an active product, the rewritten question
    contains the exact product name, so the vector search has
    much stronger grounding.

    We additionally post-filter exact product matches.
    """

    docs = retriever.invoke(
        question
    )

    if not docs:
        return []

    # --------------------------------------------------------
    # Active product:
    # prefer exact matching document
    # --------------------------------------------------------

    if active_product:

        target = normalize_text(
            active_product
        )

        exact = []

        for doc in docs:

            title = str(
                doc.metadata.get(
                    "title",
                    "",
                )
            ).strip()

            if (
                normalize_text(title)
                == target
            ):
                exact.append(doc)

        if exact:
            return exact[:1]

    return docs[:RAG_K]


# ============================================================
# CJK PROTECTION
# ============================================================

CJK = re.compile(
    r"[\u3040-\u30ff"
    r"\u3400-\u4dbf"
    r"\u4e00-\u9fff"
    r"\uac00-\ud7af]"
)


def strip_invalid_cjk(
    text,
):
    """
    Remove lines containing Chinese/Japanese/Korean
    characters.

    Thai is NOT removed.
    """

    if not text:
        return ""

    lines = text.splitlines()

    kept = []

    for line in lines:

        if CJK.search(line):
            continue

        if line.strip():
            kept.append(
                line
            )

    return "\n".join(
        kept
    ).strip()


# ============================================================
# ANSWER GENERATION
# ============================================================

def generate_answer(
    question,
    context,
    price_table,
):
    global active_product

    current_product = (
        active_product
        if active_product
        else "(none)"
    )

    conversation_context = (
        get_conversation_context()
    )

    ask = question

    for attempt in range(
        1,
        MAX_TRIES + 1,
    ):

        answer = chain.invoke(
            {
                "products": context,
                "price_table": price_table,
                "conversation_context":
                    conversation_context,
                "active_product":
                    current_product,
                "question": ask,
            }
        )

        answer = str(
            answer
        ).strip()

        # ----------------------------------------------------
        # CJK validation
        # ----------------------------------------------------

        if not CJK.search(answer):
            return answer

        print(
            f"[retry {attempt}] "
            f"Invalid CJK characters detected."
        )

        ask = (
            question
            + "\n\n"
            "IMPORTANT: Answer ONLY in the same "
            "language as the customer. "
            "Thai and English are allowed. "
            "Do NOT use Chinese, Japanese, "
            "or Korean characters."
        )

    # Last resort
    cleaned = strip_invalid_cjk(
        answer
    )

    return cleaned


# ============================================================
# DEBUG
# ============================================================

def print_debug(
    question,
    previous_product,
    resolved_product,
    effective_question,
    docs=None,
):

    print()

    print(
        f"[DEBUG] Previous product: "
        f"{previous_product}"
    )

    print(
        f"[DEBUG] Resolved product: "
        f"{resolved_product}"
    )

    print(
        f"[DEBUG] Active product: "
        f"{active_product}"
    )

    print(
        f"[DEBUG] Category: "
        f"{active_category}"
    )

    print(
        f"[DEBUG] Price question: "
        f"{is_price_question(question)}"
    )

    print(
        f"[DEBUG] Feature question: "
        f"{is_feature_question(question)}"
    )

    print(
        f"[DEBUG] Effective query: "
        f"{effective_question}"
    )

    if docs is not None:

        print()
        print(
            f"[DEBUG] Retrieved "
            f"{len(docs)} documents"
        )

        for i, doc in enumerate(
            docs,
            1,
        ):

            title = doc.metadata.get(
                "title",
                "Unknown",
            )

            print(
                f"  {i}. {title}"
            )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    debug = False

    active_product = None
    active_category = None

    print()
    print("=" * 70)
    print("Monster Connect AI Sales Assistant")
    print("=" * 70)

    print(
        f"Model       : {MODEL}"
    )

    print(
        f"Dataset     : {DATASET}"
    )

    print(
        "Vector      : vector_v2 / MMR"
    )

    print(
        f"Products    : {len(df)}"
    )

    print(
        f"Memory      : {MAX_MEMORY_TURNS} turns"
    )

    print()

    print("Commands:")
    print(
        "  q       = quit"
    )
    print(
        "  clear   = clear conversation memory"
    )
    print(
        "  history = show conversation memory"
    )
    print(
        "  debug   = toggle debug information"
    )

    print("=" * 70)

    while True:

        question = input(
            "\nAsk your question (q to quit): "
        ).strip()

        if not question:
            continue

        # ====================================================
        # COMMANDS
        # ====================================================

        if question.lower() == "q":
            break

        if question.lower() == "clear":

            clear_memory()

            print(
                "\nConversation memory cleared."
            )

            continue

        if question.lower() == "history":

            show_history()

            continue

        if question.lower() == "debug":

            debug = not debug

            print(
                f"debug = {debug}"
            )

            continue

        # ====================================================
        # CATEGORY
        # ====================================================

        detected_category = detect_category(
            question,
            active_category,
        )

        if detected_category:
            active_category = (
                detected_category
            )

        # ====================================================
        # PRODUCT RESOLUTION
        # ====================================================

        previous_product = (
            active_product
        )

        resolved_product = (
            resolve_product(
                question
            )
        )

        # ====================================================
        # EFFECTIVE QUESTION
        # ====================================================

        effective_question = (
            rewrite_question(
                question,
                resolved_product,
            )
        )

        # ====================================================
        # DEBUG BEFORE STRUCTURED ENGINE
        # ====================================================

        if debug:

            print_debug(
                question,
                previous_product,
                resolved_product,
                effective_question,
            )

        # ====================================================
        # IMPORTANT:
        #
        # Generic feature question without active product
        # should NOT search random products.
        # ====================================================

        if (
            is_feature_question(question)
            and not active_product
        ):

            answer = (
                "Which product would you like "
                "to know the features of?"
            )

            print(
                "\nAI Answer:\n"
            )

            print(answer)

            add_memory(
                question,
                answer,
            )

            continue

        # ====================================================
        # STRUCTURED DATA ENGINE
        # ====================================================

        structured_response = (
            handle_structured_query(
                effective_question,
                product=active_product,
                category=active_category,
            )
        )

        if structured_response:

            print(
                "\nAI Answer (Data Engine):\n"
            )

            print(
                structured_response
            )

            add_memory(
                question,
                structured_response,
            )

            continue

        # ====================================================
        # RAG
        # ====================================================

        try:

            docs = retrieve_documents(
                effective_question,
                active_product=active_product,
            )

        except Exception as e:

            print(
                "\n[ERROR] Vector retrieval failed:"
            )

            print(
                f"{type(e).__name__}: {e}"
            )

            continue

        # ====================================================
        # DEBUG RETRIEVAL
        # ====================================================

        if debug:

            print_debug(
                question,
                previous_product,
                resolved_product,
                effective_question,
                docs,
            )

        # ====================================================
        # BUILD CONTEXT
        # ====================================================

        context, price_table = (
            build_rag_context(
                docs,
                preferred_product=active_product,
            )
        )

        if debug:

            print()
            print(
                f"[DEBUG] Context size: "
                f"{len(context)} characters"
            )

        # ====================================================
        # GENERATE
        # ====================================================

        try:

            answer = generate_answer(
                effective_question,
                context,
                price_table,
            )

        except Exception as e:

            print(
                "\n[ERROR] LLM generation failed:"
            )

            print(
                f"{type(e).__name__}: {e}"
            )

            continue

        # ====================================================
        # OUTPUT
        # ====================================================

        print(
            "\nAI Answer (RAG Engine):\n"
        )

        print(answer)

        # ====================================================
        # MEMORY
        # ====================================================

        add_memory(
            question,
            answer,
        )

        # ====================================================
        # DEBUG PRODUCTS
        # ====================================================

        if debug:

            print()
            print(
                "Products I looked at:"
            )

            for doc in docs:

                title = doc.metadata.get(
                    "title",
                    "Unknown",
                )

                print(
                    f"  - {title}"
                )