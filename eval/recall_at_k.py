"""
eval/recall_at_k.py
-------------------
Recall@5 of the production retriever (vector_v2.retriever) on Thai
descriptive queries. A query counts as found when any of the top 5
titles matches its `expected` regex (one relevant group per query,
so this is hit@5).

Run from the repo root (needs Ollama running):
    python eval/recall_at_k.py                                # bge-m3 (default)
    EMBED_MODEL=mxbai-embed-large python eval/recall_at_k.py  # old baseline

Results 2026-11-23 (27 queries): mxbai-embed-large 26%, bge-m3 96%.
"""

import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from vector_v2 import EMBED_MODEL, retriever  # noqa: E402

K = 5

with open("eval/thai_queries.csv", encoding="utf-8") as f:
    cases = list(csv.DictReader(f))

hits = 0
for case in cases:
    titles = [d.metadata["title"] for d in retriever.invoke(case["query"])[:K]]
    found = any(re.search(case["expected"], t, re.I) for t in titles)
    hits += found
    if not found:
        print(f"MISS  {case['query']}\n      got: {' | '.join(titles)}")

print(f"\n{EMBED_MODEL}: Recall@{K} = {hits}/{len(cases)} = {hits / len(cases):.0%}")
