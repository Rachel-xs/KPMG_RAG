"""Round 1 reader evaluation: RAG top-k -> answer model -> Eval's graders (Gold Set v2).

    python scripts/run_round1_reader.py --dry-run --limit 5     # no API calls: check retrieval + prompt size
    python scripts/run_round1_reader.py --limit 5               # smoke test (5 questions, a few cents at most)
    python scripts/run_round1_reader.py                         # full run, prompt v2 (period-aware)
    python scripts/run_round1_reader.py --prompt v1             # baseline prompt, for the before/after

Needs OPENAI_API_KEY in .env (loaded by rag.config) and the Round 1 index (data/round1/index_C1).

What it measures
  numbers        Numerical Answer Accuracy with Eval's own grader (eval/vendor/kpmg_eval, pinned from
                 thomassong0604-oss/kpmg-eval @ 0fd5695, Week 8): correct / wrong_period / wrong_scale / ...
                 Each number question is also split by whether retrieval found every input figure in the
                 top k (strict, same rule as run_round1_eval.py), so every miss is either a
                 RETRIEVAL error (figure not retrieved) or a READING error (retrieved, answered wrongly).
  refusals       unanswerable questions: did the reader decline? (Eval's classify_response)
  false premise  corrected / rejected / accepted (Eval's classify_premise)
  categorical    every required point appears in the answer (rule-based; check by hand)
  narrative      answers saved for Eval's judge, not scored here
  graph route    Exhibit 21 questions RAG cannot answer: reported separately (should decline -> fallback)
  NTAP 10-Q      excluded, as in the retrieval run

Answers are cached (eval/results/round1/reader/cache.jsonl) by model + prompt + context hash, so re-running
after a code change costs nothing; change the prompt or the model and only then are new calls made.
"""
from __future__ import annotations

import argparse, csv, hashlib, json, os, sys, time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "eval" / "vendor")]
from rag.config import load_config  # noqa: E402  (also loads .env)
from run_round1_eval import kind as retrieval_kind, score as retrieval_score  # noqa: E402
from kpmg_eval.metrics.numeric import naa_summary, score_numeric  # noqa: E402
from kpmg_eval.metrics.premise import classify_premise, premise_summary  # noqa: E402
from kpmg_eval.metrics.refusal import classify_response, score_raa  # noqa: E402

PROMPTS = {
    "v1": """You answer questions about companies using ONLY the numbered SEC filing excerpts provided.
- Quote numbers exactly as they appear, with units.
- If the excerpts do not contain the answer, decline. Do not guess.""",
    "v2": """You answer questions about companies using ONLY the numbered SEC filing excerpts provided.
Rules for numbers:
- Financial tables have several columns for different periods (e.g. three months vs nine months / year to date,
  current year vs prior year, or two balance-sheet dates). First decide which period the question asks for, then
  read the column whose header matches that period exactly. Never take the prior-period or year-to-date column
  when the question asks for the quarter, and vice versa.
- Check the table's scale ("In millions", "In thousands", per-share) and keep the figure exactly as printed.
- Parentheses mean a negative number.
- For a calculation, find each input in the excerpts, state it, then compute.
Rules for everything else:
- If the question rests on a false premise (e.g. asks why something fell when it rose), say so and give the correct fact.
- If the excerpts do not contain the answer, decline. Do not guess, estimate or use outside knowledge.""",
}

JSON_SPEC = """Return JSON only:
{"answered": true|false,            // false = the excerpts do not contain the answer
 "answer_text": "...",              // one or two sentences
 "value": number|null,              // headline number in base units (dollars, not millions); percent as e.g. 18.3
 "value_text": "..."|null,          // the number as you state it, with scale, e.g. "USD 82,886 million", "$2.94", "18.3%"
 "unit": "USD"|"USD/shares"|"%"|"pp"|"count"|null,
 "period_end": "YYYY-MM-DD"|null,   // end date of the period the number refers to
 "cites": [1, 3]}                   // excerpt numbers used"""


def fmt_context(results: list[dict], use_parent: bool) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        m = r.get("metadata") or {}
        head = [f"{r['company_name']} ({r.get('ticker') or ''})", r["form"]]
        if m.get("fiscal_year"):
            head.append(f"FY{m['fiscal_year']} {m.get('fiscal_period') or ''}".strip())
        if r.get("reporting_period_end"):
            head.append(f"period ended {r['reporting_period_end']}")
        head.append(m.get("section_path") or m.get("section_title") or r.get("section") or "")
        if m.get("table_name"):
            head.append(f"table: {m['table_name']}")
        text = (m.get("parent_text") if use_parent else None) or r["text"]
        parts.append(f"[{i}] " + " | ".join(h for h in head if h) + "\n" + text)
    return "\n\n---\n\n".join(parts)


