"""Query rewriting vs Agent extraction (mentor 11/19; exploratory, not pre-registered).

Step 1 of 3: read company / period filters out of each messy-wording question with one LLM call.

Arms
  rag_llm  RAG side. One LLM call reads companies, period-end dates, fiscal years / quarters and forms from the
           question; rag.coverage maps them to the indexed filings, exactly as `--filters precheck` does with its
           rule-based extractor. A company or period the corpus does not hold -> declined, no retrieval.
  agents   Agents side. The Agent team's understand_query_llm() from yz5405/kpmg-agentic-backbone @ d89208c,
           imported unchanged, then their query_node mapping (ticker / tickers -> ticker, fiscal_year,
           fiscal_period). Passed to retrieve() as is; their flow has no pre-check yet.

Both arms use the same model (default gpt-6-luna) so the comparison is about the extraction, not the model.

    python scripts/qr_extract_filters.py --arm rag_llm
    python scripts/qr_extract_filters.py --arm agents --agents-repo ../../kpmg-agentic-backbone
    python scripts/qr_extract_filters.py --arm rag_llm --limit 5          # smoke test
    python scripts/qr_extract_filters.py --arm agents_precheck            # post-hoc, no LLM calls (see below)

Post-hoc arm (added 11/22 after seeing the two arms above on this suite; NOT an independent result):
  agents_precheck  the companies from the Agents' LLM extraction (filters_agents.jsonl, no new calls) + the periods,
                   dates and forms read by rag.coverage's rule extractor, mapped to filings by check_coverage().
                   The Agents' fiscal_year / fiscal_period are NOT used as filters (21 wrong quarters in arm B).
                   This is the integration we recommend to the Agent team.

Writes eval/results/query_rewrite/filters_<arm>.jsonl (one row per question). Re-running skips qids already written.
"""
from __future__ import annotations

import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.config import load_config  # noqa: E402  (loads .env: OPENAI_API_KEY, OPENAI_BASE_URL)
from rag.coverage import CoverageIndex, extract_request  # noqa: E402

PRICES = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.0, 5.0)}  # USD per 1M input / output tokens

RAG_SYSTEM = """You read one question about US public companies' SEC filings and extract what it asks for.
The question may contain typos, informal company names or analyst slang.
Return a JSON object with exactly these keys:
  "companies": company names or tickers the question asks about, with typos corrected
               (e.g. "Microsfot" -> "Microsoft", "Take Two" -> "Take-Two Interactive"); [] if none.
  "period_ends": ISO dates (YYYY-MM-DD) of reporting-period ends the question states explicitly
                 (e.g. "three months ended March 31, 2026" -> "2026-03-31"); [] if none.
  "fiscal_years": fiscal years the question states explicitly (e.g. "FY2025", "fiscal 2025" -> 2025); [] if none.
  "fiscal_periods": any of "Q1","Q2","Q3","Q4","FY" the question states explicitly; [] if none.
  "forms": any of "10-K","10-Q" if the question names the report type
           (annual report -> "10-K", quarterly report -> "10-Q"); [] if none.
Only extract what the question says. Do not guess, and do not convert calendar dates into fiscal years or quarters."""


def as_list(x):
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def precheck_filters(pc: dict) -> tuple[dict | None, bool]:
    """Same mapping as run_round1_reader.filters_for(mode='precheck'): (filters, declined)."""
    if pc["status"] in ("none", "unresolved"):
        return None, True
    if not pc["filters"]:
        return None, False  # no_target: search the whole index
    tickers = sorted({t["ticker"] for t in pc["targets"] if t["status"] == "hit"})
    return {"ticker": tickers if len(tickers) > 1 else tickers[0],
            "accession_number": pc["filters"]["accession_number"]}, False


