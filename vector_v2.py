"""
vector_v2.py
------------
Drop-in replacement for vector.py that actually USES the enriched columns.
Left as a separate file so the original vector.py keeps working.

To switch over, change one line in main.py:
    from vector import retriever      ->  from vector_v2 import retriever

Three changes that matter:

1. Embeds Title + Summary + Keywords + Features FIRST, description last.
   The old version embedded a 28,000-character description, which drowns
   the signal -- the meaningful words get averaged into noise.

2. Keywords are bilingual, so a Thai question can match an English product.

3. Uses MMR search so 5 results aren't 5 tiers of the same product.
   The old version returned zcrLog Cloud 1/2/3/ICT1/ICT2 for every
   log-related question.
"""

import os
import shutil

import pandas as pd
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

SRC = "products_enriched.csv"
DB_LOCATION = "./chroma_v2_db"
REBUILD_DB = False
DESC_CHARS = 1500  # cap description so it can't drown the summary

df = pd.read_csv(SRC).fillna("")
print(f"Loaded {len(df)} products, {len(df.columns)} columns")

embeddings = OllamaEmbeddings(model="mxbai-embed-large")

if REBUILD_DB and os.path.exists(DB_LOCATION):
    print("Deleting old database...")
    shutil.rmtree(DB_LOCATION)


def build_content(row):
    """Signal first, bulk text last."""
    parts = [f"Product: {row['Title']}"]

    def add(label, key):
        val = str(row.get(key, "")).strip()
        if val:
            parts.append(f"{label}: {val}")

    add("Summary", "Summary_TH")
    add("Summary (EN)", "Summary_EN")
    add("Category", "Category")
    add("Product Type", "Product_Type")
    add("Best For", "Best_For")
    add("Organization Size", "Org_Size")
    add("Deployment", "Deployment")
    add("Key Features", "Features")
    add("Keywords", "Keywords")
    add("Vendor", "Vendor")
    add("Price", "Price_Display")

    variants = str(row.get("Variants", "")).strip()
    if variants:
        parts.append(f"Pricing Tiers: {variants[:800]}")

    desc = str(row.get("Description", "")).strip()
    if desc:
        parts.append(f"Details: {desc[:DESC_CHARS]}")

    return "\n".join(parts)


documents = []
for i, row in df.iterrows():
    if not str(row["Title"]).strip():
        continue
    documents.append(
        Document(
            page_content=build_content(row),
            metadata={
                "title": str(row["Title"]),
                "vendor": str(row.get("Vendor", "")),
                "category": str(row.get("Category", "")),
                "product_type": str(row.get("Product_Type", "")),
                "best_for": str(row.get("Best_For", "")),
                "deployment": str(row.get("Deployment", "")),
                "price": str(row.get("Price_Display", "")),
                "url": str(row.get("URL", "")),
            },
            id=str(i),
        )
    )

print(f"Documents created: {len(documents)}")

vector_store = Chroma(
    collection_name="product_database_v2",
    persist_directory=DB_LOCATION,
    embedding_function=embeddings,
)

if vector_store._collection.count() == 0:
    print("Building vector database...")
    batch_size = 25
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        print(f"  Embedding {i + 1} - {min(i + batch_size, len(documents))}")
        vector_store.add_documents(batch)
    print("Done!")
else:
    print("Database already exists. Skipping embedding.")

print("Documents in database:", vector_store._collection.count())

# MMR = relevance + diversity, so you don't get 5 tiers of the same product
retriever = vector_store.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 6, "fetch_k": 25, "lambda_mult": 0.6},
)
