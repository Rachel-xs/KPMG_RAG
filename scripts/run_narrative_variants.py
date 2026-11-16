"""Compare narrative retrieval variants on the DEV set (Gold Set v2.1, 155 questions). No API calls.

    python scripts/run_narrative_variants.py                    # rrf / union / neighbors / union+neighbors at k=10 and 15
    python scripts/run_narrative_variants.py --ks 10 --each 4   # union: 4 from each method instead of top_k // 2

Scores with the same rule as scripts/run_round1_eval.py (strict: every anchor / input figure in the top k, from the
gold filing), on two groups:
  anchored prose (34)   the target: does the variant recover the 9 narrative misses?
  numbers (93)          the guard: a variant is only worth adopting if numbers do not get worse
Also reports the reader's context size (sum of chunk tokens) so a gain is not just "more text".

Adoption rule (week10-12 action plan): narrative strict improves by >= 1 question (~3 points) at the same k and
numbers do not drop; otherwise keep rrf. Decide on dev only: the holdout batch B tests the choice once, as final_v2.
"""
from __future__ import annotations

import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from run_round1_eval import apply_fixes, kind, score  # noqa: E402
from rag.narrative import VARIANTS, NarrativeSearch  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--fixes", default="eval/round1/rag_anchor_fixes.csv")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--ks", default="10,15")
    ap.add_argument("--each", type=int, default=None, help="union: results taken from each method (default top_k // 2)")
    ap.add_argument("--n-seed", type=int, default=3, help="neighbors: how many top results bring their neighbours")
    ap.add_argument("--out", default="eval/results/narrative_variants")
    a = ap.parse_args()

    from rag.retrieve import Retriever
    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    gold, _, _ = apply_fixes(gold, ROOT / a.fixes)
    gold = [q for q in gold if kind(q) in ("anchored_prose", "number")]
    retr = Retriever(ROOT / a.index, log_dir=None)
    ns = NarrativeSearch(retr, each=a.each, n_seed=a.n_seed)
    ks = [int(k) for k in a.ks.split(",")]
    variants = [v for v in a.variants.split(",") if v]

    rows = []
    for q in gold:
        row = {"qid": q["qid"], "kind": kind(q), "type": q["type"], "question": q["question"]}
        for k in ks:
            for v in variants:
                env = ns.search(q["question"], q.get("filters") or None, top_k=k, variant=v)
                res = env["results"]
                row[f"{v}@{k}"] = bool(score(q, res, ks=(k,)).get(f"strict@{k}"))
                row[f"{v}@{k}_tokens"] = sum((r.get("metadata") or {}).get("n_tokens") or 0 for r in res)
        rows.append(row)

    by = defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    md = [f"# Narrative retrieval variants (dev: {a.gold}, strict)\n",
          f"anchored prose n={len(by['anchored_prose'])}, numbers n={len(by['number'])}; "
          f"union each={a.each or 'top_k // 2'}, neighbors n_seed={a.n_seed}\n",
          "| k | variant | prose strict | Δ vs rrf | numbers strict | Δ vs rrf | context tokens / q | prose recovered | prose lost |",
          "|---|---|---|---|---|---|---|---|---|"]
    summary = {}
    for k in ks:
        base_p = {r["qid"] for r in by["anchored_prose"] if r[f"rrf@{k}"]} if "rrf" in variants else set()
        base_n = sum(r[f"rrf@{k}"] for r in by["number"]) if "rrf" in variants else None
        for v in variants:
            p = [r for r in by["anchored_prose"] if r[f"{v}@{k}"]]
            n = sum(r[f"{v}@{k}"] for r in by["number"])
            tok = sum(r[f"{v}@{k}_tokens"] for r in rows) / len(rows)
            rec = sorted({r["qid"] for r in p} - base_p)
            lost = sorted(base_p - {r["qid"] for r in p})
            summary[f"{v}@{k}"] = {"prose": len(p), "numbers": n, "tokens": round(tok), "recovered": rec, "lost": lost}
            md.append(f"| {k} | {v} | {len(p)}/{len(by['anchored_prose'])} | {len(p) - len(base_p):+d} | "
                      f"{n}/{len(by['number'])} | {'' if base_n is None else f'{n - base_n:+d}'} | {tok:,.0f} | "
                      f"{', '.join(rec) or '-'} | {', '.join(lost) or '-'} |")
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("\n".join(md))
    print(f"\nWrote {out}/summary.md, summary.json, per_question.csv")


if __name__ == "__main__":
    main()
