"""Eval's extra suites (sets D, E) -> reader question files; the reader's --filters modes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "eval" / "vendor")]
import run_round1_reader as rr  # noqa: E402
from rag.coverage import CoverageIndex, Filing  # noqa: E402
from datetime import date  # noqa: E402

COV = CoverageIndex([
    Filing("MSFT", "Microsoft Corporation", "10-Q", "0001193125-26-191507", date(2026, 3, 31), 2026, "Q3"),
    Filing("MSFT", "Microsoft Corporation", "10-K", "0001193125-26-323660", date(2026, 6, 30), 2026, "FY"),
    Filing("AAPL", "Apple Inc.", "10-Q", "0000320193-26-000011", date(2026, 3, 28), 2026, "Q2"),
])


def q(text, filters=None):
    return {"qid": "x", "question": text, "filters": filters}


def test_filter_modes():
    g = {"ticker": "MSFT", "form": "10-Q"}
    assert rr.filters_for(q("anything", g), "gold") == (g, None)
    assert rr.filters_for(q("anything", g), "none") == (None, None)
    f, pc = rr.filters_for(q("What was Microsfot's revenue for the three months ended March 31, 2026?", g), "precheck", COV)
    assert pc["status"] == "all_hit" and f["ticker"] == "MSFT" and f["accession_number"] == ["0001193125-26-191507"]
    f, pc = rr.filters_for(q("Compare Microsoft's and Apple's revenue for the quarter ended March 31, 2026."), "precheck", COV)
    assert f["ticker"] == ["AAPL", "MSFT"]                      # retrieve_multi splits per company
    f, pc = rr.filters_for(q("What was Microsoft's revenue for the three months ended March 31, 2027?"), "precheck", COV)
    assert pc["status"] == "none" and f is None                 # the runner declines with pc["message"], no retrieval
    f, pc = rr.filters_for(q("what was total revenue last quarter"), "precheck", COV)
    assert pc["status"] == "no_target" and f is None            # nothing to restrict: whole index


def test_block_carries_suite_keys():
    b = rr.to_block({"qid": "AB-001", "sid": "AB-001"}, {"answered": False}, [], "t")
    assert b["sid"] == "AB-001" and "vid" not in b


EVAL = ROOT.parent / "kpmg-eval"


@pytest.mark.skipif(not (EVAL / "Week 8" / "data" / "messy_wording_v1.jsonl").exists(), reason="kpmg-eval not cloned next to KPMG_RAG")
def test_make_suite_gold(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts/make_suite_gold.py"), "--eval-dir", str(EVAL), "--out", str(tmp_path)],
                   check=True, cwd=ROOT)
    m = [json.loads(l) for l in open(tmp_path / "messy_wording_v1.jsonl")]
    e = [json.loads(l) for l in open(tmp_path / "abstention_suite_v1.jsonl")]
    assert len(m) == 427 and all(x["qid"] == x["vid"] and x["question"] for x in m)
    assert len(e) == 56 and {rr.group(x) for x in e} == {"refusal", "false_premise"}
    assert {rr.group(x) for x in m} <= {"number", "refusal", "false_premise", "categorical", "narrative", "graph_route",
                                       "ntap_10q_excluded"}
