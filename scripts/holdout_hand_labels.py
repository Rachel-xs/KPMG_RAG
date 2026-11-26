"""Holdout narrative hand labels (11/25): merge the four blind sheets, check them, agreement between raters,
consensus, Eval's format, and agreement with the gpt-6-sol judge.

    python scripts/holdout_hand_labels.py --check-only    # what is still empty or malformed, per scorer
    python scripts/holdout_hand_labels.py                 # everything below

Input   eval/results/hand_labels_holdout/hand_labels_blind_Scorer{1..4}.csv   filled sheets, same rows as sent
        eval/results/hand_labels_holdout/KEY_do_not_share.json               which run each qid/version is
        eval/results/hand_labels_holdout/adjudication.csv                    optional: fill `final`, rerun
        ../kpmg-eval/Week 8/results/narrative_judge_holdout_{A_final_v1,B_final_v2}.json
                                                                             optional: run_eval_judge_holdout.py
Output (same folder)
        hand_labels_blind.csv   all four sheets in one file, one row per scorer x point
        adjudication.csv        points where the two raters disagree; `final` blank until the label holder fills it
                                (the judge comparison stays hidden until every disagreement has a final verdict)
        hand_labels_eval.csv    qid, run, point, rater, human_verdict    <- send to Eval (both raters, every point)
        labels_<run>.csv        qid, point, human_verdict                <- consensus only; Eval's --validate input
        agreement.json          rater pairs, consensus pass counts, human vs judge
Verdicts: stated / missing / contradicted (s / m / c accepted, any case). Each point must have exactly two raters.
The key and adjudication.csv stay private; nothing here goes to the raters.
"""
from __future__ import annotations

import argparse, csv, json, subprocess
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORT = {"s": "stated", "m": "missing", "c": "contradicted"}
CATS = ("stated", "missing", "contradicted")
JUDGE_TAG = {"rag_final_v1": "holdout_A_final_v1", "rag_final_v2": "holdout_B_final_v2"}
OFFICIAL = {"rag_final_v1": "holdout_A_final_v1.json", "rag_final_v2": "holdout_B_final_v2.json"}


def kappa(pairs):
    n = len(pairs)
    if not n:
        return {"points": 0}
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in CATS)
    return {"points": n, "agree": sum(a == b for a, b in pairs), "agreement": round(po, 3),
            "kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,  # None: both sides one category only
            "a/b": dict(Counter(f"{a}/{b}" for a, b in pairs))}


def norm(v):
    v = (v or "").strip().lower()
    return SHORT.get(v, v)


