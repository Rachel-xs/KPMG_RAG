"""Command line entry point:  python -m rag.cli <command> [options]

  ingest   download pilot filings from EDGAR           -> data/raw/
  chunk    section-aware chunking                      -> data/chunks/chunks.jsonl
  index    build BM25 + dense index                    -> data/index/
  pilot    ingest + chunk + index in one go
  search   query the index (prints top-k with metadata)
  answer   search + LLM answer with citations (needs OPENAI_API_KEY)
  eval     Experiment 1 on a gold set                  -> eval/results/
  demo     offline demo on tests/fixtures (no network, no API key)
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import textwrap
from pathlib import Path

from .config import ROOT, load_config


def _print_results(resp: dict, width: int = 300) -> None:
    for w in resp["warnings"]:
        print(f"WARNING: {w}")
    print(f"method={resp['method']} filters={resp['filters']} latency={resp['latency_ms']}ms index={resp['index_version']}\n")
    for r in resp["results"]:
        m = r["metadata"]
        tag = " [TABLE]" if m.get("is_table") else ""
        period = f"FY{m.get('fiscal_year')}" if m.get("fiscal_period") == "FY" else f"{m.get('fiscal_period')} FY{m.get('fiscal_year')}"
        title = (m.get("section_title") or "")[:60]
        print(f"#{r['rank']}  score={r['score']:.4f}  {r['ticker']} {r['form']} {period}  {r['section'] or 'Unlabeled'} {title}{tag}")
        ranks = {k: m[k] for k in ("bm25_rank", "dense_rank") if k in m}
        print(f"    {r['chunk_id']}  {ranks or ''}")
        snippet = r["text"].replace("\n", " ")
        print(textwrap.indent(textwrap.fill(snippet[:width] + ("..." if len(snippet) > width else ""), 100), "    "))
        print()


def _filters(a) -> dict:
    f = {}
    if a.ticker:
        f["ticker"] = a.ticker.split(",")
    if a.form:
        f["form"] = a.form
    if a.year:
        f["fiscal_year"] = [int(y) for y in a.year.split(",")]
    if a.period:
        f["fiscal_period"] = a.period
    if a.section:
        f["section"] = a.section
    if a.tables_only:
        f["is_table"] = True
    return f


def main(argv=None):
    p = argparse.ArgumentParser(prog="rag", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest")
    s.add_argument("--tickers", help="comma-separated; default from config.yaml")
    sub.add_parser("chunk")
    s = sub.add_parser("index")
    s.add_argument("--embedder", help="override retrieval.embedder, e.g. lsa or st:intfloat/e5-base-v2")
    s = sub.add_parser("pilot")
    s.add_argument("--embedder")

    for name in ("search", "answer"):
        s = sub.add_parser(name)
        s.add_argument("query")
        s.add_argument("--ticker")
        s.add_argument("--form")
        s.add_argument("--year", help="fiscal year(s), comma-separated")
        s.add_argument("--period", help="FY, Q1, Q2, Q3")
        s.add_argument("--section", help='e.g. "Item 1A"')
        s.add_argument("--tables-only", action="store_true")
        s.add_argument("--k", type=int, default=5 if name == "search" else 8)
        s.add_argument("--method", default="hybrid", choices=["bm25", "dense", "hybrid"])
        s.add_argument("--json", action="store_true", help="print raw JSON response")

    s = sub.add_parser("eval")
    s.add_argument("--gold", default=str(ROOT / "eval" / "gold_v0.jsonl"))
    s.add_argument("--methods", default="bm25,dense,hybrid")
    s.add_argument("--ks", default="5,10")
    s.add_argument("--filters", default="filtered,unfiltered", help="filtered, unfiltered, or both")
    s.add_argument("--include-drafts", action="store_true", help="also score questions with status=draft")
    sub.add_parser("demo")

    a = p.parse_args(argv)
    cfg = load_config(a.config)
    P = cfg["paths"]
    ch = cfg["chunking"]
    rc = cfg["retrieval"]

    if a.cmd in ("ingest", "pilot"):
        from .ingest import EdgarClient, download_filings

        tickers = a.tickers.split(",") if getattr(a, "tickers", None) else cfg["tickers"]
        download_filings(EdgarClient(cfg["user_agent"]), tickers, cfg["forms"], P["raw"])
    if a.cmd in ("chunk", "pilot"):
        from .chunk import chunk_corpus

        chunk_corpus(P["raw"], P["chunks"], ch["target_tokens"], ch["max_tokens"])
    if a.cmd in ("index", "pilot"):
        from .index import build_index

        build_index(P["chunks"], P["index"], a.embedder or rc["embedder"], P["cache"])

    if a.cmd in ("search", "answer"):
        from .retrieve import Retriever

        r = Retriever(P["index"], P["logs"], rc["rrf_k"], rc["candidate_k"])
        resp = r.search(a.query, _filters(a), top_k=a.k, method=a.method)
        if a.cmd == "search":
            print(json.dumps(resp, indent=2)) if a.json else _print_results(resp)
        else:
            from .generate import answer_with_citations

            out = answer_with_citations(a.query, resp["results"], cfg, P["logs"])
            print(json.dumps(out, indent=2) if a.json else f"{out['answer']}\n\n" + "\n".join(
                f"[{c['n']}] {c['ticker']} {c['form']} {c['reporting_period_end']} {c['section']}  {c['source_url']}" for c in out["citations"]
            ) + f"\n\ntokens in/out: {out['prompt_tokens']}/{out['completion_tokens']}  cost: {out['cost_usd']}")

    if a.cmd == "eval":
        from .evaluate import run_eval

        run_eval(P["index"], Path(a.gold), P["results"], methods=a.methods.split(","),
                 ks=tuple(int(k) for k in a.ks.split(",")), filter_modes=a.filters.split(","), log_dir=P["logs"],
                 include_drafts=a.include_drafts)

    if a.cmd == "demo":
        run_demo()


def run_demo() -> None:
    """Offline end-to-end run on two synthetic filings (tests/fixtures)."""
    from .chunk import chunk_corpus
    from .evaluate import run_eval
    from .index import build_index
    from .retrieve import Retriever

    fx = ROOT / "tests" / "fixtures"
    tmp = Path(tempfile.mkdtemp(prefix="rag_demo_"))
    raw = tmp / "raw"
    shutil.copytree(fx / "raw", raw)
    chunk_corpus(raw, tmp / "chunks.jsonl", 120, 200)  # small sizes so the tiny docs split
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    r = Retriever(tmp / "index", log_dir=tmp / "logs")
    print("\n=== Query: supply chain risks (filter ticker=ACME) ===")
    _print_results(r.search("supply chain disruption risks", {"ticker": "ACME"}, top_k=3), width=200)
    print("=== Query: total revenue table (no filter) ===")
    _print_results(r.search("total net revenue 2025 compared with 2024", None, top_k=3), width=200)
    run_eval(tmp / "index", fx / "gold_fixture.jsonl", tmp / "results", ks=(1, 3), log_dir=tmp / "logs")
    print(f"\nDemo artifacts in {tmp}")


if __name__ == "__main__":
    main()
