"""holdout_hand_labels.py: sheet checks, rater agreement, adjudication, Eval's format, and keeping the judge hidden
until every disagreement is adjudicated. Uses a tiny synthetic label set in a temporary folder (no real labels)."""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import holdout_hand_labels as hl  # noqa: E402

COLS = ["qid", "scorer", "version", "point", "required_point", "question", "answer_text", "human_verdict", "note"]
# two answers, two points each: Q-1 (run v1) rated by Scorer1/Scorer2, Q-2 (run v2) by Scorer3/Scorer4
PLAN = {"Scorer1": [("Q-1", 1), ("Q-1", 2)], "Scorer2": [("Q-1", 1), ("Q-1", 2)],
        "Scorer3": [("Q-2", 1), ("Q-2", 2)], "Scorer4": [("Q-2", 1), ("Q-2", 2)]}


def make(tmp, verdicts, judge=None):
    d = tmp / "labels"
    d.mkdir(exist_ok=True)
    (d / "KEY_do_not_share.json").write_text(json.dumps([
        {"qid": "Q-1", "version": "A", "run": "rag_final_v1"}, {"qid": "Q-2", "version": "A", "run": "rag_final_v2"}]))
    for scorer, pts in PLAN.items():
        with open(d / f"hand_labels_blind_{scorer}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            for q, p in pts:
                w.writerow({"qid": q, "scorer": scorer, "version": "A", "point": p, "required_point": f"pt{p}",
                            "human_verdict": verdicts.get((scorer, q, p), "stated")})
    repo = tmp / "eval_repo"
    if judge:
        res = repo / "Week 8" / "results"
        res.mkdir(parents=True)
        for tag, qs in judge.items():
            (res / f"narrative_judge_{tag}.json").write_text(json.dumps({"questions": qs}))
    return d, repo


def run(monkeypatch, d, repo, *extra):
    monkeypatch.setattr(sys, "argv", ["holdout_hand_labels.py", "--dir", str(d), "--eval-repo", str(repo), *extra])
    hl.main()
    return json.loads((d / "agreement.json").read_text()) if (d / "agreement.json").exists() else None


def test_kappa_and_short_codes():
    assert hl.kappa([("stated", "stated"), ("missing", "missing")])["kappa"] == 1.0
    assert hl.kappa([("stated", "stated"), ("stated", "stated")])["kappa"] is None   # one category only
    assert [hl.norm(v) for v in ("S", " m ", "c", "Stated")] == ["stated", "missing", "contradicted", "stated"]


def test_full_agreement(tmp_path, monkeypatch):
    d, repo = make(tmp_path, {("Scorer1", "Q-1", 2): "m", ("Scorer2", "Q-1", 2): "missing"})
    out = run(monkeypatch, d, repo)
    assert out["disagreements"] == 0 and out["unresolved"] == []
    assert out["pairs"]["pooled"]["agree"] == 4
    assert out["by_run"]["rag_final_v1"]["every_point_stated"] == "0/1"
    assert out["by_run"]["rag_final_v2"]["every_point_stated"] == "1/1"
    rows = list(csv.DictReader(open(d / "hand_labels_eval.csv")))
    assert len(rows) == 8 and set(rows[0]) == {"qid", "run", "point", "rater", "human_verdict"}
    assert (d / "labels_rag_final_v1.csv").exists() and (d / "hand_labels_blind.csv").exists()


def test_disagreement_is_adjudicated_and_the_judge_stays_hidden_until_then(tmp_path, monkeypatch):
    judge = {"holdout_A_final_v1": [{"qid": "Q-1", "verdicts": ["stated", "stated"]}],
             "holdout_B_final_v2": [{"qid": "Q-2", "verdicts": ["stated", "stated"]}]}
    d, repo = make(tmp_path, {("Scorer4", "Q-2", 1): "missing"}, judge)
    out = run(monkeypatch, d, repo)
    assert out["unresolved"] == ["Q-2#1"]
    v2 = out["by_run"]["rag_final_v2"]
    assert "hidden" in v2["gpt6sol"] and "hidden" in v2["differs_from_eval_judge"]
    assert "Q-2" not in [r["qid"] for r in csv.DictReader(open(d / "labels_rag_final_v2.csv")) if r["point"] == "1"]

    adj = list(csv.DictReader(open(d / "adjudication.csv")))
    assert len(adj) == 1 and adj[0]["final"] == ""
    adj[0]["final"] = "stated"
    with open(d / "adjudication.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(adj[0]))
        w.writeheader()
        w.writerows(adj)
    out = run(monkeypatch, d, repo)
    v2 = out["by_run"]["rag_final_v2"]
    assert out["unresolved"] == [] and v2["every_point_stated"] == "1/1"
    assert v2["gpt6sol_vs_consensus"]["agree"] == 2
    assert list(csv.DictReader(open(d / "adjudication.csv")))[0]["final"] == "stated"   # kept on rerun


def test_empty_or_malformed_labels_stop_the_merge(tmp_path, monkeypatch):
    d, repo = make(tmp_path, {("Scorer1", "Q-1", 1): "", ("Scorer3", "Q-2", 2): "maybe"})
    run(monkeypatch, d, repo, "--check-only")                  # reports, does not stop
    with pytest.raises(SystemExit, match="fix the sheets"):
        run(monkeypatch, d, repo)
