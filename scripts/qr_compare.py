"""Query rewriting vs Agent extraction (exploratory). Step 3 of 3: compare the filter arms.

    python scripts/qr_compare.py

Reads eval/results/query_rewrite/<arm>/*/per_question.csv and summary.json for every arm that has run, plus the
extraction files from step 1, and writes eval/results/query_rewrite/comparison.md and comparison.json:
  - numeric accuracy (NAA, Eval's grader as vendored) with a Wilson 95% interval, overall and per perturbation
  - errors by source (retrieval vs reading), false refusals, unanswerable declined, balanced RAA
  - filter quality: company resolved to the gold ticker(s); gold filing kept by the filters
  - extraction cost and latency (step 1) and reader cost per 1,000 questions
  - paired McNemar (exact) on number questions between the arms
These are our own scores (preliminary); Eval scores the arms officially.
"""
from __future__ import annotations

import csv, json, math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "eval/results/query_rewrite"
SUITE = ROOT / "eval/suites/messy_wording_v1.jsonl"
MANIFEST = ROOT / "data/round1/index_C1/chunks.jsonl"
ARMS = ["none", "precheck", "rag_llm", "agents", "agents_precheck", "gold"]
LABEL = {"none": "No filters", "precheck": "Pre-check, rules only", "rag_llm": "A: RAG-side LLM + pre-check",
         "agents": "B: Agents' LLM extractor (d89208c)",
         "agents_precheck": "B + pre-check (post-hoc)", "gold": "Gold filters (upper bound)"}


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def pctl(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


def as_list(x):
    if x is None or x == "":
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def load_arm(arm):
    d = BASE / arm
    if not d.exists():
        return None
    runs = [p for p in d.iterdir() if p.is_dir() and (p / "per_question.csv").exists()]
    if not runs:
        return None
    run = max(runs, key=lambda p: p.stat().st_mtime)
    rows = list(csv.DictReader(open(run / "per_question.csv", encoding="utf-8")))
    return {"dir": run, "rows": {r["qid"]: r for r in rows}, "summary": json.load(open(run / "summary.json"))}


def main():
    suite = {q["qid"]: q for q in (json.loads(l) for l in open(SUITE, encoding="utf-8"))}
    filings = {}
    for line in open(MANIFEST, encoding="utf-8"):
        c = json.loads(line)
        acc = c.get("accession") or c.get("accession_number")
        if acc and acc not in filings:
            filings[acc] = {"ticker": c.get("ticker"), "form": c.get("form"),
                            "fiscal_year": c.get("fiscal_year"), "fiscal_period": c.get("fiscal_period"),
                            "accession_number": acc, "accession": acc}

    def gold_accessions(q):
        accs = set()
        for e in q.get("rag_evidence") or []:
            if isinstance(e, dict) and e.get("accession"):
                accs.add(e["accession"])
        return accs

    def keeps(filters, acc):
        f = filings.get(acc)
        if f is None:
            return None
        for k, v in (filters or {}).items():
            vals = [str(x) for x in as_list(v)]
            if str(f.get(k)) not in vals:
                return False
        return True

    data = {arm: load_arm(arm) for arm in ARMS}
    data = {k: v for k, v in data.items() if v}
    if not data:
        raise SystemExit("no arm has run yet (scripts/qr_run_arm.py)")
    extract = {}
    for arm in ("rag_llm", "agents", "agents_precheck"):
        p = BASE / f"filters_{arm}.jsonl"
        if p.exists():
            extract[arm] = {r["qid"]: r for r in (json.loads(l) for l in open(p, encoding="utf-8"))}

    out = {}
    for arm, d in data.items():
        rows = d["rows"]
        nums = [r for r in rows.values() if r["group"] == "number"]
        k = sum(r["passed"] == "True" for r in nums)
        by_pert = {}
        for pert in ("typo_company", "typo_terms", "casual"):
            sel = [r for r in nums if suite.get(r["qid"], {}).get("perturbation") == pert]
            kk = sum(r["passed"] == "True" for r in sel)
            by_pert[pert] = {"k": kk, "n": len(sel), "naa": round(kk / len(sel), 3) if sel else None}
        miss = [r for r in nums if r["passed"] != "True"]
        refus = [r for r in rows.values() if r["group"] == "refusal"]
        # filter quality on answerable questions
        comp_ok = comp_n = keep_ok = keep_n = 0
        for qid, r in rows.items():
            q = suite.get(qid) or {}
            if not q.get("answerable", True):
                continue
            used = json.loads(r["filters_used"]) if r.get("filters_used") else None
            gold_t = sorted(set(q.get("tickers") or []))
            if gold_t:
                comp_n += 1
                got = sorted(set(as_list((used or {}).get("ticker"))))
                comp_ok += got == gold_t
            for acc in gold_accessions(q):
                kp = keeps(used, acc) if not (r.get("precheck_status") in ("none", "unresolved")) else False
                if kp is not None:
                    keep_n += 1
                    keep_ok += bool(kp)
        s = d["summary"]
        ex = extract.get(arm, {})
        ex_rows = [ex[qid] for qid in rows if qid in ex]
        ex_cost = [r["cost_usd"] for r in ex_rows if r.get("cost_usd") is not None]
        out[arm] = {
            "label": LABEL[arm], "run": str(d["dir"].relative_to(ROOT)), "n_questions": len(rows),
            "naa": {"k": k, "n": len(nums), "rate": round(k / len(nums), 3) if nums else None, "ci95": wilson(k, len(nums))},
            "naa_by_perturbation": by_pert,
            "errors_by_source": dict(Counter(r.get("error_source") or "unknown" for r in miss)),
            "wrong_by_label": dict(Counter(r["label"] for r in miss)),
            "unanswerable_declined": f"{sum(r['passed'] == 'True' for r in refus)}/{len(refus)}",
            "balanced_raa": (s.get("raa") or {}).get("balanced_raa"),
            "declined_by_precheck": sum(r.get("precheck_status") in ("none", "unresolved") for r in rows.values()),
            "company_exact": f"{comp_ok}/{comp_n}" if arm != "none" else "-",
            "gold_filing_kept": f"{keep_ok}/{keep_n}",
            "extraction": None if not ex_rows else {
                "mode": dict(Counter(r.get("mode") for r in ex_rows)),
                "usd_per_1000": round(sum(ex_cost) / len(ex_cost) * 1000, 4) if ex_cost else None,
                "latency_ms_p50": pctl([r.get("latency_ms") for r in ex_rows], 0.5),
                "latency_ms_p95": pctl([r.get("latency_ms") for r in ex_rows], 0.95)},
            "reader_usd_per_1000": round((s.get("per_question") or {}).get("cost_usd_per_1000") or 0, 3),
        }

    pairs = {}
    arms = list(data)
    for i, x in enumerate(arms):
        for y in arms[i + 1:]:
            b = c = 0
            for qid, r in data[x]["rows"].items():
                if r["group"] != "number" or qid not in data[y]["rows"]:
                    continue
                px, py = r["passed"] == "True", data[y]["rows"][qid]["passed"] == "True"
                b += px and not py
                c += py and not px
            pairs[f"{x} vs {y}"] = {f"{x}_only": b, f"{y}_only": c, "p_exact": round(mcnemar_exact(b, c), 4)}

    json.dump({"arms": out, "mcnemar_numbers": pairs}, open(BASE / "comparison.json", "w"), indent=1)
    f3 = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
    md = ["# Query rewriting vs Agent extraction (messy_wording_v1, 427 questions; exploratory)", "",
          "Same reader for every arm: final_v1 (gpt-6.1-terra, top 15, multi) on Chroma 7a7ad9801f86 (fixed index). "
          "Only the source of the retrieval filters changes. Extraction model: gpt-6-luna for both LLM arms. "
          "Our own grader; Eval scores officially. The post-hoc arm was designed after seeing the other arms on this "
          "suite: it shows the fix works here, it is not independent evidence.", "",
          "| arm | NAA (numbers) | 95% CI | typo_company | typo_terms | casual | errors: retrieval / reading | "
          "declined unanswerable | company exact | gold filing kept | extraction $/1k | extraction p50 / p95 ms |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        if arm not in out:
            continue
        o = out[arm]
        e = o["extraction"] or {}
        bp = o["naa_by_perturbation"]
        md.append(f"| {o['label']} | **{f3(o['naa']['rate'])}** ({o['naa']['k']}/{o['naa']['n']}) | "
                  f"{o['naa']['ci95'][0]}-{o['naa']['ci95'][1]} | " + " | ".join(
                      f"{f3(bp[p]['naa'])} ({bp[p]['k']}/{bp[p]['n']})" for p in ("typo_company", "typo_terms", "casual"))
                  + f" | {o['errors_by_source'].get('retrieval', 0)} / {o['errors_by_source'].get('reading', 0)} | "
                  f"{o['unanswerable_declined']} | {o['company_exact']} | {o['gold_filing_kept']} | "
                  f"{e.get('usd_per_1000', '-') if e else '-'} | "
                  f"{(str(e.get('latency_ms_p50')) + ' / ' + str(e.get('latency_ms_p95'))) if e else '-'} |")
    md += ["", "Extraction mode (LLM vs rule-based fallback): " + "; ".join(
        f"{a}: {out[a]['extraction']['mode']}" for a in out if out[a]["extraction"]), "",
        "Wrong number answers by label: " + "; ".join(f"{a}: {out[a]['wrong_by_label']}" for a in out), "",
        "## Paired comparison on number questions (exact McNemar)", "", "| pair | only first right | only second right | p |",
        "|---|---|---|---|"]
    for k_, v in pairs.items():
        x, y = k_.split(" vs ")
        md.append(f"| {k_} | {v[x + '_only']} | {v[y + '_only']} | {v['p_exact']} |")
    (BASE / "comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {BASE / 'comparison.md'} and comparison.json")


if __name__ == "__main__":
    main()