class RagExtractor:
    def __init__(self, model: str, cov: CoverageIndex):
        from openai import OpenAI
        self.client, self.model, self.cov = OpenAI(), model, cov

    def __call__(self, question: str) -> dict:
        t0 = time.perf_counter()
        kw = dict(model=self.model, response_format={"type": "json_object"},
                  messages=[{"role": "system", "content": RAG_SYSTEM}, {"role": "user", "content": question}])
        usage, mode, raw = {}, "llm", None
        try:
            try:
                resp = self.client.chat.completions.create(temperature=0, **kw)
            except Exception as e:  # newer models only accept the default temperature
                if "temperature" not in str(e):
                    raise
                resp = self.client.chat.completions.create(**kw)
            usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
            raw = json.loads(resp.choices[0].message.content)
            req = {"companies": as_list(raw.get("companies")) or None,
                   "period_ends": as_list(raw.get("period_ends")) or None,
                   "fiscal_years": [int(y) for y in as_list(raw.get("fiscal_years")) if str(y).isdigit()] or None,
                   "fiscal_periods": [p for p in as_list(raw.get("fiscal_periods")) if p in ("Q1", "Q2", "Q3", "Q4", "FY")] or None,
                   "forms": [f for f in as_list(raw.get("forms")) if f in ("10-K", "10-Q")] or None}
        except Exception as e:  # bad JSON or API error: fall back to the rule-based extractor, and say so
            mode, raw = "rule_based_fallback", {"error": str(e)[:200]}
            req = extract_request(question, self.cov)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        pc = self.cov.check(**req, combine="independent")
        filters, declined = precheck_filters(pc)
        return {"filters": filters, "declined": declined, "precheck_status": pc["status"],
                "message": pc["message"], "extract": raw, "request": req, "mode": mode,
                "latency_ms": ms, **usage}


