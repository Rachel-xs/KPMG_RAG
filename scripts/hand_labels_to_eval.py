"""Turn the team's blind point-by-point labels into Eval's format, and compare them with the judge.

    python scripts/hand_labels_to_eval.py           # after the four scorers fill hand_labels_blind.csv

Input  eval/results/hand_labels/hand_labels_blind.csv   (qid, scorer, version A/B, point, ..., human_verdict)
       eval/results/hand_labels/KEY_do_not_share.json   (which run each A/B is; only the label holder opens it)
Output eval/results/hand_labels/hand_labels_eval.csv     qid, run, point, human_verdict   <- send to Eval
       eval/results/hand_labels/labels_<run>.csv          qid, point, human_verdict        <- Eval's --validate input
       summary printed: labels per run, missing labels, and (if Eval's judge results are found next door) agreement
       and Cohen's kappa with the judge per run, the same statistic Eval's --validate reports.
Verdicts must be stated / missing / contradicted (case-insensitive; s / m / c accepted).
"""
from __future__ import annotations

import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORT = {"s": "stated", "m": "missing", "c": "contradicted"}
CATS = ("stated", "missing", "contradicted")


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None, None
    po = sum(h == j for h, j in pairs) / n
    pe = sum((sum(h == c for h, _ in pairs) / n) * (sum(j == c for _, j in pairs) / n) for c in CATS)
    return round(po, 3), round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="eval/results/hand_labels")
    ap.add_argument("--eval-results", default=str(ROOT.parent / "kpmg-eval" / "Week 8" / "results"))
    a = ap.parse_args()
    d = ROOT / a.dir
    key = {(k["qid"], k["version"]): k["run"] for k in json.loads((d / "KEY_do_not_share.json").read_text())}
    out, bad, missing = [], [], 0
    for r in csv.DictReader(open(d / "hand_labels_blind.csv", encoding="utf-8")):
        v = (r.get("human_verdict") or "").strip().lower()
        v = SHORT.get(v, v)
        if not v:
            missing += 1
            continue
        if v not in CATS:
            bad.append((r["qid"], r["version"], r["point"], r["human_verdict"]))
            continue
        out.append({"qid": r["qid"], "run": key[(r["qid"], r["version"])], "point": int(r["point"]), "human_verdict": v,
                    "scorer": r.get("scorer", "")})
    if bad:
        raise SystemExit(f"{len(bad)} verdicts are not stated/missing/contradicted, e.g. {bad[:3]}")
    with open(d / "hand_labels_eval.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["qid", "run", "point", "human_verdict"])
        w.writeheader()
        w.writerows({k: x[k] for k in ("qid", "run", "point", "human_verdict")} for x in out)
    by_run = defaultdict(list)
    for x in out:
        by_run[x["run"]].append(x)
    print(f"{len(out)} labels ({missing} still empty); per run: {dict(Counter(x['run'] for x in out))}")
    for run, xs in sorted(by_run.items()):
        with open(d / f"labels_{run}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["qid", "point", "human_verdict"])
            w.writeheader()
            w.writerows({k: x[k] for k in ("qid", "point", "human_verdict")} for x in xs)
        jf = Path(a.eval_results) / f"narrative_judge_{run}.json"
        if jf.exists():
            j = {(q["qid"], i + 1): v for q in json.loads(jf.read_text())["questions"] for i, v in enumerate(q["verdicts"])}
            pairs = [(x["human_verdict"], j[(x["qid"], x["point"])]) for x in xs if (x["qid"], x["point"]) in j]
            po, k = kappa(pairs)
            print(f"  {run}: {len(xs)} labels; vs judge on {len(pairs)} points: agreement {po}, kappa {k}"
                  f"{'  (>= 0.6: judge usable as headline)' if k is not None and k >= 0.6 else ''}")
        else:
            print(f"  {run}: {len(xs)} labels (judge results not found at {jf})")
    print(f"-> {d / 'hand_labels_eval.csv'} (send to Eval)")


if __name__ == "__main__":
    main()
