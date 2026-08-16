from langchain_ollama.llms import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from vector_v2 import retriever


model = OllamaLLM(model="qwen2.5:3b")

template = """
You are an AI assistant for an IT solutions company.

Use ONLY the retrieved products below to answer the question.

If the answer cannot be found, say you couldn't find a matching product.

Products:
{products}

Question:
{question}
"""
DEBUG = False

prompt = ChatPromptTemplate.from_template(template)

chain = prompt | model

while True:

    question = input("\nAsk your question (q to quit): ")

    if question.lower() == "q":
        break

    docs = retriever.invoke(question)

    if DEBUG:
        print("\nRetrieved Products:\n")
        for doc in docs:
            print(doc.page_content)
            print("-" * 60)

    context = "\n\n".join(
        [doc.page_content for doc in docs]
    )

    result = chain.invoke({
        "products": context,
        "question": question
    })

    print("\nAI Answer:\n")
    print(result)