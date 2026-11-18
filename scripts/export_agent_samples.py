"""Real sample outputs for the Agent team, from the frozen index, through the public functions they call.

    RAG_BACKEND=chroma RAG_CHROMA_DIR="$PWD/data/round1/chroma_C1" python scripts/export_agent_samples.py

Writes eval/results/agent_samples/ (local only, DM it: it holds filing text):
  01_ok.json, 02_weak.json, 03_empty.json   retrieve_with_status() for each evidence_status
  04_retrieve_multi.json                     retrieve_multi() over two companies (subqueries + merged results)
  05_coverage.json                           check_coverage() / precheck_question() for all five statuses
  06_cell_citations.json                     rag.cells for the 01_ok answer value -> exact table cell
  README.md                                  what each file shows
Chunk text is cut to --max-text characters; every metadata field is kept as returned.
"""
from __future__ import annotations

import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = ("What was Microsoft's total revenue for the three months ended March 31, 2026?",
      {"ticker": "MSFT", "form": "10-Q", "fiscal_year": 2026, "fiscal_period": "Q3"})
WEAK = ("Compare Microsoft's and Apple's total net sales or revenue for the quarter ended March 2026.",
        {"ticker": ["MSFT", "AAPL"], "form": "10-Q"})          # one search over two targets -> multi_target
EMPTY = ("What was Microsoft's total revenue for fiscal year 2025?",
         {"ticker": "MSFT", "form": "10-K", "fiscal_year": 2025})  # not in the frozen corpus -> filter_no_match
COVERAGE = [
    ("all_hit", {"tickers": ["MSFT"], "forms": ["10-Q"], "fiscal_years": [2026], "fiscal_periods": ["Q3"]}),
    ("partial", {"tickers": ["MSFT", "NTAP"], "forms": ["10-Q"]}),
    ("none", {"companies": ["Microsoft"], "period_ends": ["2026-09-30"]}),
    ("unresolved", {"companies": ["Tesla"]}),
    ("no_target", {"fiscal_years": [2026]}),
]
PRECHECK = ["What was Mcirosoft's revenue for the three months ended March 31, 2026, per its 10-Q?",
            "What was Microsoft's revenue for the quarter ended September 30, 2026?"]


def cut(env: dict, n: int) -> dict:
    out = json.loads(json.dumps(env, default=str))
    for r in out.get("results", []):
        if isinstance(r.get("text"), str) and len(r["text"]) > n:
            r["text"] = r["text"][:n] + f" …[{len(r['text']) - n} more characters]"
        md = r.get("metadata") or {}
        if isinstance(md.get("parent_text"), str) and len(md["parent_text"]) > n:
            md["parent_text"] = md["parent_text"][:n] + " …"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/results/agent_samples")
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--max-text", type=int, default=400)
    a = ap.parse_args()
    from rag.retrieve import _default_retriever, retrieve_multi, retrieve_with_status
    from rag.coverage import check_coverage, precheck_question
    from rag.cells import find_cells

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    retr = _default_retriever()
    backend = type(retr).__name__
    head = {"backend": backend, "top_k": a.top_k, "index_version": None}
    saved = {}

    for name, (q, f) in (("01_ok", OK), ("02_weak", WEAK), ("03_empty", EMPTY)):
        env = retrieve_with_status(q, f, a.top_k, trace_id=f"sample-{name}")
        if env["results"]:
            head["index_version"] = env["results"][0].get("index_version")
        (out / f"{name}.json").write_text(json.dumps({**head, "call": "retrieve_with_status", "query": q, "filters": f,
                                                      **cut(env, a.max_text)}, indent=1, ensure_ascii=False))
        saved[name] = env["evidence_status"], env["weak_reasons"], len(env["results"])

    env = retrieve_multi(WEAK[0], WEAK[1], a.top_k, trace_id="sample-multi")
    (out / "04_retrieve_multi.json").write_text(json.dumps({**head, "call": "retrieve_multi", "query": WEAK[0],
                                                            "filters": WEAK[1], **cut(env, a.max_text)},
                                                           indent=1, ensure_ascii=False))
    saved["04_retrieve_multi"] = env["evidence_status"], env["weak_reasons"], len(env["results"])

    cov = {"check_coverage": [{"expected_status": s, "args": kw, "result": check_coverage(**kw, combine="independent")}
                              for s, kw in COVERAGE],
           "precheck_question": [{"question": q, "result": precheck_question(q)} for q in PRECHECK]}
    (out / "05_coverage.json").write_text(json.dumps(cov, indent=1, ensure_ascii=False, default=str))
    saved["05_coverage"] = [c["result"]["status"] for c in cov["check_coverage"]]

    # cell citation for the ok question: 82,886 (USD millions) = Microsoft's Q3 FY2026 total revenue
    ok = retrieve_with_status(OK[0], OK[1], a.top_k)
    raw = {c["chunk_id"]: c for c in retr.chunks}
    chunks = [raw[r["chunk_id"]] for r in ok["results"] if r["chunk_id"] in raw]
    hits = find_cells(chunks, 82_886e6, "2026-03-31", 3, kind="amount")
    cells = [{k: v for k, v in h.items() if not k.startswith("_")} for h in hits[:3]]
    (out / "06_cell_citations.json").write_text(json.dumps(
        {"status": "draft (contract v1.3 §20)", "question": OK[0], "answer_value": 82_886e6, "period_end": "2026-03-31",
         "period_months": 3, "cells": cells}, indent=1, ensure_ascii=False, default=str))
    saved["06_cell_citations"] = len(cells)

    (out / "README.md").write_text(
        f"# RAG sample outputs ({backend}, index {head['index_version']}, top_k {a.top_k})\n\n"
        + "\n".join(f"- `{k}`: {v}" for k, v in saved.items())
        + "\n\nText cut to {} characters; metadata as returned. Generated by scripts/export_agent_samples.py.\n"
          .format(a.max_text))
    for k, v in saved.items():
        print(f"{k}: {v}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
