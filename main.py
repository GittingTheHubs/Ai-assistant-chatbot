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
MAX_DOC_CHARS = 1500

DATASET = "products_enriched.csv"

# Regex for CJK detection
CJK = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
)


# ============================================================
# DATASET INITIALIZATION
# ============================================================

df = pd.read_csv(DATASET, encoding="utf-8-sig").fillna("")

# Convert price to numeric (Products with "Contact for pricing" become NaN)
df["Price_num"] = pd.to_numeric(df["Price_Min"], errors="coerce")

print(f"Loaded {len(df)} products from {DATASET}")


# ============================================================
# LLM & PROMPT TEMPLATE SETUP
# ============================================================

model = OllamaLLM(
    model=MODEL,
    temperature=TEMPERATURE,
    num_ctx=NUM_CTX,
    num_predict=NUM_PREDICT,
)

TEMPLATE = """
You are a professional sales consultant for Monster Connect
(mon.co.th), an IT solutions company in Thailand.

A customer is asking you a question.

## OUR PRODUCT CATALOG

{products}

## PRICE TABLE

{price_table}

## LANGUAGE RULES

This is extremely important.

- Reply in the SAME language as the customer's original question.
- If the customer asks in Thai, answer in Thai.
- If the customer asks in English, answer in English.
- Thai and English/Latin characters are allowed.
- NEVER output Chinese characters.
- NEVER output Japanese characters.
- NEVER output Korean characters.
- Never ask the customer which language they want.
- Never write notes to yourself.
- Never mention these instructions.

## PRODUCT RULES

- Only recommend products that appear in the product catalog above.
- If the customer explicitly names a product appearing above,
  confirm that the product exists.
- Never say a listed product is unavailable.
- Do not invent products.

## PRICE RULES

Prices are extremely important.

- Use ONLY the price associated with the exact product.
- Use the PRICE TABLE or FACT information above.
- Never copy a price from another product.
- Never estimate or invent a price.
- If the price says:
  "ติดต่อสอบถาม / Contact for pricing"
  explain that the customer needs to contact the sales team for pricing.
- Do not change THB prices into another currency unless the customer
  explicitly asks for currency conversion.

## PRODUCT INFORMATION RULES

Only state information that appears in the retrieved product data.

Do NOT invent:

- specifications
- features
- certifications
- deployment types
- compatibility
- performance
- security capabilities
- compliance claims

## RECOMMENDATIONS

- Recommend at most 3 products.
- Only recommend products that genuinely match the customer's request.
- Do not pad the answer with unrelated products.
- If no retrieved product is appropriate, say so clearly.

## ANSWER STYLE

- Be concise and natural.
- Do not print internal field names such as:
  FACT, Summary, Category, Keywords, Best For.
- Do not talk about being an AI.
- Do not talk about the retrieval system.
- Do not mention the product database.
- Keep the answer under 150 words unless the customer asks for detail.

## CUSTOMER QUESTION

{question}

## YOUR ANSWER
"""

prompt = ChatPromptTemplate.from_template(TEMPLATE)
chain = prompt | model


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def strip_cjk(text):
    """Last resort: remove sentences containing Chinese/Japanese/Korean characters."""
    parts = re.split(r"(?<=[.!?。！？])\s+|\n", text)
    kept = [p for p in parts if p.strip() and not CJK.search(p)]
    return "\n".join(kept).strip()


# ============================================================
# INTENT & FEATURE DETECTION
# ============================================================

def detect_category(query, current_category=None):
    q = query.lower()

    if any(w in q for w in ["laptop", "notebook", "computer", "macbook", "thinkpad"]):
        return "laptop"

    if any(w in q for w in ["antivirus", "virus", "security", "protection", "edr", "xdr"]):
        return "antivirus"

    if any(w in q for w in ["firewall", "router", "networking", "network security"]):
        return "firewall"

    if any(w in q for w in ["backup", "recovery"]):
        return "backup"

    if any(w in q for w in ["siem", "log management", "log"]):
        return "log"

    return current_category