class Reader:
    def __init__(self, model: str, prompt: str, cache_path: Path, price_in, price_out, dry_run: bool):
        self.model, self.prompt, self.dry = model, prompt, dry_run
        self.price_in, self.price_out = price_in, price_out
        self.cache_path = cache_path
        self.cache = {}
        if cache_path.exists():
            for line in open(cache_path, encoding="utf-8"):
                d = json.loads(line)
                self.cache[d["key"]] = d
        self.client = None
        self.tokens = Counter()

    def __call__(self, question: str, context: str) -> dict:
        system = PROMPTS[self.prompt] + "\n\n" + JSON_SPEC
        user = f"Excerpts:\n\n{context}\n\nQuestion: {question}"
        key = hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()[:24]
        if key in self.cache:
            d = self.cache[key]
            self.tokens["cached_calls"] += 1
        elif self.dry:
            n = (len(system) + len(user)) // 4
            self.tokens["est_prompt_tokens"] += n
            return {"answered": False, "answer_text": "(dry run)", "value": None, "cites": [], "_dry": True}
        else:
            if self.client is None:
                from openai import OpenAI
                if not os.environ.get("OPENAI_API_KEY"):
                    raise SystemExit("OPENAI_API_KEY is not set: add OPENAI_API_KEY=sk-... to .env in the repo root")
                self.client = OpenAI()
            t0 = time.perf_counter()
            resp = self.client.chat.completions.create(
                model=self.model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            d = {"key": key, "model": self.model, "prompt": self.prompt, "raw": resp.choices[0].message.content,
                 "prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens,
                 "latency_ms": round((time.perf_counter() - t0) * 1000)}
            with open(self.cache_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(d) + "\n")
            self.cache[key] = d
            self.tokens["api_calls"] += 1
        self.tokens["prompt_tokens"] += d["prompt_tokens"]
        self.tokens["completion_tokens"] += d["completion_tokens"]
        try:
            out = json.loads(d["raw"])
        except json.JSONDecodeError:
            out = {"error": "bad_json", "answer_text": d["raw"]}
        return out

    def cost(self) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return (self.tokens["prompt_tokens"] * self.price_in + self.tokens["completion_tokens"] * self.price_out) / 1e6


def group(q: dict) -> str:
    if q.get("snapshot_status") == "review_required":
        return "ntap_10q_excluded"
    if q.get("route_expected") == "graph":
        return "graph_route"
    return {"exact_numeric": "number", "refusal": "refusal", "false_premise": "false_premise",
            "exact_categorical": "categorical", "narrative": "narrative"}[q["answer_type"]]


def to_block(q: dict, ans: dict, results: list[dict], trace_id: str) -> dict:
    """The reader's JSON -> Eval's AnswerBlock (chunk ids instead of excerpt numbers)."""
    cites = [c for c in ans.get("cites") or [] if isinstance(c, int) and 1 <= c <= len(results)]
    b = {"trace_id": trace_id, "qid": q["qid"], "answered": bool(ans.get("answered", True)),
         "answer_text": ans.get("answer_text") or "", "value": ans.get("value"), "value_text": ans.get("value_text"),
         "unit": ans.get("unit"), "period_end": ans.get("period_end"),
         "citations": [{"id": results[c - 1]["chunk_id"], "source": "vector_rag",
                        "accession": results[c - 1]["accession_number"], "section": results[c - 1].get("section") or ""}
                       for c in cites]}
    if ans.get("error"):
        b["error"] = ans["error"]
    if not b["answered"]:
        b["value"] = b["value_text"] = None
    return b


def grade(q: dict, g: str, block: dict) -> dict:
    out = {}
    text = block["answer_text"]
    if g == "number":
        r = score_numeric(q, block)
        out.update(passed=r.passed, label=r.label, answered_value=r.answered_value, detail=r.detail)
    elif g in ("refusal",):
        c = classify_response(block)
        out.update(passed=c == "refused", label=c)
    elif g == "false_premise":
        lab = classify_premise(text, q["answer"].get("required_points") or [])
        out.update(passed=lab == "corrected", label=lab)
    elif g == "categorical":
        pts = q["answer"].get("required_points") or []
        hit = [p for p in pts if p.lower() in text.lower()]
        out.update(passed=bool(pts) and len(hit) == len(pts), label=f"{len(hit)}/{len(pts)} points")
    else:
        out.update(passed=None, label=classify_response(block))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2.jsonl")
    ap.add_argument("--model", default=None, help="default: generation.model in config.yaml")
    ap.add_argument("--prompt", default="v2", choices=sorted(PROMPTS))
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--method", default="hybrid")
    ap.add_argument("--parent", action="store_true", help="give the reader parent_text instead of the chunk text")
    ap.add_argument("--limit", type=int, default=None, help="first N questions only (smoke test)")
    ap.add_argument("--qids", default=None, help="comma-separated question ids")
    ap.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens (default: config.yaml)")
    ap.add_argument("--price-out", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true", help="retrieve and build prompts, no API calls")
    ap.add_argument("--out", default="eval/results/round1/reader")
    a = ap.parse_args()

    cfg = load_config()
    gen = cfg.get("generation", {})
    model = a.model or gen.get("model", "gpt-4o-mini")
    p_in = a.price_in if a.price_in is not None else gen.get("price_per_1m_input")
    p_out = a.price_out if a.price_out is not None else gen.get("price_per_1m_output")

    from rag.retrieve import Retriever
    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    if a.qids:
        want = set(a.qids.split(","))
        gold = [q for q in gold if q["qid"] in want]
    if a.limit:
        gold = gold[: a.limit]

    tag = f"{model}_{a.prompt}_k{a.top_k}" + ("_parent" if a.parent else "")
    base = ROOT / a.out
    out = base / tag
    out.mkdir(parents=True, exist_ok=True)
    reader = Reader(model, a.prompt, base / "cache.jsonl", p_in, p_out, a.dry_run)
    retr = Retriever(ROOT / a.index, log_dir=None)

    rows, blocks = [], []
    for i, q in enumerate(gold, 1):
        g = group(q)
        trace_id = f"round1-reader-{q['qid']}"
        env = retr.search(q["question"], filters=q.get("filters") or None, top_k=a.top_k, method=a.method, trace_id=trace_id)
        res = env["results"]
        ans = reader(q["question"], fmt_context(res, a.parent)) if res else \
            {"answered": False, "answer_text": "No evidence was retrieved.", "value": None, "cites": []}
        block = to_block(q, ans, res, trace_id)
        row = {"qid": q["qid"], "group": g, "type": q["type"], "tickers": "|".join(q["tickers"]),
               "question": q["question"], "gold": q["answer"].get("display"),
               "evidence_status": env.get("evidence_status"), "weak_reasons": "|".join(env.get("weak_reasons") or []),
               "n_results": len(res), "answered": block["answered"], "answer_text": block["answer_text"],
               "value_text": block.get("value_text"), "period_end": block.get("period_end"),
               "cited_chunks": "|".join(c["id"] for c in block["citations"])}
        if not ans.get("_dry"):
            row.update(grade(q, g, block))
        if g in ("number", "ntap_10q_excluded") and retrieval_kind(q) in ("number", "ntap_10q_excluded"):
            row["retrieved_all_figures"] = retrieval_score(q, res).get(f"strict@{a.top_k}")
        if row.get("passed") is False and row.get("retrieved_all_figures") is not None:
            row["error_source"] = "reading" if row["retrieved_all_figures"] else "retrieval"
        rows.append(row)
        blocks.append(block)
        if i % 10 == 0 or i == len(gold):
            print(f"  {i}/{len(gold)}  calls {reader.tokens['api_calls']}  cached {reader.tokens['cached_calls']}", flush=True)

    if a.dry_run:
        print(f"\nDry run: {len(gold)} questions, est. {reader.tokens['est_prompt_tokens']:,} prompt tokens "
              f"(~{reader.tokens['est_prompt_tokens'] // max(len(gold), 1):,} per question). No API calls made.")
        return

    by = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    groups_line = ", ".join(f"{k} {len(v)}" for k, v in by.items())
    nums = by["number"]
    from kpmg_eval.metrics.numeric import NumericResult
    naa = naa_summary([NumericResult(r["qid"], r["passed"], r["label"]) for r in nums])
    miss = [r for r in nums if not r["passed"]]
    hit_ret = [r for r in nums if r.get("retrieved_all_figures")]
    summary = {
        "model": model, "prompt": a.prompt, "top_k": a.top_k, "method": a.method, "parent_text": a.parent,
        "index": a.index, "gold": a.gold, "n_questions": len(rows), "groups": {k: len(v) for k, v in by.items() if v},
        "numbers": {**naa,
                    "errors_by_source": dict(Counter(r.get("error_source") for r in miss)),
                    "accuracy_when_retrieved": (sum(r["passed"] for r in hit_ret) / len(hit_ret)) if hit_ret else None,
                    "n_retrieved": len(hit_ret)},
        "refusal": {"n": len(by["refusal"]), "declined": sum(bool(r["passed"]) for r in by["refusal"])},
        "raa": score_raa([(True, b) for b, r in zip(blocks, rows) if r["group"] in ("number", "categorical", "false_premise", "narrative")]
                         + [(False, b) for b, r in zip(blocks, rows) if r["group"] == "refusal"]),
        "false_premise": premise_summary([r["label"] for r in by["false_premise"]]),
        "categorical": {"n": len(by["categorical"]), "all_points": sum(bool(r["passed"]) for r in by["categorical"])},
        "graph_route": {"n": len(by["graph_route"]), "declined": sum(not r["answered"] for r in by["graph_route"])},
        "evidence_status_vs_correct": {s: dict(Counter("correct" if r["passed"] else "wrong" for r in nums if r["evidence_status"] == s))
                                       for s in sorted({r["evidence_status"] for r in nums if r["evidence_status"]})},
        "tokens": dict(reader.tokens), "cost_usd": reader.cost(),
    }

    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        cols = list(dict.fromkeys(c for r in rows for c in r))
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(out / "answer_blocks.jsonl", "w", encoding="utf-8") as fh:
        for b in blocks:
            fh.write(json.dumps(b, ensure_ascii=False) + "\n")
    json.dump(summary, open(out / "summary.json", "w"), indent=1, ensure_ascii=False)

    n = summary["numbers"]
    pct = lambda x: "-" if x is None else f"{x:.3f}"  # noqa: E731
    md = [f"# Round 1 reader results: {model}, prompt {a.prompt}, {a.method} top {a.top_k}\n",
          f"{len(rows)} questions: {groups_line}.\n",
          "## Numbers (Eval's NAA grader)", "",
          f"- **Numerical answer accuracy: {pct(n['naa'])}** ({sum(r['passed'] for r in nums)}/{len(nums)})",
          f"- When retrieval found every input figure: {pct(n['accuracy_when_retrieved'])} (n={n['n_retrieved']})",
          f"- Wrong answers by source: {n['errors_by_source']}",
          f"- Wrong answers by label: { {k: v for k, v in n['by_label'].items() if v and k != 'correct'} }", "",
          "## Other question types", "",
          f"- Unanswerable, declined: {summary['refusal']['declined']}/{summary['refusal']['n']}",
          f"- Balanced refusal accuracy (RAA): {pct(summary['raa']['balanced_raa'])}; "
          f"unnecessary refusals {pct(summary['raa']['unnecessary_refusal_rate'])}",
          f"- False premise: {summary['false_premise']}",
          f"- Categorical, all required points: {summary['categorical']['all_points']}/{summary['categorical']['n']} (rule-based, check by hand)",
          f"- Exhibit 21 (graph route), declined by the RAG reader: {summary['graph_route']['declined']}/{summary['graph_route']['n']}",
          f"- Narrative: {len(by['narrative'])} answers saved for Eval's judge, not scored here", "",
          f"evidence_status vs number correctness: {summary['evidence_status_vs_correct']}", "",
          f"Tokens: {summary['tokens']}; cost: " + ("n/a (set prices in config.yaml)" if summary["cost_usd"] is None else f"${summary['cost_usd']:.3f}"), "",
          "## Wrong number answers", "", "| qid | source | label | answer | gold |", "|---|---|---|---|---|"]
    md += [f"| {r['qid']} | {r.get('error_source') or ''} | {r['label']} | {(r.get('value_text') or r['answer_text'])[:60]} | {r['gold']} |"
           for r in miss]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:18]))
    print(f"\nWrote {out}/summary.md, summary.json, per_question.csv, answer_blocks.jsonl")


if __name__ == "__main__":
    main()
