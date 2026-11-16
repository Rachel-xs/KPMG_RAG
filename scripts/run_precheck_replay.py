"""Replay the deterministic pre-check (rag/coverage.py) over the Gold Set and a misspelled-name stress test.

    python scripts/run_precheck_replay.py                       # Gold v2.1, manifest = Round 1 index chunks
    python scripts/run_precheck_replay.py --manifest eval/round1_filings.csv

Two ways to build the request for every question:
  gold_filters   the Gold Set's own filters (what an Agent with a perfect extractor would pass)
  text           extract_request() on the question text (rules only, no LLM): companies, dates, FY, quarter, form
What we want to see:
  * answerable questions: the pre-check never says "none" / "unresolved" (that would refuse an answerable question)
  * unanswerable questions: how many it already catches (missing company or period), before any retrieval call
  * questions RAG cannot serve today (NTAP 10-Q, excluded): caught as a miss
  * typos: company names with one edit still resolve (Eval: 98% -> 19% without approximate matching)
No model or API calls; runs in a second.
"""
from __future__ import annotations

import argparse, json, random, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.coverage import CoverageIndex, extract_request  # noqa: E402

BLOCKING = {"none", "unresolved"}


def request_from_filters(f: dict | None) -> dict:
    f = f or {}
    return {"tickers": f.get("ticker"), "forms": f.get("form"), "fiscal_years": f.get("fiscal_year"),
            "fiscal_periods": f.get("fiscal_period")}


def typo(word: str, rng: random.Random) -> str:
    """One random edit: swap two adjacent letters, drop one, or double one (never the first letter)."""
    i = rng.randrange(1, len(word) - 1)
    op = rng.choice(["swap", "drop", "double"])
    if op == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if op == "drop":
        return word[:i] + word[i + 1:]
    return word[:i] + word[i] + word[i:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--manifest", default="data/round1/index_C1/chunks.jsonl",
                    help="index chunks.jsonl or a filings CSV")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="eval/results/precheck")
    a = ap.parse_args()

    m = ROOT / a.manifest
    idx = CoverageIndex.from_csv(m) if m.suffix == ".csv" else CoverageIndex.from_chunks(m)
    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for q in gold:
        unans = not q.get("answerable", True)
        excluded = q.get("snapshot_status") == "review_required"
        accs = {e.get("accession") for e in (q.get("gold") or {}).get("evidence") or [] if e.get("accession")}
        in_corpus = not accs or accs <= {f.accession for f in idx.filings}
        r_f = idx.check(**request_from_filters(q.get("filters")))
        req = extract_request(q["question"], idx)
        r_t = idx.check(**req, combine="independent")
        rows.append({"qid": q["qid"], "answer_type": q["answer_type"], "route": q.get("route_expected"),
                     "unanswerable": unans, "ntap_excluded": excluded, "evidence_in_corpus": in_corpus, "gold_tickers": "|".join(q.get("tickers") or []),
                     "status_filters": r_f["status"], "status_text": r_t["status"],
                     "text_companies": "|".join(req["companies"] or []),
                     "text_tickers": "|".join(sorted({e["ticker"] for e in r_t["entities"] if e["ticker"]})),
                     "text_periods": json.dumps({k: v for k, v in req.items() if k != "companies" and v}),
                     "message_text": r_t["message"], "question": q["question"]})

    def tally(key, sel):
        return dict(Counter(r[key] for r in rows if sel(r)))

    # answerable from the corpus we have: not unanswerable, and every gold evidence filing is indexed
    answerable = lambda r: not r["unanswerable"] and not r["ntap_excluded"] and r["evidence_in_corpus"]  # noqa: E731
    missing_filing = lambda r: not r["unanswerable"] and (r["ntap_excluded"] or not r["evidence_in_corpus"])  # noqa: E731
    false_block = [r for r in rows if answerable(r) and r["status_text"] in BLOCKING]
    ticker_ok = [r for r in rows if r["gold_tickers"] and set(r["gold_tickers"].split("|")) <= set(r["text_tickers"].split("|"))]
    with_tk = [r for r in rows if r["gold_tickers"]]

    # ---- typo stress test: misspell the company name in every question that names one ----
    rng = random.Random(a.seed)
    names = sorted({a_ for a_ in idx.aliases if len(a_) >= 5 and not a_.isupper()}, key=len, reverse=True)
    stress = []
    for q in gold:
        text = q["question"]
        for n in names:
            mt = re.search(re.escape(n), text, re.I)
            if mt:
                w = mt.group(0)
                bad = typo(w, rng)
                qt = text[:mt.start()] + bad + text[mt.end():]
                req = extract_request(qt, idx)
                got = {e["ticker"] for e in idx.check(**req, combine="independent")["entities"] if e["ticker"]}
                exact_only = {idx.aliases.get(c.lower()) or (c if c in idx.by_ticker else None)
                              for c in (req["companies"] or [])}
                want = idx.resolve(w)["ticker"]
                stress.append({"qid": q["qid"], "original": w, "typo": bad, "want": want,
                               "resolved_fuzzy": want in got, "resolved_exact_only": want in exact_only})
                break
    n_s = len(stress)

    summary = {
        "manifest": idx.source, "n_filings": len(idx.filings), "n_questions": len(rows),
        "gold_filters": {
            "answerable": tally("status_filters", answerable),
            "unanswerable": tally("status_filters", lambda r: r["unanswerable"]),
            "evidence_filing_not_indexed": tally("status_filters", missing_filing),
        },
        "text_extraction": {
            "answerable": tally("status_text", answerable),
            "unanswerable": tally("status_text", lambda r: r["unanswerable"]),
            "evidence_filing_not_indexed": tally("status_text", missing_filing),
            "false_blocks": [r["qid"] for r in false_block],
            "company_recall": f"{len(ticker_ok)}/{len(with_tk)}",
            "unanswerable_caught": [r["qid"] for r in rows if r["unanswerable"] and r["status_text"] in BLOCKING | {"partial"}],
        },
        "typo_stress": {"n": n_s, "resolved_with_fuzzy": sum(s["resolved_fuzzy"] for s in stress),
                        "resolved_exact_only": sum(s["resolved_exact_only"] for s in stress)},
    }
    import csv
    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(out / "typo_stress.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(stress[0]))
        w.writeheader()
        w.writerows(stress)
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
