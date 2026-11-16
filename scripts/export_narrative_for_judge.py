"""#6 step 2: package RAG's narrative answers for Eval's LLM judge, plus a hand-scoring sheet for calibration.

    python scripts/export_narrative_for_judge.py \
        --run eval/results/round1/reader/gpt-6.1-terra_v2_k15_multi        # the final_v1 settings

Writes eval/results/narrative/
  judge_input.jsonl   one line per narrative / categorical / false-premise question: question, gold answer and
                      required points, RAG's answer, and the FULL text of every chunk it cited (the judge checks
                      faithfulness claim by claim against these)
  hand_score.csv      a fixed random sample (default 20) to score by hand with the same two criteria, so Eval can
                      report judge-vs-human agreement:
                        faithfulness 0/1/2  (2 = every claim supported by the cited chunks, 0 = a claim contradicts them
                                             or is unsupported)
                        points_covered      how many of the gold required points the answer states
No API calls.
"""
from __future__ import annotations

import argparse, csv, json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GROUPS = ("narrative", "categorical", "false_premise")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="eval/results/round1/reader/gpt-6.1-terra_v2_k15_multi")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2_1.jsonl")
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1112)
    ap.add_argument("--out", default="eval/results/narrative")
    a = ap.parse_args()

    run = ROOT / a.run
    gold = {json.loads(l)["qid"]: json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")}
    rows = {r["qid"]: r for r in csv.DictReader(open(run / "per_question.csv", encoding="utf-8"))}
    blocks = {json.loads(l)["qid"]: json.loads(l) for l in open(run / "answer_blocks.jsonl", encoding="utf-8")}
    want = {q for q, r in rows.items() if r["group"] in GROUPS}
    cited = {c["id"] for q in want for c in blocks[q]["citations"]}
    text = {}
    for line in open(ROOT / a.index / "chunks.jsonl", encoding="utf-8"):
        c = json.loads(line)
        if c["chunk_id"] in cited:
            text[c["chunk_id"]] = {"chunk_id": c["chunk_id"], "ticker": c.get("ticker"), "form": c.get("form"),
                                   "accession": c.get("accession_number") or c.get("accession"),
                                   "section": c.get("section"), "section_title": c.get("section_title"),
                                   "table_name": c.get("table_name"), "text": c["text"]}

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    recs = []
    for qid in sorted(want):
        q, r, b = gold[qid], rows[qid], blocks[qid]
        ans = q.get("answer") or {}
        recs.append({"qid": qid, "group": r["group"], "type": q.get("type"), "tickers": q.get("tickers"),
                     "question": q["question"], "gold_answer": ans.get("display") or ans.get("text"),
                     "required_points": ans.get("required_points") or [],
                     "rag_answered": b["answered"], "rag_answer": b["answer_text"],
                     "evidence_status": r.get("evidence_status"),
                     "cited_chunks": [text[c["id"]] for c in b["citations"] if c["id"] in text],
                     "run": a.run, "trace_id": b["trace_id"]})
    with open(out / "judge_input.jsonl", "w", encoding="utf-8") as fh:
        for x in recs:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")

    rng = random.Random(a.seed)
    narr = [x for x in recs if x["group"] == "narrative"]
    sample = sorted(rng.sample(narr, min(a.sample, len(narr))), key=lambda x: x["qid"])
    with open(out / "hand_score.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "question", "required_points", "rag_answer", "n_cited_chunks",
                    "faithfulness_0_1_2", "points_covered", "n_points", "scorer", "notes"])
        for x in sample:
            w.writerow([x["qid"], x["question"], " || ".join(x["required_points"]), x["rag_answer"],
                        len(x["cited_chunks"]), "", "", len(x["required_points"]), "", ""])
    n_nocite = sum(1 for x in recs if x["rag_answered"] and not x["cited_chunks"])
    print(f"{len(recs)} questions ({', '.join(f'{g} {sum(x['group'] == g for x in recs)}' for g in GROUPS)}); "
          f"{len(cited)} cited chunks; answered without a citation: {n_nocite}; hand-score sample {len(sample)}")
    print(f"Wrote {out}/judge_input.jsonl and hand_score.csv")


if __name__ == "__main__":
    main()