class AgentsExtractor:
    """understand_query_llm() from the Agents repo, unchanged; token usage captured by wrapping their client."""

    def __init__(self, model: str, repo: Path):
        if not (repo / "agent" / "llm_query_understanding.py").exists():
            raise SystemExit(f"Agents repo not found at {repo} (clone yz5405/kpmg-agentic-backbone, "
                             "branch feature/dual-llm-integration-v03)")
        sys.path.insert(0, str(repo))
        os.environ["KPMG_QUERY_LLM_ENABLED"] = "1"
        os.environ["KPMG_QUERY_LLM_MODEL"] = model
        import agent.llm_client as lc
        from agent.llm_query_understanding import understand_query_llm
        self.fn, self.last = understand_query_llm, {}
        orig = lc.ChatCompletionClient.complete
        outer = self

        def complete(self_, **kw):
            try:
                c = orig(self_, **kw)
            except Exception as e:
                outer.last = {"error": type(e).__name__ + ": " + str(e)[:150],
                              **({"usage": e.token_usage} if getattr(e, "token_usage", None) else {})}
                raise
            outer.last = {"usage": c.token_usage, "content": c.content}
            return c
        lc.ChatCompletionClient.complete = complete
        try:
            import subprocess
            self.commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                                         capture_output=True, text=True).stdout.strip()
        except Exception:
            self.commit = ""

    def __call__(self, question: str) -> dict:
        self.last = {}
        t0 = time.perf_counter()
        parsed = self.fn(question)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        # their query_node (agent/graph_workflow.py @ d89208c), copied verbatim in logic
        filters = {k: parsed.get(k) for k in ("ticker", "fiscal_year", "fiscal_period") if parsed.get(k) is not None}
        tickers = parsed.get("tickers") or []
        if len(tickers) > 1:
            filters["ticker"] = tickers
        elif tickers and "ticker" not in filters:
            filters["ticker"] = tickers[0]
        u = self.last.get("usage") or {}
        return {"filters": filters or None, "declined": False, "precheck_status": "",
                "message": "", "extract": {k: parsed.get(k) for k in parsed},
                "llm_content": self.last.get("content"), "llm_error": self.last.get("error"),
                "mode": parsed.get("query_understanding_mode"), "latency_ms": ms,
                "prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}


class AgentsPrecheck:
    """Post-hoc: Agents' LLM companies + rule-based periods -> check_coverage(). Reads filters_agents.jsonl."""

    def __init__(self, path: Path, cov: CoverageIndex):
        if not path.exists():
            raise SystemExit(f"{path} missing: run --arm agents first")
        self.table = {r["qid"]: r for r in (json.loads(l) for l in open(path, encoding="utf-8"))}
        self.cov = cov

    def __call__(self, qid: str, question: str) -> dict:
        t0 = time.perf_counter()
        b = self.table[qid]
        ex = b.get("extract") or {}
        tickers = [t for t in (as_list(ex.get("tickers")) or as_list(ex.get("ticker"))) if t]
        rules = extract_request(question, self.cov)
        req = {"tickers": tickers or None, "companies": None if tickers else rules["companies"],
               "period_ends": rules["period_ends"], "fiscal_years": rules["fiscal_years"],
               "fiscal_periods": rules["fiscal_periods"], "forms": rules["forms"]}
        pc = self.cov.check(**req, combine="independent")
        filters, declined = precheck_filters(pc)
        return {"filters": filters, "declined": declined, "precheck_status": pc["status"], "message": pc["message"],
                "extract": {"agents_tickers": tickers, "agents_mode": b.get("mode")}, "request": req,
                "mode": "agents_llm_companies+rules_periods" if tickers else "rules_only (agents found no company)",
                "latency_ms_precheck": round((time.perf_counter() - t0) * 1000, 2),
                # the Agents' extraction call is already paid for in their flow; carry its cost and latency over
                "latency_ms": b.get("latency_ms"), "prompt_tokens": b.get("prompt_tokens"),
                "completion_tokens": b.get("completion_tokens"), "posthoc": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["rag_llm", "agents", "agents_precheck"], required=True)
    ap.add_argument("--suite", default="eval/suites/messy_wording_v1.jsonl")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--agents-repo", default="../kpmg-agentic-backbone")
    ap.add_argument("--manifest", default="data/round1/index_C1/chunks.jsonl", help="same 20 filings as chroma_C1")
    ap.add_argument("--out", default="eval/results/query_rewrite")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    load_config()
    if a.arm != "agents_precheck" and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set (.env in the repo root)")
    qs = [json.loads(l) for l in open(ROOT / a.suite, encoding="utf-8")]
    if a.limit:
        qs = qs[: a.limit]
    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"filters_{a.arm}.jsonl"
    done = set()
    if path.exists():
        for line in open(path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["qid"])
            except Exception:
                pass

    if a.arm == "rag_llm":
        ex = RagExtractor(a.model, CoverageIndex.from_chunks(ROOT / a.manifest))
        source = "scripts/qr_extract_filters.py RAG_SYSTEM + rag.coverage"
    elif a.arm == "agents_precheck":
        ex = AgentsPrecheck(out_dir / "filters_agents.jsonl", CoverageIndex.from_chunks(ROOT / a.manifest))
        source = "POST-HOC: filters_agents.jsonl companies + rag.coverage rule periods + check_coverage"
    else:
        repo = (ROOT / a.agents_repo).resolve()
        ex = AgentsExtractor(a.model, repo)
        source = f"kpmg-agentic-backbone @ {ex.commit or 'unknown'} understand_query_llm + query_node mapping"
    p_in, p_out = PRICES.get(a.model, (None, None))
    todo = [q for q in qs if q["qid"] not in done]
    print(f"arm {a.arm}, model {a.model}: {len(todo)} to extract ({len(done)} already in {path.name}); source: {source}")
    with open(path, "a", encoding="utf-8") as fh:
        for i, q in enumerate(todo, 1):
            r = ex(q["qid"], q["question"]) if a.arm == "agents_precheck" else ex(q["question"])
            cost = None
            if p_in is not None and r.get("prompt_tokens") is not None:
                cost = (r["prompt_tokens"] * p_in + (r.get("completion_tokens") or 0) * p_out) / 1e6
            fh.write(json.dumps({"qid": q["qid"], "arm": a.arm, "model": a.model, "source": source,
                                 **r, "cost_usd": cost}, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", flush=True)

    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    from collections import Counter
    print("mode:", dict(Counter(r["mode"] for r in rows)))
    if a.arm in ("rag_llm", "agents_precheck"):
        print("pre-check status:", dict(Counter(r["precheck_status"] for r in rows)))
    c = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    if c:
        print(f"extraction cost ${sum(c):.4f} for {len(c)} questions (${sum(c) / len(c) * 1000:.3f} per 1,000)")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
