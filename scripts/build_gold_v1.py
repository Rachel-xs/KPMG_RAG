"""Build eval/gold_v1.jsonl (RAG-side evidence anchors for Eval's Gold Set v1, 100 questions).

Inputs
- eval/gold_v1_questions.json : Eval's 100 questions (exported from "Gold Set v1: 100 benchmark questions").
- eval/gold_v0_msft.jsonl     : RAG Gold v0; its 30 questions keep their v0 anchors unchanged.
- ANCHORS below               : anchors for Eval's 70 new questions. Each evidence item = one filing + strings that
                                must all appear in ONE retrieved chunk. Numbers are written as the filing prints them
                                (e.g. "(84,669)" -> "84,669"), so anchors survive re-chunking.

Every anchor is checked against a chunks file; anchors not found are reported, never silently kept.
Status is "draft" for all rows: Eval should review before anything is reported as final.

    python scripts/build_gold_v1.py --chunks data/chunks_A/chunks.jsonl --check data/index_C1/chunks.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILINGS = {  # key -> (ticker, form, accession, fiscal_year, fiscal_period)
    "MSFT_Q": ("MSFT", "10-Q", "0001193125-26-191507", 2026, "Q3"),
    "MSFT_K": ("MSFT", "10-K", "0001193125-26-323660", 2026, "FY"),
    "AAPL_Q": ("AAPL", "10-Q", "0000320193-26-000013", 2026, "Q2"),
    "NVDA_Q": ("NVDA", "10-Q", "0001045810-26-000052", 2027, "Q1"),
}
NOT_IN_CORPUS = {  # filings Gold v1 needs that the current snapshot does not have
    "AMZN": "AMZN 10-Q for the quarter ended 2026-03-31 (snapshot has only 2026-06-30)",
    "META": "META 10-Q for the quarter ended 2026-03-31 (snapshot has only 2026-06-30)",
}

Q = "MSFT_Q"
ANCHORS: dict[str, list[tuple[str, list[str]]]] = {
    # Extraction (single fact)
    "EV1-001": [(Q, ["38,398"])], "EV1-002": [(Q, ["114,634"])], "EV1-003": [(Q, ["97,983"])],
    "EV1-004": [(Q, ["4.27"])], "EV1-005": [(Q, ["56,058"])], "EV1-006": [(Q, ["8,915"])],
    "EV1-007": [(Q, ["30,876"])], "EV1-008": [(Q, ["694,228"])], "EV1-009": [(Q, ["32,105"])],
    "EV1-010": [(Q, ["414,367"])], "EV1-011": [(Q, ["31,423"])], "EV1-012": [(Q, ["50,924"])],
    "EV1-013": [(Q, ["84,669"])], "EV1-014": [(Q, ["17,692"])], "EV1-015": [(Q, ["0.91"])],
    "EV1-016": [(Q, ["effective tax rate was 19%"])],
    # Segment and disaggregated revenue
    "EV1-017": [(Q, ["34,681"])], "EV1-018": [(Q, ["20,973"])], "EV1-019": [(Q, ["13,192"])],
    "EV1-020": [(Q, ["5,341"])], "EV1-021": [(Q, ["14,628"])], "EV1-022": [(Q, ["32,592"])],
    "EV1-023": [(Q, ["42,336"])],
    # Comparison
    "EV1-024": [(Q, ["20,973"]), (Q, ["13,753"]), (Q, ["3,672"])],
    "EV1-025": [(Q, ["41,198"])],
    # Calculation (one item per input number; pairs only where both sit on the same table row)
    "EV1-026": [(Q, ["38,398"]), (Q, ["82,886"])],
    "EV1-027": [(Q, ["38,398", "32,000"]), (Q, ["82,886", "70,066"])],
    "EV1-028": [(Q, ["56,058", "48,147"]), (Q, ["82,886", "70,066"])],
    "EV1-029": [(Q, ["31,778", "25,824"])],
    "EV1-030": [(Q, ["241,832", "205,283"])],
    "EV1-031": [(Q, ["30,876"]), (Q, ["82,886"])],
    "EV1-032": [(Q, ["7,562"]), (Q, ["39,340"]), (Q, ["effective tax rate was 19%"])],
    "EV1-033": [(Q, ["41,017"]), (Q, ["98,485"])],
    "EV1-034": [(Q, ["175,329"]), (Q, ["136,661"])],
    "EV1-035": [(Q, ["19,687"]), (Q, ["17,692"])],
    "EV1-036": [(Q, ["54.5 billion"]), (Q, ["82,886"])],
    # Derived periods (Q4 = 10-K full year minus 10-Q nine months)
    "EV1-037": [("MSFT_K", ["331,839"]), (Q, ["241,832"])],
    "EV1-038": [("MSFT_K", ["155,237"]), (Q, ["114,634"])],
    "EV1-039": [("MSFT_K", ["133,749"]), (Q, ["97,983"])],
    # Reconciliation
    "EV1-040": [(Q, ["20,973"]), (Q, ["13,753"]), (Q, ["3,672"]), (Q, ["38,398"])],
    "EV1-041": [(Q, ["56,058"]), (Q, ["8,915"]), (Q, ["6,814"]), (Q, ["1,931"])],
    "EV1-042": [(Q, ["93,500"]), (Q, ["97,983"])],
    "EV1-043": [(Q, ["13,192", "13,371"]), (Q, ["146 million"]), (Q, ["5,511", "6,095"])],
    # Narrative
    "EV1-044": [(Q, ["Azure and other cloud services revenue increased 40%"])],
    "EV1-045": [(Q, ["Microsoft Cloud revenue increased 29% to $54.5 billion"])],
    "EV1-046": [(Q, ["$627 billion"])],
    "EV1-047": [(Q, ["27 percent of OpenAI"])],
    "EV1-048": [(Q, ["lower rates in foreign jurisdictions"])],
    "EV1-049": [(Q, ["Sales and marketing expenses increased $602 million or 10%"])],
    # Cross-company (only filings in the snapshot; AMZN / META parts flagged below)
    "EV1-050": [("AAPL_Q", ["111,184"])],
    "EV1-053": [("NVDA_Q", ["81,615"])],
    "EV1-054": [(Q, ["82,886"]), ("AAPL_Q", ["111,184"]), ("NVDA_Q", ["81,615"])],
    "EV1-055": [(Q, ["38,398"]), (Q, ["82,886"]), ("AAPL_Q", ["111,184"]), ("NVDA_Q", ["81,615"])],
    "EV1-056": [(Q, ["31,778"]), (Q, ["38,398"])],
    "EV1-057": [(Q, ["82,886"]), ("AAPL_Q", ["111,184"]), ("NVDA_Q", ["81,615"])],
    "EV1-058": [("NVDA_Q", ["April 26, 2026"])],
    "EV1-060": [(Q, ["38,398"]), (Q, ["82,886"])],
    # False premise: the evidence that refutes the premise
    "EV1-068": [(Q, ["82,886"])],
    "EV1-069": [(Q, ["97,983"])],
}
NEEDS = {  # company names in the question -> missing filings
    qid: [k for k in NOT_IN_CORPUS if k in want]
    for qid, want in {
        "EV1-051": "AMZN", "EV1-052": "META", "EV1-054": "AMZN META", "EV1-055": "AMZN META", "EV1-056": "AMZN META",
        "EV1-057": "AMZN META", "EV1-059": "AMZN", "EV1-060": "META",
    }.items()
}
UNANSWERABLE = {"Unanswerable / out of scope", "False premise"}
COMPANY = {"Microsoft": "MSFT", "Apple": "AAPL", "NVIDIA": "NVDA", "Amazon": "AMZN", "Meta": "META", "Tesla": "TSLA"}


def item(key: str, contains: list[str]) -> dict:
    t, f, acc, _, _ = FILINGS[key]
    return {"ticker": t, "form": f, "accession": acc, "contains": contains, "anchor_source": "rag_v1_draft"}


def filters_for(anchors: list[tuple[str, list[str]]]) -> dict | None:
    keys = {k for k, _ in anchors}
    if len(keys) != 1:
        return None  # multi-filing question: the Agent should split it into one call per filing
    t, f, _, fy, fp = FILINGS[keys.pop()]
    return {"ticker": t, "form": f, "fiscal_year": fy, "fiscal_period": fp}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="eval/gold_v1_questions.json")
    ap.add_argument("--v0", default="eval/gold_v0_msft.jsonl")
    ap.add_argument("--chunks", required=True, help="chunks.jsonl to verify anchors against (Data's text)")
    ap.add_argument("--check", nargs="*", default=[], help="more chunk files whose co-occurrence is also checked")
    ap.add_argument("--out", default="eval/gold_v1.jsonl")
    a = ap.parse_args()

    qs = json.load(open(ROOT / a.questions))
    v0 = {json.loads(l)["qid"]: json.loads(l) for l in open(ROOT / a.v0) if l.strip()}
    corpora = {p: [json.loads(l) for l in open(ROOT / p)] for p in [a.chunks, *a.check]}

    def found(ev: dict, chunks: list[dict]) -> int:
        acc = ev.get("accession")
        subs = [s.lower() for s in ev.get("contains", [])]
        return sum(1 for c in chunks if (not acc or c.get("accession", c.get("accession_number")) == acc)
                   and all(s in " ".join(c["text"].split()).lower() for s in subs))

    rows, problems, stats = [], [], collections.Counter()
    for q in qs:
        qid, cat = q["id"], q["category"]
        answerable = cat not in UNANSWERABLE
        if qid in v0:
            r = dict(v0[qid])
            r["notes"] = (r.get("notes") or "") + "; v1: anchors kept from Gold v0"
        else:
            anchors = ANCHORS.get(qid, [])
            r = {"qid": qid, "tier": q.get("tier"), "question": q["question"],
                 "filters": filters_for(anchors) if anchors else None,
                 "gold": {"chunk_ids": [], "evidence": [item(k, c) for k, c in anchors]},
                 "expected": {"ticker": sorted({FILINGS[k][0] for k, _ in anchors})} if anchors else {},
                 "reference_answer": q["expected_answer"], "status": "draft",
                 "notes": "v1 anchor draft by RAG; needs Eval review"}
        r["category"] = cat
        r["source"] = q.get("source")
        r["answerable"] = answerable
        missing = NEEDS.get(qid, [])
        r["corpus_status"] = ("not_in_corpus" if missing and not r["gold"]["evidence"] else
                              "partial" if missing else "in_corpus" if r["gold"]["evidence"] else "no_evidence")
        if missing:
            r["missing_filings"] = [NOT_IN_CORPUS[m] for m in missing]
        for ev in r["gold"]["evidence"]:
            for p, chunks in corpora.items():
                n = found(ev, chunks)
                ev.setdefault("verified", {})[Path(p).parent.name] = n
                if n == 0:
                    problems.append(f"{qid}: {ev.get('contains')} not found in {p}")
        stats[r["corpus_status"]] += 1
        rows.append(r)

    with open(ROOT / a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_cat = collections.defaultdict(collections.Counter)
    for r in rows:
        by_cat[r["category"]][r["corpus_status"]] += 1
    lines = [f"# Gold v1 anchor report", "", f"{len(rows)} questions -> {a.out}. Status counts: {dict(stats)}", "",
             "| category | in_corpus | partial | not_in_corpus | no_evidence |", "|---|---|---|---|---|"]
    for cat, c in by_cat.items():
        lines.append(f"| {cat} | {c['in_corpus']} | {c['partial']} | {c['not_in_corpus']} | {c['no_evidence']} |")
    lines += ["", "## Missing filings", ""] + [f"- {v}" for v in NOT_IN_CORPUS.values()]
    lines += ["", f"## Anchors not found ({len(problems)})", ""] + ([f"- {p}" for p in problems] or ["- none"])
    (ROOT / a.out).with_name("gold_v1_anchor_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
