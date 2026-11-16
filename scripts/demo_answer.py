"""End-to-end demo for one question: pre-check -> retrieval -> answer -> table-cell citation -> explaining paragraph.

    python scripts/demo_answer.py "What was Microsoft's total revenue for the three months ended March 31, 2026, and what drove the increase?"
    python scripts/demo_answer.py "What was Microsoft's revenue for the quarter ended September 30, 2026?"   # pre-check stops it
    python scripts/demo_answer.py --model gpt-6-luna "..."      # any reader model; default = final_v1's

Uses the final_v1 settings (configs/final_v1.yaml): hybrid RRF, top 15, retrieve_multi for several targets, prompt v2.
Steps, all shown in the output (also saved as Markdown + JSON under eval/results/demo/):
  1. pre-check      rag.coverage: are the filings in the database? none / unresolved -> answer directly, stop.
  2. retrieval      restricted to the filings the pre-check found.
  3. answer         the reader (same prompt and JSON as the evaluation), with excerpt citations.
  4. cell citations every number in the answer -> the exact table cell (row, column, period), rag.cells.
  5. explanation    the narrative paragraphs the answer cites; if it cites only tables, the best non-table passage
                    of the same filing (MD&A) for the question.
This is the mentor's 10/29 ask: return the structured value and the text that explains it. One API call per run
(cached in eval/results/demo/cache.jsonl, so re-running a question is free).
"""
from __future__ import annotations

import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

_NUM_IN_TEXT = re.compile(
    r"(?:US\$|USD\s*|\$)?\s?\(?(-?\d[\d,]*(?:\.\d+)?)\)?\s*(million|billion|thousand|%|percent)?", re.I)
_SCALE = {"million": 1e6, "billion": 1e9, "thousand": 1e3}


