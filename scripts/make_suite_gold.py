"""Turn Eval's two extra suites into question files the reader runner reads (pre-registration sets D and E).

    python scripts/make_suite_gold.py --eval-dir ../kpmg-eval
        -> eval/suites/messy_wording_v1.jsonl   (427: each rewrite = its clean Gold v2.2 record, messy question, qid = vid)
        -> eval/suites/abstention_suite_v1.jsonl (56: qid = sid; 51 refusals, 5 false premises)

Then, once each (final_v1 on Chroma; see docs/preregistration_objective_eval.md):

    python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold eval/suites/messy_wording_v1.jsonl --filters none --out eval/results/suites
    python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold eval/suites/messy_wording_v1.jsonl --filters precheck --out eval/results/suites
    python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold eval/suites/messy_wording_v1.jsonl --out eval/results/suites
    python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold eval/suites/abstention_suite_v1.jsonl --filters none --out eval/results/suites
    python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold eval/suites/abstention_suite_v1.jsonl --filters precheck --out eval/results/suites

Each answer_blocks.jsonl carries "vid" / "sid", the keys Eval's Week 9/scripts/grade_suite_answers.py reads. The
reader's own summary for these runs is only a sanity check: Eval scores them. Nothing here reads the answers.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def messy(eval_dir: Path) -> list[dict]:
    data = eval_dir / "Week 8" / "data"
    gold = {q["qid"]: q for q in map(json.loads, open(data / "benchmark_v2_2.jsonl", encoding="utf-8"))}
    out = []
    for v in map(json.loads, open(data / "messy_wording_v1.jsonl", encoding="utf-8")):
        g = gold[v["qid"]]
        assert g["question"].strip() == v["clean"].strip(), f"{v['vid']}: clean text differs from Gold v2.2"
        out.append({**g, "qid": v["vid"], "vid": v["vid"], "clean_qid": v["qid"], "perturbation": v["perturbation"],
                    "question": v["messy"], "source": "messy_wording_v1"})
    return out


def abstention(eval_dir: Path) -> list[dict]:
    out = []
    for it in map(json.loads, open(eval_dir / "Week 8" / "data" / "abstention_suite_v1.jsonl", encoding="utf-8")):
        out.append({"qid": it["sid"], "sid": it["sid"], "source": "abstention_suite_v1", "type": it["kind"], "tier": "",
                    "question": it["question"], "answerable": it["answerable"], "tickers": [], "filters": None,
                    "answer_type": "false_premise" if it["answerable"] else "refusal",
                    "answer": {"display": it["expected"], "required_points": []},
                    "twin_of": it.get("twin_of") or "", "kind": it["kind"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", default="../kpmg-eval", help="local clone of thomassong0604-oss/kpmg-eval")
    ap.add_argument("--out", default="eval/suites")
    a = ap.parse_args()
    eval_dir = (ROOT / a.eval_dir).resolve()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    for name, items in (("messy_wording_v1", messy(eval_dir)), ("abstention_suite_v1", abstention(eval_dir))):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            for it in items:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
        print(f"{name}: {len(items)} items -> {out / name}.jsonl")


if __name__ == "__main__":
    main()
