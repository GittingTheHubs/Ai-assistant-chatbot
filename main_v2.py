"""
main_v2.py
----------
Same idea as main.py, but fixes the two things that broke the answers:

1. MODEL: qwen2.5:3b -> qwen2.5:7b
   The 3b model received the correct Safetica document as result #1 and
   still answered "I cannot find information about Safetica". It is too
   small to actually read the context it is given.

2. PROMPT: the old one was 5 lines and said nothing about format, so the
   model copied the raw document fields ("Summary (EN):", "Category:")
   straight into the answer, and invented facts such as Google Workspace
   being on-premise.

Run:  python main_v2.py
Type 'debug' to toggle showing which products were retrieved.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM

from vector_v2 import retriever

MODEL = "qwen2.5:7b"

model = OllamaLLM(model=MODEL, temperature=0.2)

TEMPLATE = """You are a sales consultant for mon.co.th, an IT solutions
company in Thailand. You are talking to a customer.

## THE ONLY PRODUCTS THAT EXIST
{products}

## RULES
1. Recommend ONLY products from the list above. mon.co.th does not sell
   anything else. NEVER mention Cisco, Check Point, Bitdefender, Kaspersky
   or any other brand unless it appears in the list above by name.
2. Answer in the SAME LANGUAGE the customer used. Thai question -> Thai
   answer. English question -> English answer.
3. Write like a human consultant, in flowing sentences. NEVER copy the
   field labels from the list above. The customer must never see the words
   "Summary (EN):", "Category:", "Product Type:", "Keywords:" or
   "Best For:" in your answer.
4. State the price exactly as written in the list. If it says
   "ติดต่อสอบถาม / Contact for pricing", say the price is on request.
   NEVER invent, convert or estimate a price.
5. Do NOT claim a product has a feature, certification or deployment type
   that is not written in the list. If a product is Cloud, do not call it
   on-premise.
6. Recommend at most 3 products. Say briefly why each one fits.
7. If nothing in the list fits, say so honestly and suggest the customer
   contact the sales team. Do not force an unrelated product.
8. Keep the answer under 150 words unless the customer asked for details.

## CUSTOMER QUESTION
{question}

## YOUR ANSWER"""

prompt = ChatPromptTemplate.from_template(TEMPLATE)
chain = prompt | model

debug = False
print(f"Model: {MODEL}   (type 'debug' to toggle retrieved products)")

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

    if debug:
        print("\n--- retrieved ---")
        for i, d in enumerate(docs, 1):
            print(f"{i}. {d.metadata.get('title', '?')}")
        print("-----------------")

    context = "\n\n".join(
        f"### PRODUCT {i}\n{d.page_content}" for i, d in enumerate(docs, 1)
    )

    print("\nAI Answer:\n")
    print(chain.invoke({"products": context, "question": question}))

    print("\nSources:")
    for d in docs[:3]:
        print(f"  - {d.metadata.get('title', '?')}  |  {d.metadata.get('price', '')}")
