"""Live demo for the KPMG sync: the same question through retrieve() on the baseline index and on v2.

    python scripts/demo_sync.py                      # default question, hybrid, top 3 per index
    python scripts/demo_sync.py --json               # also print the first v2 result as the full contract JSON
    python scripts/demo_sync.py -q "What drove Microsoft's revenue growth in Q3 FY2026?"

Baseline = data/index_A (Data's paragraph-v1 chunks, the same chunking as the 10/14 Agent index).
v2       = data/index_C1 (table-aware chunking, ~460 tokens; the index handed to Agents on 10/28).
Runs offline: both indexes and the bge-small model are already on disk.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")          # no network calls during the demo
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.retrieve import Retriever  # noqa: E402

QUESTION = "What was Microsoft's total revenue for the three months ended March 31, 2026?"
FILTERS = {"ticker": "MSFT", "fiscal_year": 2026, "fiscal_period": "Q3"}  # what the Agent's parser passes
WIDTH = 100


def show(title: str, resp: dict, n: int, mark: str | None, lines_per_hit: int = 8) -> None:
    print("=" * WIDTH)
    print(f"{title}   index_version={resp['index_version']}   {resp['latency_ms']:.0f} ms")
    print("=" * WIDTH)
    for r in resp["results"][:n]:
        hit = "   <-- contains " + mark if mark and mark in r["text"] else ""
        title = (r["metadata"].get("section_title") or "")[:48]
        print(f"#{r['rank']}  {r['section'] or '-'} | {title}{hit}")
        for l in [l for l in r["text"].splitlines() if l.strip()][:lines_per_hit]:  # keep table rows as rows
            print("    " + l[: WIDTH - 4])
        print("    cite: " + f"{r['company_name']} {r['form']} {r['reporting_period_end']} · {r['accession_number']}")
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question", default=QUESTION)
    ap.add_argument("-n", type=int, default=3, help="results to show per index")
    ap.add_argument("--method", default="hybrid", choices=["hybrid", "bm25", "dense"])
    ap.add_argument("--mark", default="82,886", help="highlight results containing this string ('' to turn off)")
    ap.add_argument("--json", action="store_true", help="print the first v2 result as contract JSON")
    a = ap.parse_args()

    print(f"\nQuestion: {a.question}\nFilters:  {FILTERS}   method={a.method}   top_k=8\n")
    t0 = time.perf_counter()
    base = Retriever(ROOT / "data" / "index_A", log_dir=None)
    v2 = Retriever(ROOT / "data" / "index_C1", log_dir=None)
    print(f"(indexes loaded in {time.perf_counter() - t0:.1f} s)\n")

    show("BEFORE  baseline chunks (as in the 10/14 index)", base.search(a.question, FILTERS, 8, a.method), a.n, a.mark or None)
    resp = v2.search(a.question, FILTERS, 8, a.method)
    show("AFTER   v2 table-aware chunks (index delivered 10/28)", resp, a.n, a.mark or None)

    if a.json and resp["results"]:
        print("=" * WIDTH)
        print("retrieve() result #1 — Retrieval API contract (17 fields)")
        print("=" * WIDTH)
        r = dict(resp["results"][0])
        r["text"] = r["text"][:300] + (" …" if len(r["text"]) > 300 else "")
        print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
