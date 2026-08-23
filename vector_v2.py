import os
import shutil

import pandas as pd
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings


SRC = "products_enriched.csv"
DB_LOCATION = "./chroma_v2_db"

# IMPORTANT:
# Set True ONCE if you want to rebuild the database after changing
# products_enriched.csv or changing the embedding/content structure.
REBUILD_DB = False

DESC_CHARS = 1500


# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(SRC, encoding="utf-8-sig").fillna("")

print(f"Loaded {len(df)} products, {len(df.columns)} columns")


# ============================================================
# EMBEDDING MODEL
# ============================================================

embeddings = OllamaEmbeddings(
    model="mxbai-embed-large"
)


# ============================================================
# REBUILD VECTOR DATABASE
# ============================================================

if REBUILD_DB and os.path.exists(DB_LOCATION):
    print("Deleting old database...")
    shutil.rmtree(DB_LOCATION)


# ============================================================
# BUILD SEARCH CONTENT
# ============================================================

def build_content(row):
    """
    Put important semantic information first.
    Keep the large description at the end and truncate it.
    """

    parts = [
        f"Product: {row['Title']}"
    ]

    def add(label, key):
        val = str(row.get(key, "")).strip()

        if val:
            parts.append(
                f"{label}: {val}"
            )

    # Important semantic information first
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

    # Pricing tiers
    variants = str(
        row.get("Variants", "")
    ).strip()

    if variants:
        parts.append(
            f"Pricing Tiers: {variants[:800]}"
        )

    # Description LAST
    desc = str(
        row.get("Description", "")
    ).strip()

    if desc:
        parts.append(
            f"Details: {desc[:DESC_CHARS]}"
        )

    return "\n".join(parts)


# ============================================================
# CREATE DOCUMENTS
# ============================================================

documents = []

for i, row in df.iterrows():

    title = str(
        row.get("Title", "")
    ).strip()

    if not title:
        continue

    documents.append(
        Document(
            page_content=build_content(row),

            metadata={
                "title": title,

                "vendor": str(
                    row.get("Vendor", "")
                ),

                "category": str(
                    row.get("Category", "")
                ),

                "product_type": str(
                    row.get("Product_Type", "")
                ),

                "best_for": str(
                    row.get("Best_For", "")
                ),

                "deployment": str(
                    row.get("Deployment", "")
                ),

                "price": str(
                    row.get("Price_Display", "")
                ),

                "url": str(
                    row.get("URL", "")
                ),
            },

            id=str(i),
        )
    )


print(
    f"Documents created: {len(documents)}"
)


# ============================================================
# CHROMA VECTOR STORE
# ============================================================

vector_store = Chroma(
    collection_name="product_database_v2",
    persist_directory=DB_LOCATION,
    embedding_function=embeddings,
)


# ============================================================
# BUILD DATABASE IF EMPTY
# ============================================================

if vector_store._collection.count() == 0:

    print("Building vector database...")

    batch_size = 25

    for i in range(
        0,
        len(documents),
        batch_size
    ):

        batch = documents[
            i:i + batch_size
        ]

        print(
            f"  Embedding {i + 1} - "
            f"{min(i + batch_size, len(documents))}"
        )

        vector_store.add_documents(
            batch
        )

    print("Done!")

else:

    print(
        "Database already exists. "
        "Skipping embedding."
    )


print(
    "Documents in database:",
    vector_store._collection.count()
)


# ============================================================
# MMR RETRIEVER
# ============================================================

retriever = vector_store.as_retriever(
    search_type="mmr",

    search_kwargs={
        "k": 6,
        "fetch_k": 25,
        "lambda_mult": 0.6,
    },
)