def numbers_in(text: str) -> list[tuple[str, float, bool]]:
    """Dollar amounts and percentages stated in an answer, in base units: [(as written, value, is_percent)].
    Years, dates and small bare integers are skipped."""
    out = []
    for m in _NUM_IN_TEXT.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        whole = m.group(0).strip()
        v = float(raw.replace(",", ""))
        if not unit and "$" not in whole and "USD" not in whole.upper():
            continue  # bare number: a year, a day, a count
        if re.fullmatch(r"(?:19|20)\d\d", raw):
            continue
        pct = unit in ("%", "percent")
        out.append((whole, v if pct else v * _SCALE.get(unit, 1.0), pct))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--preset", default="final_v1")
    ap.add_argument("--model", default=None, help="reader model (default: the preset's)")
    ap.add_argument("--out", default="eval/results/demo")
    a = ap.parse_args()

    import yaml
    from run_round1_reader import PROMPTS, Reader, fmt_context  # noqa: F401
    from rag.cells import find_cells
    from rag.coverage import CoverageIndex, extract_request
    from rag.config import load_config
    from rag.multi import multi_search, split_filters
    from rag.retrieve import Retriever

    p = yaml.safe_load((ROOT / "configs" / f"{a.preset}.yaml").read_text())
    model = a.model or p["reader"]["model"]
    gen = load_config().get("generation", {})
    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    log = {"question": a.question, "preset": a.preset, "model": model}
    md = [f"# {a.question}\n", f"_settings: {a.preset} (hybrid RRF, top {p['retrieval']['top_k']}, prompt "
                               f"{p['reader']['prompt']}), reader {model}_\n"]

    # 1. pre-check ------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    retr = Retriever(ROOT / p["index"]["dir"], log_dir=None)
    cov = CoverageIndex.from_chunks(ROOT / p["index"]["dir"] / "chunks.jsonl")
    req = extract_request(a.question, cov)
    pc = cov.check(**req, combine="independent")
    log["precheck"] = {"request": req, "status": pc["status"], "targets": pc["targets"], "message": pc["message"]}
    md += ["## 1. Pre-check", f"- extracted: {json.dumps({k: v for k, v in req.items() if v})}",
           f"- status: **{pc['status']}** - {pc['message']}"]
    if pc["status"] in ("none", "unresolved"):
        md += ["", "**Stopped before retrieval:** the Agent answers directly with the message above and the "
                   "filings we do have:", *[f"  - {t}: " + "; ".join(v) for t, v in pc["available"].items()]]
        return finish(out_dir, md, log)

    # 2. retrieval -----------------------------------------------------------------------------------------
    tickers = sorted({e["ticker"] for e in pc["entities"] if e["ticker"]})
    filters = dict(pc["filters"] or {})
    if not filters and tickers:
        filters = {"ticker": tickers}
    k = p["retrieval"]["top_k"]
    t1 = time.perf_counter()
    if p["retrieval"].get("multi") and len(split_filters(filters)) > 1:
        env = multi_search(lambda qq, f, kk, trace_id=None: retr.search(qq, filters=f, top_k=kk, method="hybrid"),
                           a.question, filters, top_k=k)
    else:
        env = retr.search(a.question, filters=filters or None, top_k=k, method="hybrid")
    res = env["results"]
    ret_ms = round((time.perf_counter() - t1) * 1000)
    md += ["", "## 2. Retrieval", f"- filters: {json.dumps(filters)}", f"- {len(res)} excerpts in {ret_ms} ms; "
           f"evidence_status: {env.get('evidence_status', 'n/a')}"]
    log["retrieval"] = {"filters": filters, "n": len(res), "ms": ret_ms,
                        "chunk_ids": [r["chunk_id"] for r in res]}

    # 3. answer --------------------------------------------------------------------------------------------
    reader = Reader(model, p["reader"]["prompt"], out_dir / "cache.jsonl",
                    gen.get("price_per_1m_input"), gen.get("price_per_1m_output"), False)
    ans = reader(a.question, fmt_context(res, False))
    cites = [c for c in ans.get("cites") or [] if isinstance(c, int) and 1 <= c <= len(res)]
    cited = [res[c - 1] for c in cites]
    md += ["", "## 3. Answer", f"> {ans.get('answer_text', '')}", "",
           f"- cited excerpts: {', '.join(f'[{c}]' for c in cites) or 'none'}",
           f"- reader: {reader.last.get('prompt_tokens')} input / {reader.last.get('completion_tokens')} output tokens, "
           f"{reader.last.get('latency_ms')} ms" + (" (cached)" if reader.last.get("cached") else "")]
    log["answer"] = {**ans, "reader": reader.last}

    # 4. cell citations ------------------------------------------------------------------------------------
    raw = {c["chunk_id"]: c for c in retr.chunks}
    cited_raw = [raw[r["chunk_id"]] for r in cited if r["chunk_id"] in raw]
    accs = {r.get("accession_number") for r in cited} or set(filters.get("accession_number") or [])
    same_filing_tables = [c for c in retr.chunks if c.get("is_table") and (c.get("accession_number") or c.get("accession")) in accs]
    pe = ans.get("period_end")
    months = 3 if re.search(r"three months|quarter", a.question, re.I) else \
        9 if re.search(r"nine months", a.question, re.I) else 12 if re.search(r"fiscal year|full year|annual", a.question, re.I) else None
    md += ["", "## 4. Numbers -> table cells", "| as written | table | row | column | printed | period check |",
           "|---|---|---|---|---|---|"]
    cells = []
    prior = None
    if pe:
        y, m_, d_ = (int(x) for x in pe.split("-"))
        prior = f"{y - 1:04d}-{m_:02d}-{min(d_, 28) if m_ == 2 else d_:02d}"
    for whole, v, pct in numbers_in(ans.get("answer_text") or ""):
        k_ = "percent" if pct else "amount"
        h, mark = None, ""
        for when, label in ((pe, "✓"), (prior, "✓ prior-year column")):
            hits = find_cells(cited_raw, v, when, months, kind=k_) or find_cells(same_filing_tables, v, when, months, kind=k_)
            if hits and (hits[0]["period_match"] or h is None):
                h = hits[0]
                mark = label if h["period_match"] else ("? (column has no period)" if h["period_match"] is None else "✗")
                if h["period_match"]:
                    break
        cells.append({"as_written": whole, "value": v, "cell": h, "check": mark})
        if h:
            md.append(f"| {whole} | {h['table_name'] or ''} | {' > '.join(h['row_path'])} | {h['column_header']} | "
                      f"{h['value_text']} | {mark} |")
        else:
            md.append(f"| {whole} | - | - | - | not printed in a table (computed or stated in text) | |")
    log["cells"] = cells

    # 5. explanation ---------------------------------------------------------------------------------------
    prose = [r for r in cited if not (raw.get(r["chunk_id"]) or {}).get("is_table")]
    source = "cited by the answer"
    if not prose and accs:
        env2 = retr.search(a.question, filters={"accession_number": sorted(accs), "is_table": False}, top_k=2,
                           method="hybrid")
        prose, source = env2["results"], "best narrative passages in the same filing (the answer cited only tables)"
    md += ["", "## 5. Explanation", f"_{source}_", ""]
    for r in prose[:2]:
        m = r.get("metadata") or {}
        md += [f"**{r.get('ticker')} {r['form']} · {m.get('section_title') or r.get('section') or ''}**",
               "> " + re.sub(r"\s+", " ", r["text"])[:700] + ("…" if len(r["text"]) > 700 else ""), ""]
    log["explanation"] = [{"chunk_id": r["chunk_id"], "section": (r.get("metadata") or {}).get("section_title")}
                          for r in prose[:2]]
    log["total_ms"] = round((time.perf_counter() - t0) * 1000)
    md += [f"_total {log['total_ms']} ms_"]
    return finish(out_dir, md, log)


def finish(out_dir: Path, md: list[str], log: dict):
    slug = re.sub(r"[^a-z0-9]+", "-", log["question"].lower())[:60].strip("-")
    (out_dir / f"{slug}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / f"{slug}.json").write_text(json.dumps(log, indent=1, default=str), encoding="utf-8")
    print("\n".join(md))
    print(f"\nSaved {out_dir / slug}.md / .json")


if __name__ == "__main__":
    main()
