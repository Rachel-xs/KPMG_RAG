"""Contract v1.1: evidence_status / weak_reasons on the search envelope and retrieve_with_status."""
import inspect
import shutil
from pathlib import Path

import pytest

import rag.retrieve as rr
from rag.chunk import chunk_corpus
from rag.contract import normalize_filters
from rag.evidence import assess, methods_overlap
from rag.index import build_index
from rag.retrieve import Retriever

FX = Path(__file__).parent / "fixtures"


def _r(ticker="MSFT", fy=2026, fp="Q3"):
    return {"ticker": ticker, "metadata": {"fiscal_year": fy, "fiscal_period": fp}}


def test_assess_empty_and_ok():
    assert assess({}, [], 0, None)["weak_reasons"] == ["filter_no_match"]
    assert assess({}, [], 5, None)["evidence_status"] == "empty"
    out = assess(normalize_filters({"ticker": "MSFT", "fiscal_year": 2026}), [_r()], 5, 4)
    assert out["evidence_status"] == "ok" and out["weak_reasons"] == []
    assert out["evidence_checks"]["bm25_dense_overlap@10"] == 4


def test_assess_weak_reasons():
    nf = normalize_filters({"ticker": ["MSFT", "AAPL"], "fiscal_period": "Q2"})
    out = assess(nf, [_r()], 5, 0)
    assert out["evidence_status"] == "weak"
    assert out["weak_reasons"] == ["multi_target", "entity_missing", "methods_disagree"]


def test_methods_overlap_window():
    assert methods_overlap(list(range(20)), list(range(10, 30))) == 0
    assert methods_overlap([1, 2, 3], [3, 2, 9]) == 2


def test_default_rrf_k_unchanged():
    assert inspect.signature(Retriever.__init__).parameters["rrf_k"].default == 60
    assert inspect.signature(rr.make_retriever).parameters["rrf_k"].default == 60


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ev")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    return tmp / "index"


def test_envelope_has_status(idx):
    r = Retriever(idx, log_dir=None)
    env = r.search("total net revenue", top_k=5, method="hybrid")
    assert env["evidence_status"] in ("ok", "weak") and isinstance(env["weak_reasons"], list)
    assert isinstance(env["evidence_checks"]["bm25_dense_overlap@10"], int)
    bm = r.search("total net revenue", top_k=5, method="bm25")
    assert bm["evidence_checks"]["bm25_dense_overlap@10"] is None


def test_filter_no_match_is_empty(idx):
    env = Retriever(idx, log_dir=None).search("revenue", filters={"ticker": "ZZZZ"}, top_k=5)
    assert env["results"] == [] and env["evidence_status"] == "empty"
    assert env["weak_reasons"] == ["filter_no_match"]


def test_retrieve_with_status(idx, monkeypatch):
    monkeypatch.setattr(rr, "_DEFAULT", Retriever(idx, log_dir=None))
    out = rr.retrieve_with_status("total net revenue", top_k=3, trace_id="t-9")
    assert set(out) >= {"results", "evidence_status", "weak_reasons", "evidence_checks", "trace_id"}
    assert out["trace_id"] == "t-9" and len(out["results"]) <= 3
    assert [c["chunk_id"] for c in out["results"]] == [c["chunk_id"] for c in rr.retrieve("total net revenue", top_k=3)]
