import re
import difflib
from typing import Optional, Tuple, List

import pandas as pd

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever


# ============================================================
# CONFIGURATION
# ============================================================

MODEL = "qwen2.5:7b"

NUM_CTX = 16384
NUM_PREDICT = 700
TEMPERATURE = 0.1

DATASET = "products_enriched.csv"

MAX_MEMORY_TURNS = 6
MAX_DOC_CHARS = 1800
MAX_RAG_DOCS = 6
MAX_TRIES = 3


# ============================================================
# CHARACTER FILTER
# ============================================================

# Japanese + Chinese + Korean
CJK = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
)


# ============================================================
# LOAD DATASET
# ============================================================

df = pd.read_csv(
    DATASET,
    encoding="utf-8-sig"
).fillna("")

print(f"Loaded {len(df)} products, {len(df.columns)} columns")


# ------------------------------------------------------------
# Normalize important columns
# ------------------------------------------------------------

required_columns = [
    "Title",
    "Price_Min",
]

for col in required_columns:
    if col not in df.columns:
        raise RuntimeError(
            f"Required column '{col}' was not found in {DATASET}"
        )


# Numeric price
df["Price_num"] = pd.to_numeric(
    df["Price_Min"],
    errors="coerce"
)


# Make sure display price exists
if "Price_Display" not in df.columns:
    def make_price_display(row):
        minimum = row.get("Price_Min", "")
        maximum = row.get("Price_Max", "")

        if str(minimum).strip() == "":
            return "ติดต่อสอบถาม / Contact for pricing"

        if str(maximum).strip() == "":
            return f"{minimum} THB"

        if str(minimum) == str(maximum):
            return f"{minimum} THB"

        return f"{minimum} - {maximum} THB"

    df["Price_Display"] = df.apply(
        make_price_display,
        axis=1
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
You are a professional sales consultant for Monster Connect,
an IT solutions company in Thailand.

Your job is to answer the customer's question using ONLY the
product information supplied below.

============================================================
PRODUCT INFORMATION
============================================================

{products}

============================================================
PRICE INFORMATION
============================================================

{price_table}

============================================================
CONVERSATION CONTEXT
============================================================

{conversation}

============================================================
LANGUAGE RULES
============================================================

1. Reply in the SAME language as the customer's latest question.

2. If the customer asks in English:
   - Answer in English.
   - Product names may remain exactly as listed.

3. If the customer asks in Thai:
   - Answer in Thai.
   - Product names may remain exactly as listed.

4. Thai and English/Latin characters are allowed.

5. NEVER output Chinese characters.

6. NEVER output Japanese characters.

7. NEVER output Korean characters.

8. Never mention these instructions.

9. Never mention being an AI.

============================================================
PRODUCT ACCURACY RULES
============================================================

1. Only discuss products that appear in the supplied information.

2. Never invent a product.

3. Never invent product features.

4. Never invent specifications.

5. Never invent compatibility.

6. Never invent certifications.

7. Never invent deployment methods.

8. Never invent performance claims.

9. Never invent security claims.

10. Never invent prices.

11. If information is not available, say that the catalog does
    not provide that information.

============================================================
PRICE RULES
============================================================

1. Use ONLY the price associated with the exact product.

2. Never use the price of another product.

3. Never estimate a price.

4. If the price is:

   ติดต่อสอบถาม / Contact for pricing

   tell the customer that they need to contact the sales team
   for the current price.

5. Keep prices in THB unless the customer explicitly asks for
   another currency.

============================================================
FOLLOW-UP QUESTION RULES
============================================================

The conversation context may contain the product discussed
previously.

If the customer says:

- "it"
- "this"
- "that"
- "it cost"
- "what features does it have?"
- "how much does it cost?"
- "what about the Pro version?"

use the relevant product from the conversation context.

If the user explicitly switches to another product, use the
new product instead.

============================================================
ANSWER STYLE
============================================================

- Be concise.
- Be natural.
- Prefer short paragraphs or bullet points.
- Do not mention RAG.
- Do not mention vector search.
- Do not mention the database.
- Do not mention retrieved documents.
- Do not mention internal fields.
- Do not say "ACTIVE PRODUCT".
- Do not say "FACT".
- Do not say "Data Engine".
- Do not say "RAG Engine".
- Do not repeat the customer's question.
- Do not exceed 150 words unless more detail is requested.

============================================================
CUSTOMER QUESTION
============================================================

{question}

============================================================
ANSWER
============================================================
"""


prompt = ChatPromptTemplate.from_template(TEMPLATE)

chain = prompt | model


# ============================================================
# BASIC TEXT HELPERS
# ============================================================

def normalize_text(text: str) -> str:
    """
    Normalize text for product matching.
    """
    text = str(text).lower().strip()

    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("_", " ")

    # Remove most punctuation but keep useful product symbols
    text = re.sub(r"[^\w\s\-.+&/]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def compact(text: str) -> str:
    """
    Remove spaces and punctuation for loose matching.
    """
    return re.sub(
        r"[^a-z0-9ก-๙]+",
        "",
        normalize_text(text)
    )


def strip_cjk(text: str) -> str:
    """
    Remove sentences containing unsupported CJK characters.
    Thai characters are NOT included in the CJK regex.
    """

    parts = re.split(
        r"(?<=[.!?。！？])\s+|\n",
        text
    )

    kept = []

    for part in parts:
        part = part.strip()

        if not part:
            continue

        if not CJK.search(part):
            kept.append(part)

    return "\n".join(kept).strip()


def contains_cjk(text: str) -> bool:
    return bool(CJK.search(text))


# ============================================================
# QUESTION INTENT
# ============================================================

def is_price_question(query: str) -> bool:
    q = normalize_text(query)

    phrases = [
        "how much",
        "how much is",
        "how much does",
        "price",
        "price of",
        "cost",
        "cost of",
        "what is the price",
        "what's the price",

        "ราคา",
        "ราคาเท่าไหร่",
        "ราคาเท่าไร",
        "กี่บาท",
        "เท่าไหร่",
        "เท่าไร",
        "ค่าใช้จ่าย",
    ]

    return any(p in q for p in phrases)


def is_feature_question(query: str) -> bool:
    q = normalize_text(query)

    phrases = [
        "what features",
        "what feature",
        "features",
        "feature",
        "what can it do",
        "what does it do",
        "capabilities",
        "specifications",
        "specs",

        "มีฟีเจอร์อะไร",
        "มีฟีเจอร์อะไรบ้าง",
        "ฟีเจอร์",
        "คุณสมบัติ",
        "ทำอะไรได้บ้าง",
        "ความสามารถ",
        "สเปค",
        "รายละเอียด",
    ]

    return any(p in q for p in phrases)


def is_comparison_question(query: str) -> bool:
    q = normalize_text(query)

    return any(
        phrase in q
        for phrase in [
            "compare",
            "comparison",
            "difference",
            "different",
            "versus",
            "vs",
            "เปรียบเทียบ",
            "ต่างกัน",
            "แตกต่าง",
        ]
    )


def is_followup_question(query: str) -> bool:
    q = normalize_text(query)

    followups = [
        "it",
        "this",
        "that",
        "these",
        "those",
        "it cost",
        "how much does it",
        "what features does it have",
        "what features does it",
        "what about",
        "another version",
        "another variant",

        "มัน",
        "ตัวนี้",
        "อันนี้",
        "รุ่นนี้",
        "เวอร์ชันนี้",
        "รุ่นอื่น",
        "อีกเวอร์ชัน",
        "อีกตัว",
    ]

    return any(
        phrase in q
        for phrase in followups
    )


# ============================================================
# CATEGORY DETECTION
# ============================================================

def detect_category(query: str) -> Optional[str]:

    q = normalize_text(query)

    if any(
        word in q
        for word in [
            "laptop",
            "notebook",
            "macbook",
            "thinkpad",
            "travelmate",
            "latitude",
        ]
    ):
        return "laptop"

    if any(
        word in q
        for word in [
            "antivirus",
            "virus",
            "endpoint",
            "edr",
            "xdr",
            "crowdstrike",
            "security software",
        ]
    ):
        return "antivirus"

    if any(
        word in q
        for word in [
            "firewall",
            "router",
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

    return None


# ============================================================
# PRODUCT MATCHING
# ============================================================

def product_titles() -> List[str]:
    return [
        str(x).strip()
        for x in df["Title"].tolist()
        if str(x).strip()
    ]


def get_row_by_title(title: str):
    if not title:
        return None

    matches = df[
        df["Title"].astype(str).str.lower()
        == title.lower()
    ]

    if matches.empty:
        return None

    return matches.iloc[0]


def exact_product_match(query: str) -> Optional[str]:
    """
    Find a product when its title/name is explicitly present
    in the customer's question.

    Longest match wins.
    """

    q_norm = normalize_text(query)

    candidates = []

    for title in product_titles():

        title_norm = normalize_text(title)

        if len(title_norm) < 3:
            continue

        if title_norm in q_norm:
            candidates.append(title)

    if candidates:
        return max(
            candidates,
            key=len
        )

    return None


def special_product_alias(query: str) -> Optional[str]:
    """
    Handle common human-friendly product names that may not
    exactly match the CSV title.
    """

    q = normalize_text(query)

    # --------------------------------------------------------
    # M Cloud
    # --------------------------------------------------------

    if re.search(
        r"\bm\s*cloud\b",
        q,
        re.IGNORECASE
    ):
        matches = df[
            df["Title"]
            .astype(str)
            .str.contains(
                r"^M Cloud",
                case=False,
                regex=True,
                na=False,
            )
        ]

        if len(matches) == 1:
            return matches.iloc[0]["Title"]

        if not matches.empty:
            # Prefer the S monthly product
            preferred = matches[
                matches["Title"]
                .astype(str)
                .str.contains(
                    r"รุ่น S|รายเดือน",
                    case=False,
                    regex=True,
                    na=False,
                )
            ]

            if not preferred.empty:
                return preferred.iloc[0]["Title"]

            return matches.iloc[0]["Title"]

    # --------------------------------------------------------
    # Safetica
    # --------------------------------------------------------

    if re.search(
        r"\bsafetica\b",
        q,
        re.IGNORECASE
    ):
        # Do NOT automatically select Pro/Premium.
        # The base Safetica product should be selected.
        matches = df[
            df["Title"]
            .astype(str)
            .str.fullmatch(
                r"safetica",
                case=False,
                na=False,
            )
        ]

        if not matches.empty:
            return matches.iloc[0]["Title"]

        # Fallback to any title starting with Safetica,
        # but prefer the shortest one.
        matches = df[
            df["Title"]
            .astype(str)
            .str.contains(
                r"^safetica",
                case=False,
                regex=True,
                na=False,
            )
        ]

        if not matches.empty:
            return sorted(
                matches["Title"].tolist(),
                key=len
            )[0]

    return None


def find_variant_of_product(
    query: str,
    active_product: Optional[str]
) -> Optional[str]:

    if not active_product:
        return None

    q = normalize_text(query)

    # --------------------------------------------------------
    # Pro version
    # --------------------------------------------------------

    pro_words = [
        "pro version",
        "pro version?",
        "pro",
        "professional version",
        "รุ่น pro",
        "เวอร์ชัน pro",
    ]

    asks_pro = any(
        phrase in q
        for phrase in pro_words
    )

    if not asks_pro:
        return None

    active_norm = normalize_text(active_product)

    # Extract brand/base product.
    # Example:
    # safetica -> safetica
    # safetica Essentials -> safetica
    # M Cloud ... -> M Cloud
    base = active_norm

    if "safetica" in active_norm:
        base = "safetica"

    # Search for variants
    matches = df[
        df["Title"]
        .astype(str)
        .str.lower()
        .str.contains(
            re.escape(base),
            regex=True,
            na=False,
        )
    ].copy()

    if matches.empty:
        return None

    # Prefer exact Pro
    pro_matches = matches[
        matches["Title"]
        .astype(str)
        .str.contains(
            r"\bpro\b",
            case=False,
            regex=True,
            na=False,
        )
    ]

    if not pro_matches.empty:

        # Prefer "safetica Pro" over unrelated products
        exact_pro = pro_matches[
            pro_matches["Title"]
            .astype(str)
            .str.fullmatch(
                r"safetica\s+pro",
                case=False,
                na=False,
            )
        ]

        if not exact_pro.empty:
            return exact_pro.iloc[0]["Title"]

        return pro_matches.iloc[0]["Title"]

    return None


def fuzzy_product_match(query: str) -> Optional[str]:
    """
    Conservative fuzzy matching.

    This is intentionally NOT used for generic follow-up
    questions such as "What features does it have?"
    """

    q = normalize_text(query)

    if len(q) < 4:
        return None

    # Do not fuzzy-match generic questions.
    generic_words = [
        "what",
        "which",
        "how",
        "does",
        "have",
        "features",
        "feature",
        "price",
        "cost",
        "much",
        "tell",
        "about",
        "product",
        "products",
        "ราคา",
        "ฟีเจอร์",
        "คุณสมบัติ",
    ]

    if all(
        word in generic_words
        for word in q.split()
    ):
        return None

    titles = product_titles()

    # Compare against normalized titles
    normalized_titles = [
        normalize_text(title)
        for title in titles
    ]

    matches = difflib.get_close_matches(
        q,
        normalized_titles,
        n=1,
        cutoff=0.72,
    )

    if not matches:
        return None

    normalized_match = matches[0]

    for title in titles:
        if normalize_text(title) == normalized_match:
            return title

    return None


def resolve_product(
    query: str,
    active_product: Optional[str]
) -> Optional[str]:
    """
    Resolve the product relevant to the current question.

    Priority:

    1. Explicit exact product
    2. Known aliases
    3. Product variant
    4. Follow-up -> active product
    5. Conservative fuzzy matching
    """

    # --------------------------------------------------------
    # 1. Explicit exact product
    # --------------------------------------------------------

    match = exact_product_match(query)

    if match:
        return match

    # --------------------------------------------------------
    # 2. Known aliases
    # --------------------------------------------------------

    alias = special_product_alias(query)

    if alias:
        return alias

    # --------------------------------------------------------
    # 3. Variant
    # --------------------------------------------------------

    variant = find_variant_of_product(
        query,
        active_product
    )

    if variant:
        return variant

    # --------------------------------------------------------
    # 4. Follow-up question
    # --------------------------------------------------------

    if active_product and is_followup_question(query):
        return active_product

    # --------------------------------------------------------
    # 5. Fuzzy matching
    # --------------------------------------------------------

    fuzzy = fuzzy_product_match(query)

    if fuzzy:
        return fuzzy

    return None


# ============================================================
# CATEGORY FILTERING
# ============================================================

def filter_category(
    dataframe,
    category: Optional[str]
):

    if category is None:
        return dataframe

    data = dataframe.copy()

    title = data["Title"].astype(str)

    product_type = (
        data["Product_Type"].astype(str)
        if "Product_Type" in data.columns
        else pd.Series("", index=data.index)
    )

    catalog_category = (
        data["Category"].astype(str)
        if "Category" in data.columns
        else pd.Series("", index=data.index)
    )

    if category == "laptop":

        mask = (
            title.str.contains(
                r"laptop|notebook|expertbook|latitude|thinkpad|"
                r"thinkbook|travelmate|macbook",
                case=False,
                regex=True,
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
            r"all-in-one|sff|m70a|v50a",
            case=False,
            regex=True,
            na=False,
        )

        return data[mask & ~exclude]

    if category == "antivirus":

        mask = (
            title.str.contains(
                r"antivirus|falcon|sentinelone|sophos|"
                r"security|crowdstrike|singularity",
                case=False,
                regex=True,
                na=False,
            )
            |
            product_type.str.contains(
                r"Antivirus|EDR|XDR",
                case=False,
                regex=True,
                na=False,
            )
            |
            catalog_category.str.contains(
                r"Antivirus|Security",
                case=False,
                regex=True,
                na=False,
            )
        )

        return data[mask]

    if category == "firewall":

        mask = (
            title.str.contains(
                r"fortigate|sophos|sonicwall|watchguard|firewall",
                case=False,
                regex=True,
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
                regex=True,
                na=False,
            )
            |
            product_type.str.contains(
                r"Backup|Recovery",
                case=False,
                regex=True,
                na=False,
            )
        )

        return data[mask]

    if category == "log":

        mask = (
            title.str.contains(
                r"log|siem|zcrlog",
                case=False,
                regex=True,
                na=False,
            )
            |
            product_type.str.contains(
                r"SIEM|Log Management",
                case=False,
                regex=True,
                na=False,
            )
        )

        return data[mask]

    return data


# ============================================================
# PRICE HELPERS
# ============================================================

def extract_price_thresholds(
    query: str
) -> Tuple[Optional[float], Optional[float]]:

    q = normalize_text(query)

    min_price = None
    max_price = None

    max_match = re.search(
        r"""
        (?:
            under |
            less\s+than |
            lower\s+than |
            below |
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
            max_match.group(1).replace(",", "")
        )

    min_match = re.search(
        r"""
        (?:
            above |
            over |
            more\s+than |
            higher\s+than |
            greater\s+than |
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
            min_match.group(1).replace(",", "")
        )

    return min_price, max_price


def remove_price_words(query: str) -> str:

    q = normalize_text(query)

    phrases = [
        "what is the price of",
        "what's the price of",
        "how much does",
        "how much is",
        "how much",
        "price of",
        "cost of",
        "price",
        "cost",

        "ราคาเท่าไหร่",
        "ราคาเท่าไร",
        "ราคา",
        "กี่บาท",
        "เท่าไหร่",
        "เท่าไร",
    ]

    for phrase in phrases:
        q = q.replace(
            phrase,
            " "
        )

    return re.sub(
        r"\s+",
        " ",
        q
    ).strip()


# ============================================================
# PRODUCT ROW -> CONTEXT
# ============================================================

def row_to_context(row) -> str:
    """
    Convert one CSV row into clean factual context.

    We intentionally include all useful non-empty fields.
    This avoids the LLM needing to guess from a generic
    vector result.
    """

    lines = []

    for column in df.columns:

        if column == "Price_num":
            continue

        value = str(
            row.get(column, "")
        ).strip()

        if not value:
            continue

        if column == "Price_Display":
            continue

        lines.append(
            f"{column}: {value}"
        )

    return "\n".join(lines)


def row_price(row) -> str:

    price = str(
        row.get(
            "Price_Display",
            ""
        )
    ).strip()

    if not price:
        return "ติดต่อสอบถาม / Contact for pricing"

    return price


def build_single_product_context(
    title: str
):

    row = get_row_by_title(title)

    if row is None:
        return None, None

    context = row_to_context(row)

    price = row_price(row)

    price_table = (
        f"{title} = {price}"
    )

    return context, price_table


# ============================================================
# STRUCTURED PRICE ENGINE
# ============================================================

def handle_price_query(
    query: str,
    active_product: Optional[str],
    category: Optional[str]
) -> Optional[str]:

    if not is_price_question(query):
        return None

    # --------------------------------------------------------
    # 1. If we have an active product, ALWAYS use it.
    # --------------------------------------------------------

    if active_product:

        row = get_row_by_title(
            active_product
        )

        if row is not None:

            return (
                f"• {row['Title']} — "
                f"{row_price(row)}"
            )

    # --------------------------------------------------------
    # 2. User explicitly named a product
    # --------------------------------------------------------

    explicit = resolve_product(
        query,
        active_product=None
    )

    if explicit:

        row = get_row_by_title(
            explicit
        )

        if row is not None:

            return (
                f"• {row['Title']} — "
                f"{row_price(row)}"
            )

    # --------------------------------------------------------
    # 3. Price search across catalog
    # --------------------------------------------------------

    search_query = remove_price_words(
        query
    )

    if len(search_query) > 1:

        title_series = (
            df["Title"]
            .astype(str)
        )

        mask = title_series.str.contains(
            re.escape(search_query),
            case=False,
            regex=True,
            na=False,
        )

        if "Vendor" in df.columns:

            mask = (
                mask
                |
                df["Vendor"]
                .astype(str)
                .str.contains(
                    re.escape(search_query),
                    case=False,
                    regex=True,
                    na=False,
                )
            )

        matches = df[mask].copy()

        if not matches.empty:

            matches = matches.sort_values(
                by="Price_num",
                ascending=True,
                na_position="last",
            )

            results = []

            for _, row in matches.head(5).iterrows():

                results.append(
                    f"• {row['Title']} — "
                    f"{row_price(row)}"
                )

            return "\n".join(results)

    # --------------------------------------------------------
    # 4. Generic price question
    # --------------------------------------------------------

    return (
        "Please specify the product you want the price for."
    )


# ============================================================
# RANKING / RECOMMENDATION
# ============================================================

def is_ranking_query(query: str) -> bool:

    q = normalize_text(query)

    return any(
        phrase in q
        for phrase in [
            "top",
            "cheapest",
            "cheaper",
            "cheap",
            "lowest price",
            "least expensive",
            "expensive",
            "highest price",
            "most expensive",
            "best",
            "recommend",
            "recommendation",

            "แนะนำ",
            "ถูกที่สุด",
            "ราคาถูก",
            "แพงที่สุด",
            "ราคาแพง",
            "อันดับ",
        ]
    )


def handle_ranking_query(
    query: str,
    category: Optional[str]
) -> Optional[str]:

    if not is_ranking_query(query):
        return None

    min_price, max_price = extract_price_thresholds(
        query
    )

    filtered = df.dropna(
        subset=["Price_num"]
    ).copy()

    filtered = filter_category(
        filtered,
        category
    )

    if max_price is not None:

        filtered = filtered[
            filtered["Price_num"] < max_price
        ]

    if min_price is not None:

        filtered = filtered[
            filtered["Price_num"] > min_price
        ]

    if filtered.empty:

        return (
            "No matching products were found "
            "for the requested criteria."
        )

    expensive = any(
        word in normalize_text(query)
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

    top_df = (
        filtered
        .sort_values(
            by="Price_num",
            ascending=ascending,
        )
        .head(5)
    )

    results = []

    for _, row in top_df.iterrows():

        results.append(
            f"• {row['Title']} — "
            f"{row_price(row)}"
        )

    return "\n".join(results)


# ============================================================
# CONVERSATION MEMORY
# ============================================================

def build_conversation_context(
    memory: List[dict]
) -> str:

    if not memory:
        return "No previous conversation."

    lines = []

    for item in memory[-MAX_MEMORY_TURNS:]:

        user = item.get(
            "user",
            ""
        )

        assistant = item.get(
            "assistant",
            ""
        )

        product = item.get(
            "product",
            ""
        )

        lines.append(
            f"Customer: {user}"
        )

        lines.append(
            f"Assistant: {assistant}"
        )

        if product:
            lines.append(
                f"Product discussed: {product}"
            )

        lines.append("")

    return "\n".join(lines).strip()


def add_memory(
    memory: List[dict],
    question: str,
    answer: str,
    product: Optional[str]
):

    memory.append(
        {
            "user": question,
            "assistant": answer,
            "product": product,
        }
    )

    if len(memory) > MAX_MEMORY_TURNS:
        del memory[
            :-MAX_MEMORY_TURNS
        ]


# ============================================================
# RAG CONTEXT
# ============================================================

def build_rag_context(
    docs
):

    blocks = []
    price_rows = []

    for i, doc in enumerate(
        docs[:MAX_RAG_DOCS],
        1
    ):

        metadata = doc.metadata

        title = metadata.get(
            "title",
            "Unknown product"
        )

        vendor = metadata.get(
            "vendor",
            ""
        )

        price = metadata.get(
            "price",
            ""
        )

        if not price:

            price = (
                "ติดต่อสอบถาม / "
                "Contact for pricing"
            )

        content = doc.page_content[
            :MAX_DOC_CHARS
        ]

        block = (
            f"### PRODUCT {i}\n"
            f"NAME: {title}\n"
            f"VENDOR: {vendor}\n"
            f"PRICE: {price}\n"
            f"{content}"
        )

        blocks.append(
            block
        )

        price_rows.append(
            f"{i}. {title} = {price}"
        )

    return (
        "\n\n".join(blocks),
        "\n".join(price_rows),
    )


# ============================================================
# LLM GENERATION
# ============================================================

def generate_answer(
    question: str,
    context: str,
    price_table: str,
    conversation: str,
) -> str:

    answer = ""

    for attempt in range(
        1,
        MAX_TRIES + 1
    ):

        try:

            answer = chain.invoke(
                {
                    "products": context,
                    "price_table": price_table,
                    "conversation": conversation,
                    "question": question,
                }
            )

        except Exception:
            raise

        answer = str(
            answer
        ).strip()

        if not contains_cjk(
            answer
        ):
            return answer

        print(
            f"[retry {attempt}] "
            f"Unsupported CJK characters detected."
        )

        question = (
            question
            + "\n\n"
            "IMPORTANT: "
            "Answer in the same language as the "
            "customer. "
            "Use Thai and English/Latin characters only. "
            "Do not output Chinese, Japanese, or Korean."
        )

    # Last-resort cleanup
    cleaned = strip_cjk(
        answer
    )

    if cleaned:
        return cleaned

    return (
        "I could not generate a reliable answer "
        "from the available product information."
    )


# ============================================================
# MAIN QUESTION PROCESSOR
# ============================================================

def process_question(
    question: str,
    active_product: Optional[str],
    current_category: Optional[str],
    memory: List[dict],
    debug: bool,
):
    """
    Central question-processing pipeline.

    Returns:
        answer,
        new_active_product,
        new_category,
        answer_type
    """

    # --------------------------------------------------------
    # Resolve product ONCE
    # --------------------------------------------------------

    resolved_product = resolve_product(
        question,
        active_product
    )

    # --------------------------------------------------------
    # Important:
    #
    # If the user explicitly asks for another product,
    # update active product.
    #
    # Generic feature/price follow-ups keep the active product.
    # --------------------------------------------------------

    if resolved_product:

        active_product = resolved_product

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    detected_category = detect_category(
        question
    )

    if detected_category:
        current_category = detected_category

    # --------------------------------------------------------
    # Debug
    # --------------------------------------------------------

    if debug:

        print(
            f"[DEBUG] Previous product: "
            f"{active_product if resolved_product == active_product else 'None'}"
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
            f"{current_category}"
        )

        print(
            f"[DEBUG] Price question: "
            f"{is_price_question(question)}"
        )

        print(
            f"[DEBUG] Feature question: "
            f"{is_feature_question(question)}"
        )

    # ========================================================
    # PRICE QUERY
    # ========================================================

    if is_price_question(
        question
    ):

        response = handle_price_query(
            question,
            active_product,
            current_category,
        )

        if response:

            if debug:
                print(
                    "[DEBUG] Using structured price lookup"
                )

            return (
                response,
                active_product,
                current_category,
                "Data Engine",
            )

    # ========================================================
    # RANKING / RECOMMENDATION
    # ========================================================

    if (
        not active_product
        and is_ranking_query(question)
    ):

        response = handle_ranking_query(
            question,
            current_category,
        )

        if response:

            return (
                response,
                active_product,
                current_category,
                "Data Engine",
            )

    # ========================================================
    # EXACT PRODUCT INFORMATION
    #
    # This is the most important part.
    #
    # If we know exactly which product the user is talking
    # about, DO NOT ask the vector database for similar
    # products.
    #
    # Use the exact CSV row.
    # ========================================================

    if active_product:

        product_context, price_table = (
            build_single_product_context(
                active_product
            )
        )

        if product_context:

            if debug:

                print(
                    "[DEBUG] Using exact product row"
                )

                print(
                    f"[DEBUG] Product: "
                    f"{active_product}"
                )

                print(
                    f"[DEBUG] Context size: "
                    f"{len(product_context)} characters"
                )

            conversation = build_conversation_context(
                memory
            )

            answer = generate_answer(
                question=question,
                context=product_context,
                price_table=price_table,
                conversation=conversation,
            )

            return (
                answer,
                active_product,
                current_category,
                "RAG Engine",
            )

    # ========================================================
    # GENERIC RAG QUERY
    #
    # Only use vector retrieval when we DON'T have an exact
    # product.
    # ========================================================

    effective_query = question

    if debug:

        print(
            f"[DEBUG] Effective query: "
            f"{effective_query}"
        )

    try:

        docs = retriever.invoke(
            effective_query
        )

    except Exception as e:

        raise RuntimeError(
            f"Vector retrieval failed: {e}"
        )

    if debug:

        print(
            f"[DEBUG] Retrieved "
            f"{len(docs)} documents"
        )

        for i, doc in enumerate(
            docs,
            1
        ):

            print(
                f"  {i}. "
                f"{doc.metadata.get('title', 'Unknown')}"
            )

    context, price_table = (
        build_rag_context(
            docs
        )
    )

    if debug:

        print(
            f"[DEBUG] Context size: "
            f"{len(context)} characters"
        )

    conversation = build_conversation_context(
        memory
    )

    answer = generate_answer(
        question=question,
        context=context,
        price_table=price_table,
        conversation=conversation,
    )

    return (
        answer,
        active_product,
        current_category,
        "RAG Engine",
    )


# ============================================================
# PRINT HISTORY
# ============================================================

def print_history(
    memory: List[dict]
):

    print()

    if not memory:

        print(
            "Conversation memory is empty."
        )

        return

    print(
        "=" * 70
    )

    print(
        "Conversation History"
    )

    print(
        "=" * 70
    )

    for i, item in enumerate(
        memory,
        1
    ):

        print(
            f"\n[{i}] Customer:"
        )

        print(
            item["user"]
        )

        print(
            "\nAssistant:"
        )

        print(
            item["assistant"]
        )

        if item.get("product"):

            print(
                f"\nProduct: "
                f"{item['product']}"
            )

        print(
            "-" * 70
        )


# ============================================================
# MAIN LOOP
# ============================================================

if __name__ == "__main__":

    active_product = None
    current_category = None

    memory = []

    debug = False

    print()

    print(
        "=" * 70
    )

    print(
        "Monster Connect AI Sales Assistant"
    )

    print(
        "=" * 70
    )

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

    print(
        "Commands:"
    )

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

    print(
        "=" * 70
    )

    while True:

        try:

            question = input(
                "\nAsk your question (q to quit): "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):

            print(
                "\nGoodbye."
            )

            break

        # ----------------------------------------------------
        # Empty input
        # ----------------------------------------------------

        if not question:
            continue

        # ----------------------------------------------------
        # Quit
        # ----------------------------------------------------

        if question.lower() == "q":

            print(
                "Goodbye."
            )

            break

        # ----------------------------------------------------
        # Debug
        # ----------------------------------------------------

        if question.lower() == "debug":

            debug = not debug

            print(
                f"debug = {debug}"
            )

            continue

        # ----------------------------------------------------
        # Clear
        # ----------------------------------------------------

        if question.lower() == "clear":

            memory.clear()

            active_product = None

            current_category = None

            print(
                "\nConversation memory cleared."
            )

            continue

        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        if question.lower() == "history":

            print_history(
                memory
            )

            continue

        # ====================================================
        # PROCESS QUESTION
        # ====================================================

        previous_product = active_product

        try:

            (
                answer,
                active_product,
                current_category,
                answer_type,
            ) = process_question(
                question=question,
                active_product=active_product,
                current_category=current_category,
                memory=memory,
                debug=debug,
            )

        except Exception as e:

            print(
                "\n[ERROR]"
            )

            print(
                f"{type(e).__name__}: {e}"
            )

            # Restore previous product if something failed
            active_product = previous_product

            continue

        # ====================================================
        # OUTPUT
        # ====================================================

        print(
            f"\nAI Answer ({answer_type}):\n"
        )

        print(
            answer
        )

        # ====================================================
        # MEMORY
        # ====================================================

        add_memory(
            memory=memory,
            question=question,
            answer=answer,
            product=active_product,
        )

        # ====================================================
        # DEBUG INFO
        # ====================================================

        if debug:

            print()

            print(
                f"[DEBUG] Active product after answer: "
                f"{active_product}"
            )

            print(
                f"[DEBUG] Memory entries: "
                f"{len(memory)}"
            )