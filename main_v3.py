"""
main_v3.py
----------
Fixes the silent context-window overflow in main_v2.py.

SYMPTOM in v2: the model denied the #1 retrieved product every time
("Safetica is not in the list") while happily using products #4-#6.

CAUSE: Ollama defaults num_ctx to ~2048-4096 tokens. main_v2 sent six
products with 1,500-character descriptions each (~9,000 characters, well
over the limit). Ollama silently DROPS the front of the prompt, so
PRODUCT 1 never reached the model. The question sits at the end, so it
always survived - which is why the answers looked coherent but denied
exactly the product that mattered.

THREE FIXES
1. num_ctx set explicitly to 16384 (fine on 16 GB RAM).
2. Each product is trimmed to CHARS_PER_DOC before going in the prompt,
   so the total stays far below the limit no matter what.
3. The prompt no longer stacks NEVER/ONLY rules, which pushed the model
   toward denial as the "safe" answer. It now states plainly that
   everything in the list IS sold by mon.co.th.

Run:  python main_v3.py
Type 'debug' to see the retrieved products and the prompt size.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever

MODEL = "qwen2.5:7b"
NUM_CTX = 16384       # lower to 8192 if the machine runs out of memory
CHARS_PER_DOC = 1100  # per product, inside the prompt only

model = OllamaLLM(model=MODEL, temperature=0.2, num_ctx=NUM_CTX)

TEMPLATE = """You are a sales consultant for mon.co.th, an IT solutions
company in Thailand. A customer is asking you a question.

## OUR PRODUCT CATALOG (these are products mon.co.th SELLS)
{products}

## HOW TO ANSWER
- Every product listed above is one we sell. If the customer asks about a
  product that appears in the list, confirm we have it and describe it.
  Never tell the customer a listed product is unavailable.
- Recommend at most 3 products from the list. Say briefly why each fits.
- Reply in the same language as the question. Thai question, Thai answer.
- Write in natural sentences, like a consultant speaking to a customer.
  Do not copy the field labels (Summary, Category, Keywords, Best For)
  into your answer.
- Quote prices exactly as written. If a price reads
  "ติดต่อสอบถาม / Contact for pricing", say the price is available on request.
  Never estimate or convert a price.
- Only describe features, deployment types and certifications that are
  actually written above. Do not fill gaps with general knowledge.
- If the catalog above genuinely has nothing relevant, say so and invite
  the customer to contact the sales team.
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

    context = "\n\n".join(
        f"### PRODUCT {i}\n{d.page_content[:CHARS_PER_DOC]}"
        for i, d in enumerate(docs, 1)
    )

    if debug:
        print(f"\n--- {len(docs)} products, {len(context)} characters ---")
        for i, d in enumerate(docs, 1):
            print(f"{i}. {d.metadata.get('title', '?')}")
        print("---")

    print("\nAI Answer:\n")
    print(chain.invoke({"products": context, "question": question}))

    print("\nProducts I looked at:")
    for i, d in enumerate(docs, 1):
        print(f"  {i}. {d.metadata.get('title', '?')}  |  {d.metadata.get('price', '')}")
