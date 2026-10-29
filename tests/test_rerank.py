"""Reranker wiring tests with a stub cross-encoder (no model download)."""
import shutil
from pathlib import Path

import pytest

from rag.chunk import chunk_corpus
from rag.contract import validate_results
from rag.index import build_index
from rag.rerank import load_reranker
from rag.retrieve import Retriever

FX = Path(__file__).parent / "fixtures"


class StubReranker:
    """Scores a passage by how many times it contains the word 'revenue' (deterministic, offline)."""

    spec = "stub"

    def __init__(self):
        self.calls = 0

    def score(self, query, passages):
        self.calls += 1
        return [p.lower().count("revenue") + 0.001 * i for i, p in enumerate(passages)]


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rr")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    return tmp / "index"


def test_rerank_reorders_and_keeps_contract(index_dir):
    rr = StubReranker()
    r = Retriever(index_dir, log_dir=None, reranker=rr, rerank_pool=10)
    base = r.search("total revenue", top_k=5, method="bm25", rerank=False)
    out = r.search("total revenue", top_k=5, method="bm25")
    assert rr.calls == 1
    assert base["method"] == "bm25" and base["reranker"] is None
    assert out["method"] == "bm25+rerank" and out["reranker"] == "stub"
    validate_results(out["results"], 5)
    scores = [x["score"] for x in out["results"]]
    assert scores == sorted(scores, reverse=True)
    assert all(x["metadata"]["first_stage_rank"] >= 1 for x in out["results"])
    assert all(x["metadata"]["retrieval_method"] == "bm25+rerank" for x in out["results"])


def test_rerank_only_reorders_first_stage_pool(index_dir):
    r = Retriever(index_dir, log_dir=None, reranker=StubReranker(), rerank_pool=10)
    pool = {x["chunk_id"] for x in r.search("total revenue", top_k=10, method="bm25", rerank=False)["results"]}
    got = {x["chunk_id"] for x in r.search("total revenue", top_k=5, method="bm25")["results"]}
    assert got <= pool


def test_rerank_empty_filter_result(index_dir):
    r = Retriever(index_dir, log_dir=None, reranker=StubReranker())
    out = r.search("total revenue", filters={"ticker": "ZZZZ"}, top_k=5, method="bm25")
    assert out["results"] == [] and out["reranker"] is None


def test_load_reranker_none():
    assert load_reranker(None) is None and load_reranker("none") is None
    with pytest.raises(ValueError):
        load_reranker("bogus:model")
