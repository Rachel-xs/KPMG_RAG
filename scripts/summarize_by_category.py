"""Break a run_chunking_exp per_question.csv down by Gold v1 category (and source: RAG v0 vs Eval new).

    python scripts/summarize_by_category.py eval/results/<run>/per_question.csv --gold eval/gold_v1.jsonl --k 8
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("per_question")
    ap.add_argument("--gold", default="eval/gold_v1.jsonl")
    ap.add_argument("--k", type=int, default=8)
    a = ap.parse_args()
    gold = {json.loads(l)["qid"]: json.loads(l) for l in open(a.gold) if l.strip()}
    rows = list(csv.DictReader(open(a.per_question)))
    ck, pk = f"evidence_recall@{a.k}", f"parent_recall@{a.k}"
    groups = collections.defaultdict(list)
    for r in rows:
        g = gold.get(r["qid"], {})
        for key in (g.get("category", "?"), f"source={g.get('source', '?')}", "ALL"):
            groups[(r["variant"], r["method"], key)].append(r)
    print(f"| variant | method | group | n | child recall@{a.k} | parent recall@{a.k} | MRR |")
    print("|---|---|---|---|---|---|---|")
    for (v, m, key), rs in sorted(groups.items()):
        mean = lambda c: round(statistics.mean(float(x[c]) for x in rs), 3) if c in rs[0] else "-"
        print(f"| {v} | {m} | {key} | {len(rs)} | {mean(ck)} | {mean(pk)} | {mean('mrr')} |")


if __name__ == "__main__":
    main()
