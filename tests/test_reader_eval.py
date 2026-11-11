"""Round 1 reader evaluation: AnswerBlock conversion and grading (no API calls)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "eval" / "vendor")]
import run_round1_reader as rr  # noqa: E402

GOLD = {q["qid"]: q for q in map(json.loads, open(ROOT / "eval/round1/benchmark_v2.jsonl", encoding="utf-8"))}
RES = [{"chunk_id": f"c{i}", "accession_number": "0001193125-26-191507", "section": "Item 1"} for i in range(1, 4)]


def block(qid, **ans):
    return rr.to_block(GOLD[qid], {"answered": True, "cites": [1], **ans}, RES, "t")


def test_number_correct_and_wrong_period():
    q = GOLD["GSv0-MSFT-001"]
    assert rr.grade(q, "number", block(q["qid"], value_text="USD 82,886 million", value=82886e6, unit="USD"))["label"] == "correct"
    r = rr.grade(q, "number", block(q["qid"], value_text="USD 241,832 million", value=241832e6, unit="USD"))
    assert not r["passed"] and r["label"] == "wrong_period"


def test_block_maps_cites_to_chunk_ids_and_drops_value_on_decline():
    b = rr.to_block(GOLD["GSv0-MSFT-001"], {"answered": False, "value": 5, "cites": [2, 9, "x"]}, RES, "t")
    assert [c["id"] for c in b["citations"]] == ["c2"] and b["value"] is None


def test_refusal_and_false_premise():
    assert rr.grade(GOLD["EV1-061"], "refusal", rr.to_block(GOLD["EV1-061"], {"answered": False, "answer_text": "Not disclosed."}, RES, "t"))["passed"]
    fp = GOLD["EV1-068"]
    txt = "The premise is wrong: revenue actually increased to USD 82,886 million from 70,066 million."
    assert rr.grade(fp, "false_premise", block("EV1-068", answer_text=txt))["label"] == "corrected"


def test_every_question_has_a_group():
    assert {rr.group(q) for q in GOLD.values()} <= {"number", "refusal", "false_premise", "categorical", "narrative",
                                                   "graph_route", "ntap_10q_excluded"}
