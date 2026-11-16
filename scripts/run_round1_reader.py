"""Round 1 reader evaluation: RAG top-k -> answer model -> Eval's graders (Gold Set v2).

    python scripts/run_round1_reader.py --dry-run --limit 5     # no API calls: check retrieval + prompt size
    python scripts/run_round1_reader.py --limit 5               # smoke test (5 questions, a few cents at most)
    python scripts/run_round1_reader.py                         # full run, prompt v2 (period-aware)
    python scripts/run_round1_reader.py --prompt v1             # baseline prompt, for the before/after
    python scripts/run_round1_reader.py --preset final_v1       # frozen final settings (configs/final_v1.yaml)

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

Cost and latency (mentor 11/12: compare methods on cost and latency, not only accuracy): every question records
the reader's input / output tokens (from the API response's `usage`), the reader call's latency, the retrieval
latency and the cost in USD; summary.json has per-question means and p50 / p95 latencies. A cached answer keeps
the tokens and latency of the call that produced it, so re-running a configuration reports the same costs.

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
from rag.multi import multi_search, split_filters  # noqa: E402
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


# final_v2 output spec (11/16), from Eval's round-1 asks:
#  - "answered" follows Eval's decision policy (POLICY_answer_clarify_abstain.md): true when every requested figure
#    or fact is stated and supported (GSv0-MSFT-023 stated its figure but came back answered=false); false (abstain)
#    when any requested part is missing or the question asks for advice / a forecast. A first version ("false only if
#    nothing answers", 11/16 run) turned partial answers into answers and blocked the Agent's fallback: replaced.
#  - "decision": answer / abstain (Eval's optional AnswerBlock field);
#  - "values" lists every figure a multi-part question asks for (Eval's optional AnswerBlock field, graded sign-sensitive).
JSON_SPEC_V2 = JSON_SPEC.replace(
    '{"answered": true|false,            // false = the excerpts do not contain the answer',
    '{"answered": true|false,            // true = you answer what the question asks: every requested figure or fact is\n'
    '                                   // stated and supported by the excerpts (correcting a false premise counts as an\n'
    '                                   // answer); a note about extra context you could not find does not make it false.\n'
    '                                   // false = abstain: any requested figure, company, period or list item is missing\n'
    '                                   // from the excerpts, or the question asks for investment advice or a forecast;\n'
    '                                   // answer_text then says what is missing and what is available\n'
    ' "decision": "answer"|"abstain",   // same choice as answered').replace(
    ' "value": number|null,              // headline number in base units (dollars, not millions); percent as e.g. 18.3',
    ' "value": number|null,              // headline number in base units (dollars, not millions); percent as e.g. 18.3;\n'
    '                                   // an amount spent, paid or repurchased is positive, as the question asks it').replace(
    ' "cites": [1, 3]}                   // excerpt numbers used',
    ' "values": [{"label": "...", "value": number, "unit": "...", "value_text": "..."}],\n'
    '                                   // every figure a multi-part question asks for, one entry each; a CHANGE is signed\n'
    '                                   // (a decrease is negative), amounts keep the sign the question asks; [] otherwise\n'
    ' "cites": [1, 3]}                   // excerpt numbers used')
assert JSON_SPEC_V2.count("true = you answer") == 1 and '"values"' in JSON_SPEC_V2 and "spent, paid" in JSON_SPEC_V2
SPECS = {"v1": JSON_SPEC, "v2": JSON_SPEC_V2}


# dev experiment (11/16): Eval's narrative judge found answers that state the main point but drop secondary required
# points; JSON_SPEC caps answer_text at one or two sentences. For narrative-type questions only, allow a fuller answer.
def long_spec(spec: str) -> str:
    """The narrative variant of an output spec: up to 5 sentences covering every reason / component asked for."""
    out = spec.replace(
        '"answer_text": "...",              // one or two sentences',
        '"answer_text": "...",              // for an explanation, comparison or definition: up to 5 sentences that state\n'
        '                                   // every distinct reason, component, segment or figure the question asks for;\n'
        '                                   // every claim must come from the excerpts (no outside knowledge)')
    assert out != spec
    return out


JSON_SPEC_LONG = JSON_SPEC.replace(
    '"answer_text": "...",              // one or two sentences',
    '"answer_text": "...",              // for an explanation, comparison or definition: up to 5 sentences that state\n'
    '                                   // every distinct reason, component, segment or figure the question asks for;\n'
    '                                   // every claim must come from the excerpts (no outside knowledge)')
assert JSON_SPEC_LONG != JSON_SPEC


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
        self.last: dict = {}

    def __call__(self, question: str, context: str, spec: str | None = None) -> dict:
        system = PROMPTS[self.prompt] + "\n\n" + (spec or JSON_SPEC)
        user = f"Excerpts:\n\n{context}\n\nQuestion: {question}"
        key = hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()[:24]
        if key in self.cache:
            d = self.cache[key]
            self.tokens["cached_calls"] += 1
            self.last = {"cached": True}
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
            kw = dict(model=self.model, response_format={"type": "json_object"},
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            try:
                resp = self.client.chat.completions.create(temperature=0, **kw)
            except Exception as e:  # newer reasoning models only accept the default temperature
                if "temperature" not in str(e):
                    raise
                resp = self.client.chat.completions.create(**kw)
            d = {"key": key, "model": self.model, "prompt": self.prompt, "raw": resp.choices[0].message.content,
                 "prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens,
                 "latency_ms": round((time.perf_counter() - t0) * 1000)}
            with open(self.cache_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(d) + "\n")
            self.cache[key] = d
            self.tokens["api_calls"] += 1
            self.last = {"cached": False}
        self.tokens["prompt_tokens"] += d["prompt_tokens"]
        self.tokens["completion_tokens"] += d["completion_tokens"]
        self.last.update(prompt_tokens=d["prompt_tokens"], completion_tokens=d["completion_tokens"],
                         latency_ms=d.get("latency_ms"), cost_usd=self.call_cost(d["prompt_tokens"], d["completion_tokens"]))
        try:
            out = json.loads(d["raw"])
        except json.JSONDecodeError:
            out = {"error": "bad_json", "answer_text": d["raw"]}
        return out

    def call_cost(self, p: int, c: int) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return (p * self.price_in + c * self.price_out) / 1e6

    def cost(self) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return (self.tokens["prompt_tokens"] * self.price_in + self.tokens["completion_tokens"] * self.price_out) / 1e6


def load_preset(name: str) -> dict:
    import yaml
    path = ROOT / "configs" / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"no preset {path}")
    return yaml.safe_load(path.read_text())


def apply_preset(a, p: dict) -> None:
    """Preset values win over command-line flags for everything that defines the system under test."""
    a.index, a.top_k, a.method = p["index"]["dir"], p["retrieval"]["top_k"], p["retrieval"]["method"]
    a.multi, a.parent = bool(p["retrieval"]["multi"]), bool(p["retrieval"].get("parent_text", False))
    a.model, a.prompt = p["reader"]["model"], p["reader"]["prompt"]
    a.spec = p["reader"].get("spec", "v1")
    a.narrative_long = bool(p["reader"].get("narrative_long", False)) or getattr(a, "narrative_long", False)
    prices = p.get("prices_usd_per_1m") or {}
    a.price_in = a.price_in if a.price_in is not None else prices.get("input")
    a.price_out = a.price_out if a.price_out is not None else prices.get("output")
    meta = json.loads((ROOT / a.index / "meta.json").read_text())
    want = p["index"].get("index_version")
    if want and meta["index_version"] != want:
        raise SystemExit(f"preset {p['name']} expects index_version {want}, {a.index} has {meta['index_version']}")


def pctl(xs: list, q: float):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))]


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
    if ans.get("decision") in ("answer", "abstain"):
        b["decision"] = ans["decision"]
    vals = [v for v in ans.get("values") or [] if isinstance(v, dict) and isinstance(v.get("value"), (int, float))]
    if vals:
        b["values"] = [{"label": v.get("label") or "", "value": float(v["value"]), "unit": v.get("unit"),
                        "value_text": v.get("value_text")} for v in vals]
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
    ap.add_argument("--multi", action="store_true",
                    help="multi-target questions use retrieve_multi (contract v1.2): one search per company / filing")
    ap.add_argument("--dry-run", action="store_true", help="retrieve and build prompts, no API calls")
    ap.add_argument("--narrative-variant", default=None, choices=["rrf", "union", "neighbors", "union+neighbors"],
                    help="dev experiments only: retrieval variant (rag/narrative.py) for narrative / categorical / "
                         "false-premise questions, chosen by the Gold answer_type; other questions unchanged")
    ap.add_argument("--spec", choices=sorted(SPECS), default="v1",
                    help="output spec: v1 = final_v1's; v2 = answered only false when nothing answers + values list")
    ap.add_argument("--narrative-long", action="store_true",
                    help="dev experiments only: narrative / categorical / false-premise questions may answer in up to 5 "
                         "sentences covering every reason or component (JSON_SPEC_LONG); number questions unchanged")
    ap.add_argument("--preset", default=None, help="configs/<name>.yaml, e.g. final_v1 (overrides the flags above)")
    ap.add_argument("--out", default="eval/results/round1/reader")
    a = ap.parse_args()

    preset = load_preset(a.preset) if a.preset else None
    if preset:
        apply_preset(a, preset)
        print(f"preset {preset['name']}: {a.model} prompt {a.prompt}, {a.method} top {a.top_k}, multi={a.multi}, index {a.index}")
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

    # a preset plus an experiment is no longer the preset: label it as a dev experiment
    from_preset = bool(preset) and preset["reader"].get("narrative_long", False) == a.narrative_long
    tag = ("dev_" if (a.narrative_variant or (a.narrative_long and not from_preset) or (a.spec != "v1" and not preset)) else f"{a.preset}_" if a.preset else "") + f"{model}_{a.prompt}_k{a.top_k}" + ("_parent" if a.parent else "") + ("_multi" if a.multi else "") \
        + (f"_narr-{a.narrative_variant.replace('+', '-')}" if a.narrative_variant else "") \
        + ("_narr-long" if a.narrative_long else "") + (f"_spec{a.spec}" if a.spec != "v1" else "")
    base = ROOT / a.out
    out = base / tag
    out.mkdir(parents=True, exist_ok=True)
    reader = Reader(model, a.prompt, base / "cache.jsonl", p_in, p_out, a.dry_run)
    retr = Retriever(ROOT / a.index, log_dir=None)
    narr = None
    if a.narrative_variant:
        from rag.narrative import NarrativeSearch
        narr = NarrativeSearch(retr)

    rows, blocks = [], []
    for i, q in enumerate(gold, 1):
        g = group(q)
        trace_id = f"round1-reader-{q['qid']}"
        t_ret = time.perf_counter()
        if narr and g in ("narrative", "categorical", "false_premise") and len(split_filters(q.get("filters"))) == 1:
            env = narr.search(q["question"], q.get("filters") or None, top_k=a.top_k, variant=a.narrative_variant,
                              trace_id=trace_id)
        elif a.multi and len(split_filters(q.get("filters"))) > 1:
            env = multi_search(lambda qq, f, k, trace_id=None: retr.search(qq, filters=f, top_k=k, method=a.method,
                                                                            trace_id=trace_id),
                               q["question"], q.get("filters"), top_k=a.top_k, trace_id=trace_id)
        else:
            env = retr.search(q["question"], filters=q.get("filters") or None, top_k=a.top_k, method=a.method,
                              trace_id=trace_id)
        retrieval_ms = round((time.perf_counter() - t_ret) * 1000, 1)
        res = env["results"]
        reader.last = {}
        base_spec = SPECS[a.spec]
        spec = long_spec(base_spec) if (a.narrative_long and g in ("narrative", "categorical", "false_premise")) else base_spec
        ans = reader(q["question"], fmt_context(res, a.parent), spec) if res else \
            {"answered": False, "answer_text": "No evidence was retrieved.", "value": None, "cites": []}
        block = to_block(q, ans, res, trace_id)
        row = {"qid": q["qid"], "group": g, "type": q["type"], "tickers": "|".join(q["tickers"]),
               "question": q["question"], "gold": q["answer"].get("display"),
               "evidence_status": env.get("evidence_status"), "weak_reasons": "|".join(env.get("weak_reasons") or []),
               "n_results": len(res), "multi": "subqueries" in env, "answered": block["answered"], "answer_text": block["answer_text"],
               "value_text": block.get("value_text"), "period_end": block.get("period_end"),
               "cited_chunks": "|".join(c["id"] for c in block["citations"]),
               "retrieval_ms": retrieval_ms, "n_subqueries": len(env.get("subqueries") or []) or 1,
               "reader_prompt_tokens": reader.last.get("prompt_tokens", 0),
               "reader_completion_tokens": reader.last.get("completion_tokens", 0),
               "reader_latency_ms": reader.last.get("latency_ms"), "reader_cached": reader.last.get("cached"),
               "cost_usd": reader.last.get("cost_usd")}
        if not ans.get("_dry"):
            row.update(grade(q, g, block))
        if g in ("number", "ntap_10q_excluded") and retrieval_kind(q) in ("number", "ntap_10q_excluded"):
            k = max(len(res), 1)
            row["retrieved_all_figures"] = retrieval_score(q, res, ks=(k,)).get(f"strict@{k}")
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
        "multi": a.multi, "index": a.index, "gold": a.gold, "n_questions": len(rows), "groups": {k: len(v) for k, v in by.items() if v},
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
        "per_question": {
            "n": len(rows),
            "prompt_tokens_mean": sum(r["reader_prompt_tokens"] for r in rows) / max(len(rows), 1),
            "completion_tokens_mean": sum(r["reader_completion_tokens"] for r in rows) / max(len(rows), 1),
            "cost_usd_mean": (reader.cost() / len(rows)) if reader.cost() is not None and rows else None,
            "cost_usd_per_1000": (reader.cost() / len(rows) * 1000) if reader.cost() is not None and rows else None,
            "reader_latency_ms_p50": pctl([r["reader_latency_ms"] for r in rows], 0.5),
            "reader_latency_ms_p95": pctl([r["reader_latency_ms"] for r in rows], 0.95),
            "retrieval_ms_p50": pctl([r["retrieval_ms"] for r in rows], 0.5),
            "retrieval_ms_p95": pctl([r["retrieval_ms"] for r in rows], 0.95),
            "end_to_end_ms_p50": pctl([r["retrieval_ms"] + (r["reader_latency_ms"] or 0) for r in rows], 0.5),
            "end_to_end_ms_p95": pctl([r["retrieval_ms"] + (r["reader_latency_ms"] or 0) for r in rows], 0.95),
        },
        "preset": a.preset, "narrative_variant": a.narrative_variant, "narrative_long": a.narrative_long, "spec": a.spec,
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
          f"Tokens: {summary['tokens']}; cost: " + ("n/a (set prices in config.yaml)" if summary["cost_usd"] is None else f"${summary['cost_usd']:.3f}"),
          "Per question: {prompt_tokens_mean:,.0f} input / {completion_tokens_mean:,.0f} output tokens; "
          "reader p50 {reader_latency_ms_p50} ms, p95 {reader_latency_ms_p95} ms; "
          "retrieval p50 {retrieval_ms_p50} ms, p95 {retrieval_ms_p95} ms".format(**summary["per_question"]), "",
          "## Wrong number answers", "", "| qid | source | label | answer | gold |", "|---|---|---|---|---|"]
    md += [f"| {r['qid']} | {r.get('error_source') or ''} | {r['label']} | {(r.get('value_text') or r['answer_text'])[:60]} | {r['gold']} |"
           for r in miss]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:18]))
    print(f"\nWrote {out}/summary.md, summary.json, per_question.csv, answer_blocks.jsonl")


if __name__ == "__main__":
    main()
