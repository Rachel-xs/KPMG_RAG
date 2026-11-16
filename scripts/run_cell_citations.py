"""#2: can every number RAG answers with be pinned to the exact table cell, in the right period column?

    python scripts/run_cell_citations.py        # final_v1 answers on dev, no API calls

For each exact-numeric Gold question:
  answer cell   the reader's value, looked up in the chunks it cited (then, failing that, in every table chunk of the
                cited filings: "same filing")
  input cells   each Gold fact value (a derived answer such as a growth rate has several), looked up the same way
  correct cell  value matches AND the column's period matches the Gold fact: same end date (±7 days) and the same
                duration (3 / 6 / 9 / 12 months, or a point in time). This is stricter than "the number appears".
Also reports how many table cells in the whole index get a parsed period (coverage of the parser).
"""
from __future__ import annotations

import argparse, csv, json, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.cells import find_cells, parse_table  # noqa: E402
from rag.coverage import CoverageIndex  # noqa: E402


def months_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return 0 if end else None  # instant facts have no start
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return round(((e - s).days + 1) / 30.4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--run", default="eval/results/round1/reader/final_v1_gpt-6.1-terra_v2_k15_multi")
    ap.add_argument("--out", default="eval/results/cells")
    a = ap.parse_args()

    chunks = [json.loads(l) for l in open(ROOT / a.index / "chunks.jsonl", encoding="utf-8")]
    by_id = {c["chunk_id"]: c for c in chunks}
    by_acc = defaultdict(list)
    for c in chunks:
        if c.get("is_table"):
            by_acc[c.get("accession_number") or c.get("accession")].append(c)
    cov = CoverageIndex.from_chunks(ROOT / a.index / "chunks.jsonl")
    fy_ends = {t: e for t, e in cov.fy_end.items() if e}

    gold = {json.loads(l)["qid"]: json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")}
    run = ROOT / a.run
    if not (run / "answer_blocks.jsonl").exists():
        run = ROOT / "eval/results/round1/reader/gpt-6.1-terra_v2_k15_multi"
    blocks = {json.loads(l)["qid"]: json.loads(l) for l in open(run / "answer_blocks.jsonl", encoding="utf-8")}
    pq = {r["qid"]: r for r in csv.DictReader(open(run / "per_question.csv", encoding="utf-8"))}

    rows = []
    for qid, r in pq.items():
        if r["group"] != "number":
            continue
        q, b = gold[qid], blocks[qid]
        facts = q.get("facts") or []
        g_end = facts[0].get("period_end") if facts else None
        g_m = months_between(facts[0].get("period_start"), g_end) if facts else None
        cited = [by_id[c["id"]] for c in b.get("citations") or [] if c["id"] in by_id]
        same_filing = [c for acc in {c.get("accession_number") or c.get("accession") for c in cited} for c in by_acc[acc]]

        def locate(v, end, m):
            hits = find_cells(cited, v, end, m, fy_ends)
            where = "cited"
            if not any(h["period_match"] for h in hits):
                more = find_cells(same_filing, v, end, m, fy_ends)
                if any(h["period_match"] for h in more) or not hits:
                    hits, where = more, "same_filing"
            return hits, (where if hits else "none")

        row = {"qid": qid, "passed": r["passed"] == "True", "answered": b["answered"], "gold_period_end": g_end,
               "gold_months": g_m, "n_cited": len(cited)}
        if b["answered"] and b.get("value") is not None:
            hits, where = locate(float(b["value"]), b.get("period_end") or g_end, g_m)
            top = hits[0] if hits else None
            row.update(answer_found=where, answer_period_match=bool(top and top["period_match"]),
                       answer_cell=top["cell_key"] if top else "", answer_cell_value=top["value_text"] if top else "",
                       answer_n_matches=len(hits),
                       answer_n_period_matches=sum(1 for h in hits if h["period_match"]))
        inputs = []
        for f, (k, v) in zip(facts, (q.get("fact_values") or {}).items()):
            hits, where = locate(float(v), f.get("period_end"), months_between(f.get("period_start"), f.get("period_end")))
            inputs.append(bool(hits and hits[0]["period_match"]))
        row["inputs_total"] = len(inputs)
        row["inputs_cell_ok"] = sum(inputs)
        rows.append(row)

    passed = [r for r in rows if r["passed"] and "answer_found" in r]
    derived = [r for r in passed if r["inputs_total"] > 1 or r["answer_found"] == "none"]
    c_where = Counter(r["answer_found"] for r in passed)
    ok = [r for r in passed if r["answer_period_match"]]
    ambiguous = [r for r in ok if r["answer_n_period_matches"] > 1]
    inputs_ok = sum(r["inputs_cell_ok"] for r in rows if r["passed"])
    inputs_all = sum(r["inputs_total"] for r in rows if r["passed"])

    # parser coverage over the whole index
    n_cells = n_period = n_tables = n_parsed = 0
    for c in chunks:
        if not c.get("is_table"):
            continue
        n_tables += 1
        t = parse_table(c, fy_ends.get(c.get("ticker")))
        if not t:
            continue
        n_parsed += 1
        for cell in t.cells():
            n_cells += 1
            n_period += cell["period_end"] is not None

    summary = {
        "run": str(run.relative_to(ROOT)), "n_number_questions": len(rows), "n_correct_with_value": len(passed),
        "answer_cell_period_match": f"{len(ok)}/{len(passed)}",
        "answer_found_in": dict(c_where),
        "period_matched_but_several_candidate_cells": [r["qid"] for r in ambiguous],
        "no_exact_cell (derived or computed answers)": [r["qid"] for r in passed if not r["answer_period_match"]],
        "gold_input_cells_period_match": f"{inputs_ok}/{inputs_all}",
        "parser": {"table_chunks": n_tables, "parsed": n_parsed, "value_cells": n_cells,
                   "cells_with_period": n_period, "share_with_period": round(n_period / max(n_cells, 1), 3)},
    }
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
