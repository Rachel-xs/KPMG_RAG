"""Do the dev numbers measured on the custom index hold on Chroma, the backend the Agent serves from?

    python scripts/backend_parity_final.py          # final_v1 retrieval settings, Gold v2.1 dev, no API calls

Every RAG result reported so far (NAA 0.935 / 0.947, narrative 29/34, ...) was measured on the custom NumPy/BM25
index (data/round1/index_C1), while config.yaml serves `retrieve()` from Chroma (data/round1/chroma_C1). The 11/5 parity
check used Gold v1 at k=8; this one uses the final_v1 settings: hybrid RRF 60, top 15, retrieve_multi for
multi-target filters, Gold v2.1 with anchor fixes, strict scoring from run_round1_eval.py.

Reports, for number and anchored-prose questions: strict hit@10 and @15 on each backend, questions that differ,
mean top-15 id overlap, and whether both indexes were built from the same chunks (count + id set).
Pass: |recall difference| <= 1 question per group and mean overlap >= 0.95.
"""
from __future__ import annotations

import argparse, csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from run_round1_eval import apply_fixes, kind, score  # noqa: E402
from rag.multi import multi_search, split_filters  # noqa: E402
from rag.retrieve import make_retriever  # noqa: E402


def run(retr, q, k):
    f = q.get("filters") or None
    if len(split_filters(f)) > 1:
        return multi_search(lambda qq, ff, kk, trace_id=None: retr.search(qq, filters=ff, top_k=kk, method="hybrid"),
                            q["question"], f, top_k=k)["results"]
    return retr.search(q["question"], filters=f, top_k=k, method="hybrid")["results"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--custom-dir", default="data/round1/index_C1")
    ap.add_argument("--chroma-dir", default="data/round1/chroma_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--fixes", default="eval/round1/rag_anchor_fixes.csv")
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--out", default="eval/results/backend_parity_final")
    a = ap.parse_args()

    cus = make_retriever("custom", ROOT / a.custom_dir, log_dir=None)
    chr_ = make_retriever("chroma", ROOT / a.chroma_dir, log_dir=None)
    ids_c, ids_h = {c["chunk_id"] for c in cus.chunks}, {c["chunk_id"] for c in chr_.chunks}
    same_chunks = ids_c == ids_h
    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    gold, _, _ = apply_fixes(gold, ROOT / a.fixes)
    gold = [q for q in gold if kind(q) in ("number", "anchored_prose")]

    rows = []
    for q in gold:
        rc, rh = run(cus, q, a.k), run(chr_, q, a.k)
        sc, sh = score(q, rc, ks=(10, a.k)), score(q, rh, ks=(10, a.k))
        lc, lh = [r["chunk_id"] for r in rc], [r["chunk_id"] for r in rh]
        rows.append({"qid": q["qid"], "kind": kind(q),
                     "custom@10": bool(sc.get("strict@10")), "chroma@10": bool(sh.get("strict@10")),
                     f"custom@{a.k}": bool(sc.get(f"strict@{a.k}")), f"chroma@{a.k}": bool(sh.get(f"strict@{a.k}")),
                     # retrieve_multi can return more than k results: compare the full lists (Jaccard)
                     "overlap": round(len(set(lc) & set(lh)) / max(1, len(set(lc) | set(lh))), 3),
                     "same_order_top5": lc[:5] == lh[:5]})

    summ = {"same_chunk_ids": same_chunks, "custom_chunks": len(ids_c), "chroma_chunks": len(ids_h), "k": a.k,
            "mean_overlap": round(sum(r["overlap"] for r in rows) / len(rows), 4),
            "identical_top5": f"{sum(r['same_order_top5'] for r in rows)}/{len(rows)}", "groups": {}}
    ok = summ["mean_overlap"] >= 0.95 and same_chunks
    for g in ("number", "anchored_prose"):
        rr = [r for r in rows if r["kind"] == g]
        d = {}
        for kk in (10, a.k):
            c, h = sum(r[f"custom@{kk}"] for r in rr), sum(r[f"chroma@{kk}"] for r in rr)
            d[f"@{kk}"] = {"custom": f"{c}/{len(rr)}", "chroma": f"{h}/{len(rr)}", "diff": h - c,
                           "differ": [r["qid"] for r in rr if r[f"custom@{kk}"] != r[f"chroma@{kk}"]]}
            ok = ok and abs(h - c) <= 1
        summ["groups"][g] = d
    summ["pass"] = ok
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    json.dump(summ, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
