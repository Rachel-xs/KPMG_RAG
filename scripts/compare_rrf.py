"""Check an RRF k change on a second question set before making it the default.

    python scripts/compare_rrf.py --index data/round1/index_C1 --gold eval/gold_v1.jsonl --include-drafts

Hybrid, question filters, evidence recall@5/8/10 and MRR (rag.evaluate scoring), for each rrf_k, plus which
questions each setting gains or loses against the first one.
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.evaluate import load_gold, score_question  # noqa: E402
from rag.retrieve import Retriever  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--index", default="data/round1/index_C1")
ap.add_argument("--gold", default="eval/gold_v1.jsonl")
ap.add_argument("--include-drafts", action="store_true")
ap.add_argument("--rrf", default="60,20")
a = ap.parse_args()
gold = load_gold(ROOT / a.gold, a.include_drafts)
r = Retriever(ROOT / a.index, log_dir=None)
ks, per = (5, 8, 10), {}
print(f"{len(gold)} questions from {a.gold}, hybrid, filtered\n")
print("| rrf_k | recall@5 | recall@8 | recall@10 | MRR |\n|---|---|---|---|---|")
for k_ in [int(x) for x in a.rrf.split(",")]:
    r.rrf_k = k_
    rows = {q["qid"]: score_question(q, r.search(q["question"], filters=q.get("filters"), top_k=10, method="hybrid")["results"], ks)
            for q in gold}
    per[k_] = rows
    m = lambda key: sum(v[key] for v in rows.values()) / len(rows)
    print(f"| {k_} | {m('evidence_recall@5'):.3f} | {m('evidence_recall@8'):.3f} | {m('evidence_recall@10'):.3f} | {m('mrr'):.3f} |")
base = list(per)[0]
for k_ in list(per)[1:]:
    up = [q for q in per[k_] if per[k_][q]["evidence_recall@10"] > per[base][q]["evidence_recall@10"]]
    dn = [q for q in per[k_] if per[k_][q]["evidence_recall@10"] < per[base][q]["evidence_recall@10"]]
    print(f"\nrrf_k {k_} vs {base} at @10: better on {len(up)} {up}, worse on {len(dn)} {dn}")
