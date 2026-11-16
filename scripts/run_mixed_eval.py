"""#2 "number + reason" questions: is every number pinned to a table cell, and is the explaining passage retrieved?

    python scripts/run_mixed_eval.py          # final_v1 answers on dev, no API calls

Mixed questions = narrative or reconciliation / comparison questions whose final_v1 answer states dollar amounts or
percentages, i.e. the answer combines figures with an explanation (the mentor's 10/29 "structured value + the text
that describes it"). For each:
  numbers   every $ / % figure in the answer -> rag.cells.find_cells in the cited table chunks, then the same
            filing's tables; "pinned" = the cell's column is the answer's period or its prior-year comparative;
            "not in a table" = computed by the reader or stated only in prose (e.g. "up 18%")
  reason    did retrieval bring the Gold explanation anchors into the top 15 (strict, from
            run_narrative_variants.py: rrf@15 = final_v1, union@15 = the candidate for final_v2)
"""
from __future__ import annotations

import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from demo_answer import numbers_in  # noqa: E402
from rag.cells import find_cells  # noqa: E402

MIXED_TYPES = {"narrative", "reconciliation", "comparison", "event", "relationship"}


def prior(pe: str | None) -> str | None:
    if not pe:
        return None
    y, m, d = (int(x) for x in pe.split("-"))
    return f"{y - 1:04d}-{m:02d}-{min(d, 28) if m == 2 else d:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--run", default="eval/results/round1/reader/final_v1_gpt-6.1-terra_v2_k15_multi")
    ap.add_argument("--variants", default="eval/results/narrative_variants/per_question.csv")
    ap.add_argument("--out", default="eval/results/mixed")
    a = ap.parse_args()

    chunks = [json.loads(l) for l in open(ROOT / a.index / "chunks.jsonl", encoding="utf-8")]
    by_id = {c["chunk_id"]: c for c in chunks}
    tables_by_acc = defaultdict(list)
    for c in chunks:
        if c.get("is_table"):
            tables_by_acc[c.get("accession_number") or c.get("accession")].append(c)
    gold = {json.loads(l)["qid"]: json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")}
    run = ROOT / a.run
    if not (run / "answer_blocks.jsonl").exists():
        run = ROOT / "eval/results/round1/reader/gpt-6.1-terra_v2_k15_multi"
    blocks = {json.loads(l)["qid"]: json.loads(l) for l in open(run / "answer_blocks.jsonl", encoding="utf-8")}
    var = {}
    vp = ROOT / a.variants
    if vp.exists():
        var = {r["qid"]: r for r in csv.DictReader(open(vp, encoding="utf-8"))}

    rows = []
    for qid, b in blocks.items():
        q = gold[qid]
        if q.get("type") not in MIXED_TYPES or not b.get("answered"):
            continue
        nums = numbers_in(b.get("answer_text") or "")
        if not nums:
            continue
        cited = [by_id[c["id"]] for c in b.get("citations") or [] if c["id"] in by_id]
        same = [c for acc in {c.get("accession_number") or c.get("accession") for c in cited} for c in tables_by_acc[acc]]
        pe = b.get("period_end")
        pinned = not_in_table = unmatched_period = 0
        detail = []
        for whole, v, pct in nums:
            k_ = "percent" if pct else "amount"
            best = None
            for when in (pe, prior(pe)):
                hits = find_cells(cited, v, when, kind=k_) or find_cells(same, v, when, kind=k_)
                if hits and hits[0]["period_match"]:
                    best = hits[0]
                    break
                best = best or (hits[0] if hits else None)
            if best and best["period_match"]:
                pinned += 1
                detail.append(f"{whole} -> {' > '.join(best['row_path'])} @ {best['column_header']}")
            elif best:
                unmatched_period += 1
                detail.append(f"{whole} -> ? {' > '.join(best['row_path'])} @ {best['column_header']}")
            else:
                not_in_table += 1
                detail.append(f"{whole} -> (not in a table)")
        v = var.get(qid) or {}
        rows.append({"qid": qid, "type": q["type"], "n_numbers": len(nums), "pinned": pinned,
                     "period_unclear": unmatched_period, "not_in_table": not_in_table,
                     "reason_anchor_rrf@15": v.get("rrf@15", ""), "reason_anchor_union@15": v.get("union@15", ""),
                     "numbers": " ; ".join(detail), "question": q["question"]})

    n_num = sum(r["n_numbers"] for r in rows)
    tab = [r for r in rows if r["n_numbers"] - r["not_in_table"] > 0]
    in_tables = sum(r["n_numbers"] - r["not_in_table"] for r in rows)
    anchored = [r for r in rows if r["reason_anchor_rrf@15"] in ("True", "False")]
    summary = {
        "n_mixed_questions": len(rows), "numbers_stated": n_num,
        "numbers_found_in_tables": in_tables,
        "pinned_to_right_period_cell": f"{sum(r['pinned'] for r in rows)}/{in_tables}",
        "not_in_any_table (computed or prose-only)": sum(r["not_in_table"] for r in rows),
        "questions_all_table_numbers_pinned": f"{sum(r['pinned'] == r['n_numbers'] - r['not_in_table'] for r in tab)}/{len(tab)}",
        "reason_retrieved_final_v1 (rrf@15)": f"{sum(r['reason_anchor_rrf@15'] == 'True' for r in anchored)}/{len(anchored)}",
        "reason_retrieved_union@15": f"{sum(r['reason_anchor_union@15'] == 'True' for r in anchored)}/{len(anchored)}",
    }
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
    for r in rows:
        print(f"- {r['qid']} ({r['type']}): {r['pinned']}/{r['n_numbers'] - r['not_in_table']} pinned, "
              f"{r['not_in_table']} not in a table; reason rrf@15={r['reason_anchor_rrf@15'] or 'n/a'}")


if __name__ == "__main__":
    main()