def official_counts(eval_repo: Path, name: str):
    """Eval's per-question narrative counts ("4/4"); origin/main first, so a fetch without pull is enough."""
    rel = f"Week 10/results/{name}"
    try:
        txt = subprocess.run(["git", "-C", str(eval_repo), "show", f"origin/main:{rel}"], capture_output=True,
                             text=True, check=True).stdout
    except Exception:  # noqa: BLE001
        p = eval_repo / rel
        if not p.exists():
            return {}
        txt = p.read_text()
    return json.loads(txt).get("narrative", {}).get("per_question", {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="eval/results/hand_labels_holdout")
    ap.add_argument("--eval-repo", default=str(ROOT.parent / "kpmg-eval"))
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    d = ROOT / a.dir
    eval_repo = Path(a.eval_repo)
    key = {(k["qid"], k["version"]): k["run"] for k in json.loads((d / "KEY_do_not_share.json").read_text())}

    # 1. read and check each sheet
    rows, problems = [], []
    sheets = sorted(d.glob("hand_labels_blind_Scorer*.csv"))
    if not sheets:
        raise SystemExit(f"no hand_labels_blind_Scorer*.csv in {d}")
    for f in sheets:
        scorer = f.stem.split("_")[-1]
        sr = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        empty = [f"{r['qid']}#{r['point']}" for r in sr if not norm(r.get("human_verdict"))]
        bad = [f"{r['qid']}#{r['point']}={r['human_verdict']!r}" for r in sr
               if norm(r.get("human_verdict")) and norm(r.get("human_verdict")) not in CATS]
        wrong = {r.get("scorer") for r in sr} - {scorer, ""}
        print(f"{scorer}: {len(sr)} points, {len(sr) - len(empty) - len(bad)} labelled, {len(empty)} empty, {len(bad)} malformed"
              + (f"; scorer column says {wrong}" if wrong else ""))
        if empty:
            print(f"   empty: {', '.join(empty[:12])}{' …' if len(empty) > 12 else ''}")
        if bad:
            print(f"   malformed: {', '.join(bad)}")
        problems += empty + bad
        for r in sr:
            r["scorer"] = scorer
            r["human_verdict"] = norm(r.get("human_verdict"))
            rows.append(r)
    by_point = defaultdict(dict)
    for r in rows:
        by_point[(r["qid"], int(r["point"]))][r["scorer"]] = r
    not_two = [f"{q}#{p}: {sorted(s)}" for (q, p), s in by_point.items() if len(s) != 2]
    if not_two:
        print(f"points without exactly two raters: {not_two[:10]}")
    missing_key = sorted({r["qid"] for r in rows if (r["qid"], r["version"]) not in key})
    if missing_key:
        print(f"qids not in the key: {missing_key}")
    if a.check_only:
        return
    if problems or not_two or missing_key:
        raise SystemExit("fix the sheets above first (or ask the scorer), then rerun")

    # 2. merged blind file (same columns as 11/17)
    cols = ["qid", "scorer", "version", "point", "required_point", "question", "answer_text", "human_verdict", "note"]
    with open(d / "hand_labels_blind.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["qid"], int(r["point"]), r["scorer"])))

    # 3. agreement between the two raters of each pair
    pair_of = {}
    for (q, p), s in by_point.items():
        pair_of[(q, p)] = tuple(sorted(s))
    out = {"points": len(by_point), "questions": len({q for q, _ in by_point}), "pairs": {}}
    for pair in sorted(set(pair_of.values())):
        pts = sorted(k for k, v in pair_of.items() if v == pair)
        out["pairs"]["/".join(pair)] = kappa([(by_point[k][pair[0]]["human_verdict"], by_point[k][pair[1]]["human_verdict"]) for k in pts])
        out["pairs"]["/".join(pair)]["questions"] = len({q for q, _ in pts})
    allpairs = [tuple(by_point[k][s]["human_verdict"] for s in pair_of[k]) for k in by_point]
    out["pairs"]["pooled"] = kappa(allpairs)

    # 4. consensus, with adjudication of disagreements
    adj_path = d / "adjudication.csv"
    adjudicated = {}
    if adj_path.exists():
        for r in csv.DictReader(open(adj_path, encoding="utf-8-sig")):
            v = norm(r.get("final"))
            if v:
                if v not in CATS:
                    raise SystemExit(f"adjudication.csv: {r['qid']}#{r['point']} final={r['final']!r}")
                adjudicated[(r["qid"], int(r["point"]))] = v
    consensus, disagree = {}, []
    for k, s in sorted(by_point.items()):
        v1, v2 = (s[x]["human_verdict"] for x in pair_of[k])
        if v1 == v2:
            consensus[k] = v1
        else:
            disagree.append(k)
            if k in adjudicated:
                consensus[k] = adjudicated[k]
    with open(adj_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "point", "required_point", "rater_a", "verdict_a", "note_a", "rater_b", "verdict_b", "note_b", "final"])
        for k in disagree:
            ra, rb = (by_point[k][x] for x in pair_of[k])
            w.writerow([k[0], k[1], ra.get("required_point", ""), ra["scorer"], ra["human_verdict"], ra.get("note", ""),
                        rb["scorer"], rb["human_verdict"], rb.get("note", ""), adjudicated.get(k, "")])
    unresolved = [f"{q}#{p}" for q, p in disagree if (q, p) not in adjudicated]
    out["disagreements"] = len(disagree)
    out["unresolved"] = unresolved

    # 5. Eval's format: every rater's label, plus consensus per run
    run_of = {r["qid"]: key[(r["qid"], r["version"])] for r in rows}
    with open(d / "hand_labels_eval.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "run", "point", "rater", "human_verdict"])
        for (q, p), s in sorted(by_point.items()):
            for i, sc in enumerate(pair_of[(q, p)], 1):
                w.writerow([q, run_of[q], p, f"R{i}", s[sc]["human_verdict"]])
    runs = sorted(set(run_of.values()))
    out["by_run"] = {}
    for run in runs:
        ks = [k for k in sorted(consensus) if run_of[k[0]] == run]
        with open(d / f"labels_{run}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["qid", "point", "human_verdict"])
            w.writerows([q, p, consensus[(q, p)]] for q, p in ks)
        qs = sorted({q for q, _ in by_point if run_of[q] == run})
        complete = [q for q in qs if all((q, p) in consensus for qq, p in by_point if qq == q)]
        passed = [q for q in complete if all(consensus[(q, p)] == "stated" for qq, p in by_point if qq == q)]
        pts = [consensus[k] for k in ks]
        offi = official_counts(eval_repo, OFFICIAL[run])
        changed = {}
        for q in complete:
            n = sum(1 for qq, _ in by_point if qq == q)
            h = f"{sum(consensus[(q, p)] == 'stated' for qq, p in by_point if qq == q)}/{n}"
            if q in offi and offi[q] != h:
                changed[q] = {"judge (Eval)": offi[q], "human": h}
        r = {"questions": len(qs), "every_point_stated": f"{len(passed)}/{len(complete)}"
             + ("" if len(complete) == len(qs) else f" ({len(qs) - len(complete)} unresolved)"),
             "points_stated": f"{pts.count('stated')}/{len(pts)}", "verdicts": dict(Counter(pts)),
             "differs_from_eval_judge": changed if not unresolved else "hidden until adjudication.csv is complete",
             "failed": sorted(set(complete) - set(passed))}
        # 6. human vs gpt-6-sol judge (if run)
        jf = eval_repo / "Week 8" / "results" / f"narrative_judge_{JUDGE_TAG[run]}.json"
        if unresolved:
            # keep the adjudicator blind to the judge: no judge comparison until every disagreement has a final verdict
            r["gpt6sol"] = "hidden until adjudication.csv is complete (keeps the adjudicator blind to the judge)"
        elif jf.exists():
            j = {(x["qid"], i): v for x in json.loads(jf.read_text())["questions"] for i, v in enumerate(x["verdicts"], 1)}
            r["gpt6sol_vs_consensus"] = kappa([(consensus[k], j[k]) for k in ks if k in j])
            r["gpt6sol_vs_each_rater"] = kappa([(by_point[k][s]["human_verdict"], j[k]) for k in by_point
                                                if run_of[k[0]] == run and k in j for s in pair_of[k]])
            r["gpt6sol_disagreements"] = [{"qid": k[0], "point": k[1], "human": consensus[k], "judge": j[k]}
                                          for k in ks if k in j and consensus[k] != j[k]]
            r["not_judged"] = sorted({k[0] for k in ks if k not in j})
        else:
            r["gpt6sol"] = f"not run yet ({jf.name})"
        out["by_run"][run] = r
    (d / "agreement.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))

    print(json.dumps(out, indent=1, ensure_ascii=False))
    if unresolved:
        print(f"\n{len(unresolved)} disagreements without a final verdict -> fill `final` in {adj_path.name}, rerun. "
              f"Until then labels_<run>.csv leaves them out; hand_labels_eval.csv already has both raters.")
    print(f"\n-> send to Eval: {d / 'hand_labels_eval.csv'} (+ labels_<run>.csv once unresolved is empty). Keep the key private.")


if __name__ == "__main__":
    main()