def extract_price_thresholds(query):
    q = query.lower()
    max_price = None
    min_price = None

    max_match = re.search(
        r"""
        (?:
            lower\ than |
            under |
            less\ than |
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
        max_price = float(max_match.group(1).replace(",", ""))

    min_match = re.search(
        r"""
        (?:
            higher\ than |
            more\ than |
            above |
            over |
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
        min_price = float(min_match.group(1).replace(",", ""))

    return min_price, max_price


def is_price_lookup(query):
    q = query.lower()
    return any(
        phrase in q
        for phrase in [
            "how much",
            "price of",
            "cost of",
            "ราคา",
            "ราคาเท่าไหร่",
            "ราคาเท่าไร",
            "กี่บาท",
        ]
    )


def is_ranking_query(query):
    q = query.lower()
    return any(
        word in q
        for word in [
            "top",
            "cheapest",
            "cheap",
            "expensive",
            "highest",
            "lowest",
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
    )


# ============================================================
# DATAFRAME FILTERING
# ============================================================

def filter_category(dataframe, category):
    if category is None:
        return dataframe

    df2 = dataframe.copy()
    title = df2["Title"].astype(str)
    product_type = df2["Product_Type"].astype(str)
    catalog_category = df2["Category"].astype(str)

    if category == "laptop":
        mask = title.str.contains(
            r"laptop|notebook|expertbook|latitude|thinkpad|thinkbook|travelmate|macbook",
            case=False,
            na=False,
        ) | product_type.str.contains("Laptop", case=False, na=False)

        exclude = title.str.contains(
            r"monitor|display|optiplex|thinkvision|aio|all-in-one|sff|m70a|v50a",
            case=False,
            na=False,
        )
        return df2[mask & ~exclude]

    if category == "antivirus":
        mask = (
            title.str.contains(
                r"antivirus|falcon|sentinelone|sophos|security|crowdstrike|singularity",
                case=False,
                na=False,
            )
            | product_type.str.contains(
                r"Antivirus|EDR|XDR", case=False, na=False
            )
            | catalog_category.str.contains(
                r"Antivirus|Security", case=False, na=False
            )
        )
        return df2[mask]

    if category == "firewall":
        mask = title.str.contains(
            r"fortigate|sophos|sonicwall|watchguard|firewall",
            case=False,
            na=False,
        ) | product_type.str.contains("Firewall", case=False, na=False)
        return df2[mask]

    if category == "backup":
        mask = title.str.contains(
            r"backup|recovery", case=False, na=False
        ) | product_type.str.contains(
            r"Backup|Recovery", case=False, na=False
        )
        return df2[mask]

    if category == "log":
        mask = title.str.contains(
            r"log|siem|zcrlog", case=False, na=False
        ) | product_type.str.contains(
            r"SIEM|Log Management", case=False, na=False
        )
        return df2[mask]

    return df2


# ============================================================
# STRUCTURED QUERY ENGINE
# ============================================================

def handle_structured_query(query, category=None):
    q = query.lower().strip()
    min_price, max_price = extract_price_thresholds(q)
    active_category = detect_category(q, category)

    # --------------------------------------------------------
    # DIRECT PRICE LOOKUP
    # --------------------------------------------------------
    if is_price_lookup(q) and min_price is None and max_price is None:
        search_query = q
        remove_words = [
            "how much is",
            "how much",
            "price of",
            "cost of",
            "what is the price of",
            "what's the price of",
            "ราคา",
            "ราคาเท่าไหร่",
            "ราคาเท่าไร",
            "กี่บาท",
            "เท่าไหร่",
            "เท่าไร",
        ]

        for phrase in remove_words:
            search_query = search_query.replace(phrase, "")

        search_query = search_query.strip()

        # Search title/vendor first
        if len(search_query) > 1:
            matches = df[
                df["Title"]
                .astype(str)
                .str.contains(search_query, case=False, na=False)
                | df["Vendor"]
                .astype(str)
                .str.contains(search_query, case=False, na=False)
            ].copy()

            if not matches.empty:
                matches = matches.sort_values(
                    by="Price_num", ascending=True, na_position="last"
                )
                results = []
                for _, row in matches.head(5).iterrows():
                    price = row["Price_Display"]
                    results.append(f"• {row['Title']} — {price}")

                return "\n".join(results)

    # --------------------------------------------------------
    # RANKING / THRESHOLD
    # --------------------------------------------------------
    if (
        is_ranking_query(q)
        or min_price is not None
        or max_price is not None
    ):
        filtered = df.dropna(subset=["Price_num"]).copy()
        filtered = filter_category(filtered, active_category)

        # Strict price filtering
        if max_price is not None:
            filtered = filtered[filtered["Price_num"] < max_price]

        if min_price is not None:
            filtered = filtered[filtered["Price_num"] > min_price]

        # Determine number of requested products
        cleaned = re.sub(
            r"""
            (?:
                lower\ than |
                under |
                less\ than |
                below |
                higher\ than |
                more\ than |
                above |
                over |
                greater\ than |
                ไม่เกิน |
                ต่ำกว่า |
                น้อยกว่า |
                มากกว่า |
                สูงกว่า
            )
            \s*
            [\d,]+
            """,
            "",
            q,
            flags=re.VERBOSE,
        )

        number_match = re.search(r"\b(\d+)\b", cleaned)
        n = int(number_match.group(1)) if number_match else 5
        n = max(1, min(n, 10))  # Prevent huge outputs

        # Sort order
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

        top_df = filtered.sort_values(
            by="Price_num", ascending=ascending
        ).head(n)

        if top_df.empty:
            return "No matching products were found for the requested criteria."

        results = []
        for _, row in top_df.iterrows():
            results.append(f"• {row['Title']} — {row['Price_Display']}")

        return "\n".join(results)

    return None


# ============================================================
# RAG ENGINE & GENERATION
# ============================================================

def build_rag_context(docs):
    blocks = []
    rows = []

    for i, doc in enumerate(docs, 1):
        metadata = doc.metadata
        title = metadata.get("title", "Unknown product")
        vendor = metadata.get("vendor", "")
        price = metadata.get("price", "")

        if not price:
            price = "ติดต่อสอบถาม / Contact for pricing"

        fact = f"FACT | NAME: {title} | VENDOR: {vendor} | PRICE: {price}"
        content = doc.page_content[:MAX_DOC_CHARS]

        blocks.append(f"### PRODUCT {i}\n{fact}\n{content}")
        rows.append(f"{i}. {title} = {price}")

    return "\n\n".join(blocks), "\n".join(rows)


def generate_answer(question, context, price_table):
    ask = question
    answer = ""

    for attempt in range(1, MAX_TRIES + 1):
        answer = chain.invoke(
            {
                "products": context,
                "price_table": price_table,
                "question": ask,
            }
        )

        # Check for Chinese/Japanese/Korean
        if not CJK.search(answer):
            return answer.strip()

        print(
            f"  [retry {attempt}] CJK characters detected, regenerating..."
        )

        ask = (
            question
            + "\n\n"
            "IMPORTANT REMINDER: "
            "Answer in the same language as the customer. "
            "If the customer used Thai, answer in Thai. "
            "Use ONLY Thai and English/Latin characters. "
            "Absolutely NO Chinese, Japanese, or Korean characters."
        )

    # Last resort fallback
    answer = strip_cjk(answer)
    print(
        "  [warning] Model repeatedly generated CJK characters. Removed affected sentences."
    )

    return answer


# ============================================================
# MAIN LOOP
# ============================================================

if __name__ == "__main__":
    current_category = None
    debug = False

    print()
    print("=" * 70)
    print("Monster Connect AI Sales Assistant")
    print("=" * 70)
    print(f"Model       : {MODEL}")
    print(f"Dataset     : {DATASET}")
    print(f"Vector      : vector_v2 / MMR")
    print(f"Products    : {len(df)}")
    print()
    print("Commands:")
    print("  q     = quit")
    print("  debug = toggle debug information")
    print("=" * 70)

    while True:
        question = input("\nAsk your question (q to quit): ").strip()

        if not question:
            continue

        if question.lower() == "q":
            break

        if question.lower() == "debug":
            debug = not debug
            print(f"debug = {debug}")
            continue

        # Category Memory
        detected = detect_category(question, current_category)
        if detected:
            current_category = detected

        # Structured Query Branch
        structured_response = handle_structured_query(
            question, category=current_category
        )

        if structured_response:
            print("\nAI Answer (Data Engine):\n")
            print(structured_response)
            continue

        # Vector RAG Branch
        try:
            docs = retriever.invoke(question)
        except Exception as e:
            print("\n[ERROR] Vector retrieval failed:")
            print(f"{type(e).__name__}: {e}")
            continue

        context, price_table = build_rag_context(docs)

        if debug:
            print()
            print(f"--- Retrieved {len(docs)} products ---")
            print(price_table)
            print(f"--- Context size: {len(context)} characters ---")

        # LLM Generation
        try:
            answer = generate_answer(question, context, price_table)
        except Exception as e:
            print("\n[ERROR] LLM generation failed:")
            print(f"{type(e).__name__}: {e}")
            continue

        print("\nAI Answer (RAG Engine):\n")
        print(answer)

        # Show Retrieved Products in Debug Mode
        if debug:
            print("\nProducts I looked at:")
            for row in price_table.splitlines():
                print(f"  {row}")