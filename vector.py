from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import pandas as pd
import os
import shutil

# ----------------------------- 
# Load CSV
# -----------------------------
df = pd.read_excel("products_cleaned.xlsx")

df = df.fillna("")
df = df.drop(columns=["Unnamed: 7"], errors="ignore")
print(f"CSV rows: {len(df)}")
print(df.columns.tolist())
REBUILD_DB = False
# -----------------------------
# Embedding model
# -----------------------------
embeddings = OllamaEmbeddings(
    model="mxbai-embed-large"
)

# -----------------------------
# Database location
# -----------------------------
db_location = "./chroma_langchain_db"

if REBUILD_DB and os.path.exists(db_location):
    print("Deleting old database...")
    shutil.rmtree(db_location)

# -----------------------------
# Create documents
# -----------------------------

documents = []

for i, row in df.iterrows():
    title = row["Title"].strip()
    description = row["Description"].strip()

    if title == "" or description == "":
        continue
    page_content = f"""
        Product Name: {row['Title']}

        Category: {row['Product Category']}

        Type: {row['Type']}

        Vendor: {row['Vendor']}

        Price: {row['Price']}

        Tags: {row['Tags']}

        Description:
            {description}
        """

    metadata = {
        "vendor": str(row["Vendor"]),
        "category": str(row["Product Category"]),
        "type": str(row["Type"]),
        "price": str(row["Price"])
    }

    documents.append(
        Document(
            page_content=page_content,
            metadata=metadata,
            id=str(i)
        )
    )

print(f"Documents created: {len(documents)}")

# -----------------------------
# Create Chroma DB
# -----------------------------
vector_store = Chroma(
    collection_name="product_database",
    persist_directory=db_location,
    embedding_function=embeddings
)

# Only build if database is empty
if vector_store._collection.count() == 0:

    print("Building vector database...")

    batch_size = 25

    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]

        print(f"Embedding {i+1} - {min(i+batch_size, len(documents))}")

        vector_store.add_documents(batch)

    print("Done!")

else:
    print("Database already exists. Skipping embedding.")

print("Documents in database:",
      vector_store._collection.count())

# -----------------------------
# Retriever
# -----------------------------
retriever = vector_store.as_retriever(
    search_kwargs={"k": 5}
)
