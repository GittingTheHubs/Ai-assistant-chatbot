"""
main_v4.py
----------
Fixes the price mis-attribution found in main_v3.

SYMPTOM in v3: asked for antivirus, the bot quoted Kaspersky at 6,750
(really 1,290), Intercept X at 4,800 (a number that exists nowhere) and
Bitdefender at 1,600 (really ESET's price). Correct products, wrong
prices - the worst kind of error for a sales bot.

CAUSE: each product block was ~1,100 characters with the price buried in
the middle. Across six blocks the model lost track of which price
belonged to which name, like reading the wrong row of a table.

FIXES
1. Every block now opens with a single FACT line holding name, vendor and
   price together, before any prose. Name and price can no longer drift
   apart.
2. A compact price table is repeated at the end of the prompt, right
   before the question, where models attend most reliably.
3. The prompt tells the model to copy prices only from the FACT line of
   the same numbered product, and to say "contact sales" when unsure.
4. Added an instruction not to force a recommendation when nothing in the
   list actually matches (v3 offered Lark Starter, a team chat app, for a
   data-loss-prevention question).

Run:  python main_v4.py
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever

MODEL = "qwen2.5:7b"
NUM_CTX = 16384
CHARS_PER_DOC = 900

model = OllamaLLM(model=MODEL, temperature=0.1, num_ctx=NUM_CTX)

TEMPLATE = """You are a sales consultant for mon.co.th, an IT solutions
company in Thailand. A customer is asking you a question.

## OUR PRODUCT CATALOG
{products}

## PRICE TABLE (the only correct prices)
{price_table}

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
  the customer asked for. If only one fits, recommend one. If none of the
  products above actually solve the customer's problem, say so plainly
  and invite them to contact the sales team. Never pad the answer with an
  unrelated product.
- Reply in the same language as the question. Thai question, Thai answer.
- Write natural sentences. Do not print the field labels (FACT, Summary,
  Category, Keywords, Best For) in your answer.
- Only state features, deployment types and certifications written above.
  Do not fill gaps with outside knowledge.
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

    if debug:
        print(f"\n--- {len(docs)} products, {len(context)} characters ---")
        print(price_table)
        print("---")

    print("\nAI Answer:\n")
    print(chain.invoke({
        "products": context,
        "price_table": price_table,
        "question": question,
    }))

    print("\nProducts I looked at:")
    for row in rows:
        print(f"  {row}")
