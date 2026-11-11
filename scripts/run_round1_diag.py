"""Round 1 follow-ups on Gold Set v2: (A) ranking variants, (B) "weak result" signal validation.

    python scripts/run_round1_diag.py --index data/round1/index_C1

A. Ranking: does the evidence just outside the top 10 come back with a bigger candidate pool, a different
   RRF k, weighted fusion of BM25 and dense, or k = 12 / 15? Same strict scoring as run_round1_eval.py.
B. Weak signal: for every question, which structural checks fire on the default hybrid top 10, broken down by
   hit / miss / unanswerable / Exhibit 21 (graph route). A useful check fires often on misses and unanswerable
   questions and rarely on hits.
     empty            no results (includes "filters matched no chunks")
     methods_disagree BM25 top 10 and dense top 10 share <= T chunk ids (T swept 0..5)
     entity_missing   a ticker / fiscal year / fiscal period in the filters is absent from the results
     multi_target     the filters list several tickers, forms or periods

Writes eval/results/round1/diag_summary.md and diag_per_question.csv.
"""
from __future__ import annotations

import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from rag.retrieve import Retriever  # noqa: E402
import run_round1_eval as E  # noqa: E402

POOL = 50  # max top_k the API allows; per-method lists for weighted fusion


def fuse(bm, dn, w_b, w_d, rrf_k, k):
    s, keep = defaultdict(float), {}
    for w, lst in ((w_b, bm), (w_d, dn)):
        for i, r in enumerate(lst):
            s[r["chunk_id"]] += w / (rrf_k + i + 1)
            keep[r["chunk_id"]] = r
    return [keep[c] for c in sorted(s, key=lambda c: -s[c])[:k]]


def hit_at(q, res, k):
    """strict hit using the first k results (k may be 12 or 15)."""
    old = E.KS
    E.KS = (k,)
    try:
        return E.score(q, res[:k]).get(f"strict@{k}")
    finally:
        E.KS = old


