"""
diagnose.py
-----------
Tests the vector store WITHOUT the chat model, so we can tell whether
a bad answer is a SEARCH problem or a WRITING problem.

If the right product appears here but main.py still answers wrong,
the retriever is fine and the chat prompt is at fault.
If the right product does NOT appear here, the embedding model cannot
match the query and no prompt change will ever fix it.

Run:  python diagnose.py
"""

import pandas as pd

SRC = "products_enriched.csv"

# ---------------------------------------------------------------
# 1. Encoding + data sanity check (no vector store needed)
# ---------------------------------------------------------------
print("=" * 70)
print("PART 1 — Is the data itself correct?")
print("=" * 70)

df = pd.read_csv(SRC, encoding="utf-8-sig").fillna("")
print(f"rows: {len(df)}   columns: {len(df.columns)}")

# mojibake = Thai written as UTF-8 but read as Latin-1
MOJIBAKE = ["à¸", "à¹", "Ã¡", "â€"]
bad = df[df.apply(
    lambda r: any(m in str(r.to_dict()) for m in MOJIBAKE), axis=1
)]
print(f"rows with corrupted Thai text: {len(bad)}")
if len(bad):
    for t in bad["Title"].head(10):
        print(f"   - {t}")

for name in ["Safetica", "M Cloud", "zcrLog"]:
    hits = df[df["Title"].str.contains(name, case=False, na=False)]
    print(f"\n--- '{name}' in the file: {len(hits)} rows")
    for _, r in hits.head(3).iterrows():
        print(f"    Title    : {r['Title']}")
        print(f"    Category : {r['Category']}")
        print(f"    Type     : {r['Product_Type']}")
        print(f"    Best For : {r['Best_For'] or '(EMPTY)'}")
        print(f"    Price    : {r['Price_Display']}")
        print(f"    Keywords : {str(r['Keywords'])[:120]}")

# ---------------------------------------------------------------
# 2. Retrieval check
# ---------------------------------------------------------------
print()
print("=" * 70)
print("PART 2 — Can the search engine FIND it?")
print("=" * 70)

from vector_v2 import retriever  # noqa: E402

QUERIES = [
    "Safetica คืออะไร",
    "Safetica",
    "M Cloud รุ่น S ราคาเท่าไหร่",
    "M Cloud",
    "โปรแกรมป้องกันข้อมูลรั่วไหล",
    "data loss prevention",
    "มีระบบเก็บ log ตาม พรบ. คอมพิวเตอร์ไหม",
    "zcrLog",
    "แนะนำ antivirus สำหรับออฟฟิศเล็กๆ",
]

for q in QUERIES:
    print(f"\nQUERY: {q}")
    try:
        docs = retriever.invoke(q)
        for i, d in enumerate(docs[:5], 1):
            print(f"   {i}. {d.metadata.get('title', '?')[:60]}")
    except Exception as e:
        print(f"   ERROR: {type(e).__name__}: {e}")

print()
print("=" * 70)
print("HOW TO READ THIS")
print("=" * 70)
print("""
Compare the Thai query with its English/product-name twin:

  'Safetica คืออะไร'  vs  'Safetica'
  'M Cloud รุ่น S...'  vs  'M Cloud'
  'โปรแกรมป้องกัน...'   vs  'data loss prevention'

If the SHORT/English one finds the product but the Thai sentence does
not, the embedding model (mxbai-embed-large) cannot read Thai.
That is fixed by switching the embedding model, not the prompt.
""")
