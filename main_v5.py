"""
main_v5.py
----------
Same as main_v4 (prices are now correct 8/8) plus a guard against qwen
leaking Chinese into Thai answers.

SYMPTOM in v4: the Safetica answer ended with
"...และการ集思广益，您想要我用中文还是继续用泰文回答呢？"
The model slipped into Chinese mid-sentence and started talking to itself.

CAUSE: qwen2.5 is a Chinese model. In long contexts it drifts back to its
native language. Exactly the same failure enrich_products.py hit, where a
"no CJK" rule plus an automatic retry fixed it completely.

FIXES
1. An explicit language rule in the prompt: Thai and English characters
   only, never Chinese or Japanese.
2. A CJK detector on the OUTPUT. If Chinese characters appear, the answer
   is regenerated (up to 3 attempts) with a stronger reminder.
3. If all three attempts leak, the Chinese fragment is stripped rather
   than shown to the customer.

Run:  python main_v5.py
"""

import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever

MODEL = "qwen2.5:7b"
NUM_CTX = 16384
CHARS_PER_DOC = 900
MAX_TRIES = 3

model = OllamaLLM(model=MODEL, temperature=0.1, num_ctx=NUM_CTX, num_predict=800)

CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def strip_cjk(text):
    """Last resort: drop any sentence containing Chinese/Japanese."""
    parts = re.split(r"(?<=[.!?。])\s+|\n", text)
    kept = [p for p in parts if p.strip() and not CJK.search(p)]
    return "\n".join(kept).strip()


TEMPLATE = """You are a sales consultant for mon.co.th, an IT solutions
company in Thailand. A customer is asking you a question.

## OUR PRODUCT CATALOG
{products}

## PRICE TABLE (the only correct prices)
{price_table}

## LANGUAGE (most important rule)
Write ONLY in Thai script and English/Latin letters. NEVER output Chinese,
Japanese or Korean characters. Characters such as 集思广益, 统合, 安全 are
forbidden. Reply in the same language the customer used: Thai question,
Thai answer. Never ask the customer which language to use. Never write a
note to yourself in the answer.

## HOW TO ANSWER
- Every product above is one mon.co.th sells. If the customer names a
  product that appears above, confirm we have it. Never say a listed
  product is unavailable.
- PRICES: copy the price from the FACT line of that exact numbered
  product, or from the price table above. Never take a price from a
  different product. Never invent or estimate a number. If the price
  reads "ติดต่อสอบถาม / Contact for pricing", say the price is available
  on request.
- Recommend at most 3 products, and only ones that genuinely match what
  the customer asked for. If none of them solve the customer's problem,
  say so plainly and invite them to contact the sales team. Never pad the
  answer with an unrelated product.
- Write natural sentences. Do not print the field labels (FACT, Summary,
  Category, Keywords, Best For) in your answer.
- Only state features, deployment types and certifications written above.
- Keep it under 150 words unless the customer asks for detail.

## CUSTOMER QUESTION
{question}

## YOUR ANSWER"""

prompt = ChatPromptTemplate.from_template(TEMPLATE)
chain = prompt | model

debug = False
print(f"Model: {MODEL}   num_ctx: {NUM_CTX}   (type 'debug' for details)")

while True:
    question = input("\nAsk your question (q to quit): ").strip()

    if question.lower() == "q":
        break
    if question.lower() == "debug":
        debug = not debug
        print(f"debug = {debug}")
        continue
    if not question:
        continue

    docs = retriever.invoke(question)

    blocks, rows = [], []
    for i, d in enumerate(docs, 1):
        m = d.metadata
        title = m.get("title", "?")
        price = m.get("price", "") or "ติดต่อสอบถาม / Contact for pricing"
        vendor = m.get("vendor", "")

        fact = f"FACT | NAME: {title} | VENDOR: {vendor} | PRICE: {price}"
        blocks.append(
            f"### PRODUCT {i}\n{fact}\n{d.page_content[:CHARS_PER_DOC]}"
        )
        rows.append(f"{i}. {title} = {price}")

    context = "\n\n".join(blocks)
    price_table = "\n".join(rows)

    ask = question
    answer = ""
    for attempt in range(1, MAX_TRIES + 1):
        answer = chain.invoke({
            "products": context,
            "price_table": price_table,
            "question": ask,
        })
        if not CJK.search(answer):
            break
        print(f"  [retry {attempt}] Chinese characters detected, regenerating")
        ask = (
            question
            + "\n\nREMINDER: answer in Thai only. No Chinese characters."
        )
    else:
        answer = strip_cjk(answer)
        print("  [warn] model kept leaking Chinese; removed those sentences")

    if debug:
        print(f"\n--- {len(docs)} products, {len(context)} characters ---")
        print(price_table)
        print("---")

    print("\nAI Answer:\n")
    print(answer)

    print("\nProducts I looked at:")
    for row in rows:
        print(f"  {row}")
