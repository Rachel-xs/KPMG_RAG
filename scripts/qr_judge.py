"""Eval's ask (d), 11/23: run Eval's narrative judge on the narrative rewrites of two query-rewrite arms.

    python scripts/qr_judge.py --dry-run      # writes inputs, builds judge prompts, no API calls
    python scripts/qr_judge.py                # real run (judge model gpt-6-sol via run_eval_judge.py)
    python scripts/qr_judge.py --summary-only # re-print the table from finished runs

Eval's judge only knows the 30 clean Gold v2.2 narrative questions, so each arm's answers are split by perturbation
(casual / typo_terms / typo_company) and each rewrite's qid is mapped back to its clean_qid. Rewrites change the
wording only, so the required points are the clean question's. The 3 NetApp 10-Q rewrites (review_required) are left
out, as agreed with Eval (72 per arm). Judge prompts, rubric and quote guard are Eval's, unchanged.
Also reports, without any model call, how many answers cite only filings other than the gold filing(s).
Exploratory, not pre-registered; not tracked in git (like the other qr_* scripts).
"""
import argparse, glob, json, subprocess, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QR = ROOT / "eval/results/query_rewrite"
OUT = QR / "judge"
EVAL_RES = ROOT.parent / "kpmg-eval" / "Week 8" / "results"
ARMS = ["precheck", "agents"]


def load():
    suite = {json.loads(l)["qid"]: json.loads(l) for l in open(ROOT / "eval/suites/messy_wording_v1.jsonl")}
    arms = {}
    for arm in ARMS:
        f = glob.glob(str(QR / arm / "*" / "answer_blocks.jsonl"))[0]
        arms[arm] = [a for a in map(json.loads, open(f))
                     if suite[a["qid"]]["answer_type"] == "narrative" and suite[a["qid"]]["snapshot_status"] == "in_snapshot"]
    return suite, arms


def wrong_filing(a, q):
    gold = {e["accession"] for e in q.get("rag_evidence") or [] if e.get("accession")}
    cited = {c.get("accession") for c in a.get("citations") or [] if c.get("accession")}
    return bool(a.get("answered")) and bool(cited) and bool(gold) and not (cited & gold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    a = ap.parse_args()
    suite, arms = load()
    OUT.mkdir(parents=True, exist_ok=True)
    tags = []
    for arm, ans in arms.items():
        by = defaultdict(list)
        for x in ans:
            q = suite[x["qid"]]
            by[q["perturbation"]].append({**x, "qid": q["clean_qid"], "rewrite_qid": x["qid"]})
        for pert, rows in sorted(by.items()):
            tag = f"qr_{arm}_{pert}"
            tags.append((arm, pert, tag, rows))
            f = OUT / f"{tag}.jsonl"
            f.write_text("".join(json.dumps(r) + "\n" for r in rows))
            if not a.summary_only:
                cmd = [sys.executable, str(ROOT / "scripts/run_eval_judge.py"), "--answers", str(f), "--tag", tag] + \
                      (["--dry-run"] if a.dry_run else [])
                print(f"== {tag}: {len(rows)} answers", flush=True)
                subprocess.run(cmd, check=True, cwd=ROOT)

    print("\n| arm | narrative rewrites | answered | cite only a non-gold filing | all required points (of all) | mean point recall | with unsupported claims |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for arm, ans in arms.items():
        n, answered = len(ans), sum(bool(x.get("answered")) for x in ans)
        wf = sum(wrong_filing(x, suite[x["qid"]]) for x in ans)
        passed = tot = unsup = 0
        recall = []
        for arm2, pert, tag, rows in tags:
            res = EVAL_RES / f"narrative_judge_{tag}.json"
            if arm2 != arm or not res.exists():
                continue
            # denominator = every rewrite we sent (answered or not); unanswered or unjudged = not passed, recall 0
            judged = {r["qid"]: r for r in json.loads(res.read_text()).get("questions") or []}
            for row in rows:
                r = judged.get(row["qid"]) if row.get("answered") else None
                tot += 1
                passed += bool(r and r.get("passed"))
                recall.append((r or {}).get("point_recall") or 0.0)
                unsup += bool(r and r.get("unsupported_claims"))
        if tot:
            print(f"| {arm} | {n} | {answered} | {wf} | {passed}/{tot} | {sum(recall) / len(recall):.3f} | {unsup} |")
        else:
            print(f"| {arm} | {n} | {answered} | {wf} | (not run) | | |")
    print("Unanswered rewrites count as not passed (point recall 0). Exploratory; judge = Eval's Week 8 rubric.")


if __name__ == "__main__":
    main()
