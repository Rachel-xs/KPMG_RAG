"""Contract v1.2: retrieve_multi (one search per target, merged round robin)."""
import shutil
from pathlib import Path

import pytest

import rag.retrieve as rr
from rag.chunk import chunk_corpus
from rag.index import build_index
from rag.multi import default_top_k_each, multi_search, split_filters
from rag.retrieve import Retriever

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def retr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("multi")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    return Retriever(tmp / "index", log_dir=None)


def test_split_filters():
    assert split_filters(None) == [("all", {})]
    assert split_filters({"ticker": "MSFT", "form": "10-Q"}) == [("all", {"ticker": "MSFT", "form": "10-Q"})]
    out = split_filters({"ticker": ["msft", "AAPL"], "form": "10-K"})
    assert out == [("ticker=AAPL", {"form": "10-K", "ticker": "AAPL"}), ("ticker=MSFT", {"form": "10-K", "ticker": "MSFT"})]
    out = split_filters({"ticker": "MSFT", "fiscal_year": 2026, "fiscal_period": ["FY", "Q3"]})
    assert [l for l, _ in out] == ["fiscal_period=FY", "fiscal_period=Q3"]
    assert len(split_filters({"form": ["10-K", "10-Q"], "fiscal_period": ["FY", "Q3"]})) == 4
    with pytest.raises(ValueError):
        split_filters({"ticker": [f"T{i}" for i in range(7)], "form": ["10-K", "10-Q"], "fiscal_year": [2025, 2026]})


def test_default_depth():
    assert default_top_k_each(2, 10) == 10 and default_top_k_each(10, 10) == 5 and default_top_k_each(10, 3) == 3


def test_every_target_represented_round_robin(retr):
    out = multi_search(retr.search, "revenue", {"ticker": ["ACME", "BETA"]}, top_k=4, trace_id="t-1")
    labels = [r["metadata"]["subquery"] for r in out["results"]]
    assert labels[:2] == ["ticker=ACME", "ticker=BETA"]
    assert {r["ticker"] for r in out["results"]} == {"ACME", "BETA"}
    assert [r["rank"] for r in out["results"]] == list(range(1, len(out["results"]) + 1))
    assert len({r["chunk_id"] for r in out["results"]}) == len(out["results"])
    assert all("multi_target" not in w for w in out["weak_reasons"])
    assert out["trace_id"] == "t-1" and len(out["subqueries"]) == 2 and out["top_k_each"] == 4


def test_impossible_combination_is_skipped_not_weak(retr):
    out = multi_search(retr.search, "revenue", {"ticker": ["ACME", "ZZZZ"]}, top_k=3)
    assert [s["label"] for s in out["skipped"]] == ["ticker=ZZZZ"] and out["warnings"]
    assert {r["ticker"] for r in out["results"]} == {"ACME"}
    assert not any(w.startswith("ticker=ZZZZ") for w in out["weak_reasons"])


def test_nothing_matches_is_empty(retr):
    out = multi_search(retr.search, "revenue", {"ticker": ["YYYY", "ZZZZ"]}, top_k=3)
    assert out["results"] == [] and out["evidence_status"] == "empty" and out["weak_reasons"] == ["filter_no_match"]


def test_explicit_subqueries(retr):
    out = multi_search(retr.search, "", None, top_k=2, subqueries=[
        {"query": "net revenue", "filters": {"ticker": "ACME"}, "label": "acme"},
        {"query": "net revenue", "filters": {"ticker": "BETA"}}])
    assert [s["label"] for s in out["subqueries"]] == ["acme", "sub2"]
    with pytest.raises(ValueError):
        multi_search(retr.search, "x", None, subqueries=[])


def test_retrieve_multi_single_target_matches_retrieve_with_status(retr, monkeypatch):
    monkeypatch.setattr(rr, "_DEFAULT", retr)
    one = rr.retrieve_multi("total net revenue", {"ticker": "ACME"}, top_k=3)
    ref = rr.retrieve_with_status("total net revenue", {"ticker": "ACME"}, top_k=3)
    assert [c["chunk_id"] for c in one["results"]] == [c["chunk_id"] for c in ref["results"]]
    assert one["subqueries"][0]["label"] == "all" and one["evidence_status"] == ref["evidence_status"]