def as_list(v):
    return v if isinstance(v, list) else [v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2.jsonl")
    ap.add_argument("--fixes", default="eval/round1/rag_anchor_fixes.csv")
    ap.add_argument("--out", default="eval/results/round1")
    a = ap.parse_args()
    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    gold, _, _ = E.apply_fixes(gold, ROOT / a.fixes)
    retr = Retriever(ROOT / a.index, log_dir=None)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    # ---------------- A. ranking variants (scored questions only)
    variants = [  # name, rrf_k, candidate_k, (w_bm25, w_dense) or None for the built-in hybrid
        ("baseline hybrid (rrf 60, pool 100)", 60, 100, None),
        ("pool 200", 60, 200, None),
        ("rrf k 20", 20, 100, None),
        ("rrf k 100", 100, 100, None),
        ("fusion bm25 1.5 : dense 1", 60, None, (1.5, 1.0)),
        ("fusion bm25 1 : dense 1.5", 60, None, (1.0, 1.5)),
    ]
    scored = [q for q in gold if E.kind(q) in ("number", "anchored_prose")]
    lists = {}
    for q in gold:
        f = q.get("filters") or None
        bm = retr.search(q["question"], filters=f, top_k=POOL, method="bm25")["results"]
        dn = retr.search(q["question"], filters=f, top_k=POOL, method="dense")["results"]
        lists[q["qid"]] = (bm, dn)
    rowsA, per_q = [], defaultdict(dict)
    for name, rrf_k, pool, w in variants:
        hits = {10: 0, 12: 0, 15: 0}
        for q in scored:
            if w is None:
                retr.rrf_k, retr.candidate_k = rrf_k, pool
                res = retr.search(q["question"], filters=q.get("filters") or None, top_k=15, method="hybrid")["results"]
            else:
                bm, dn = lists[q["qid"]]
                res = fuse(bm, dn, w[0], w[1], rrf_k, 15)
            for k in hits:
                h = bool(hit_at(q, res, k))
                hits[k] += h
                per_q[q["qid"]][f"{name} @{k}"] = h
        rowsA.append((name, {k: v / len(scored) for k, v in hits.items()}, hits))
    retr.rrf_k, retr.candidate_k = 60, 100

    # ---------------- B. weak-signal checks (all questions, default hybrid top 10)
    rowsB = []
    for q in gold:
        f = q.get("filters") or {}
        env = retr.search(q["question"], filters=f or None, top_k=10, method="hybrid")
        res = env["results"]
        bm, dn = lists[q["qid"]]
        overlap = len({r["chunk_id"] for r in bm[:10]} & {r["chunk_id"] for r in dn[:10]})
        tick = {str(t) for t in as_list(f.get("ticker"))} if f.get("ticker") else set()
        ent_missing = bool(res) and (
            (tick and not tick <= {r.get("ticker") for r in res}) or
            (f.get("fiscal_year") and not {int(y) for y in as_list(f["fiscal_year"])} <= {r["metadata"].get("fiscal_year") for r in res}) or
            (f.get("fiscal_period") and not set(as_list(f["fiscal_period"])) <= {r["metadata"].get("fiscal_period") for r in res}))
        multi = any(isinstance(f.get(key), list) and len(f[key]) > 1 for key in ("ticker", "form", "fiscal_period", "fiscal_year"))
        k_ = E.kind(q)
        if k_ in ("number", "anchored_prose"):
            grp = "hit" if E.score(q, res).get("strict@10") else "miss"
        else:
            grp = {"unanswerable": "unanswerable", "graph_route": "exhibit21 (graph route)"}.get(k_, k_)
        rowsB.append({"qid": q["qid"], "group": grp, "n_results": len(res), "empty": not res,
                      "bm25_dense_overlap@10": overlap, "entity_missing": bool(ent_missing), "multi_target": multi,
                      **per_q.get(q["qid"], {})})

    with open(out / "diag_per_question.csv", "w", newline="", encoding="utf-8") as fh:
        cols = list(dict.fromkeys(c for r in rowsB for c in r))
        w_ = csv.DictWriter(fh, fieldnames=cols)
        w_.writeheader()
        w_.writerows(rowsB)

    groups = ["hit", "miss", "unanswerable", "exhibit21 (graph route)", "prose_no_anchor", "ntap_10q_excluded"]
    by = {g: [r for r in rowsB if r["group"] == g] for g in groups}

    def pct(rs, fn):
        return f"{sum(1 for r in rs if fn(r))}/{len(rs)}" if rs else "-"

    md = ["# Round 1 follow-ups: ranking variants and weak-result checks\n",
          f"Index `{a.index}`, Gold Set v2, {len(scored)} scored questions. Strict scoring as in run_round1_eval.py.\n",
          "## A. Ranking variants (strict recall on scored questions)", "",
          "| variant | @10 | @12 | @15 |", "|---|---|---|---|"]
    md += [f"| {n} | {r[10]:.3f} ({h[10]}) | {r[12]:.3f} ({h[12]}) | {r[15]:.3f} ({h[15]}) |" for n, r, h in rowsA]
    md += ["", "## B. Weak-result checks: how often each fires, by group (default hybrid, top 10)", "",
           "| check | " + " | ".join(f"{g} (n={len(by[g])})" for g in groups if by[g]) + " |",
           "|---|" + "---|" * sum(1 for g in groups if by[g])]
    checks = [("empty", lambda r: r["empty"]), ("entity_missing", lambda r: r["entity_missing"]),
              ("multi_target", lambda r: r["multi_target"])]
    checks += [(f"methods_disagree (overlap <= {t})", (lambda t: lambda r: r["bm25_dense_overlap@10"] <= t)(t)) for t in range(0, 6)]
    checks += [("any of empty / entity_missing / multi_target / overlap <= 2",
                lambda r: r["empty"] or r["entity_missing"] or r["multi_target"] or r["bm25_dense_overlap@10"] <= 2)]
    for name, fn in checks:
        md.append(f"| {name} | " + " | ".join(pct(by[g], fn) for g in groups if by[g]) + " |")
    med = {g: sorted(r["bm25_dense_overlap@10"] for r in by[g]) for g in groups if by[g]}
    md += ["", "Median BM25/dense overlap in top 10: " + ", ".join(f"{g} {v[len(v) // 2]}" for g, v in med.items())]
    (out / "diag_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nWrote {out}/diag_summary.md and diag_per_question.csv")


if __name__ == "__main__":
    main()
