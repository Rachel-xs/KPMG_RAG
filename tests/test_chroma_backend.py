"""Chroma MVP acceptance tests.

These tests prove that changing the backend does not change the Agent-facing
``retrieve(query, filters, top_k)`` interface or Retrieval API v0 schema.
"""
from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

import rag.retrieve as rr
from rag.chunk import chunk_corpus
from rag.chroma_backend import ChromaRetriever, build_chroma_index
from rag.contract import validate_results

FX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def chroma_index(tmp_path):
    chunks = tmp_path / "chunks.jsonl"
    chunk_corpus(FX / "raw", chunks, 120, 200)
    persist_dir = tmp_path / "chroma"
    build_chroma_index(chunks, persist_dir, "lsa", cache_dir=tmp_path / "cache")
    return persist_dir


def test_chroma_returns_contract_and_filters(chroma_index):
    retriever = ChromaRetriever(chroma_index, log_dir=None)
    response = retriever.search(
        "total net revenue operating profit",
        filters={"ticker": "acme", "form": "10-k"},
        top_k=3,
    )
    assert response["backend"] == "chroma"
    assert response["results"]
    assert all(row["ticker"] == "ACME" and row["form"] == "10-K" for row in response["results"])
    assert all(row["metadata"]["retrieval_backend"] == "chroma" for row in response["results"])
    validate_results(response["results"], top_k=3)


def test_section_prefix_and_no_match(chroma_index):
    retriever = ChromaRetriever(chroma_index, log_dir=None)
    rows = retriever.retrieve("risk", {"ticker": "ACME", "section": "Item 1"}, top_k=5)
    assert rows
    assert all((row["section"] or "").startswith("Item 1") for row in rows)
    assert retriever.retrieve("risk", {"ticker": "NOPE"}, top_k=5) == []


def test_module_level_interface_switch_needs_no_agent_change(chroma_index, monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "chroma")
    monkeypatch.setenv("RAG_CHROMA_DIR", str(chroma_index))
    monkeypatch.setenv("RAG_LOG_DIR", str(chroma_index.parent / "logs"))
    rr._DEFAULT = None
    try:
        # This is the exact public call already used by the Agent wrapper.
        rows = rr.retrieve("total net revenue", {"ticker": "ACME"}, top_k=2)
        assert rows
        validate_results(rows, top_k=2)
    finally:
        rr._DEFAULT = None


@pytest.mark.parametrize("method", ["bm25", "dense", "hybrid"])
def test_all_retrieval_methods(chroma_index, method):
    retriever = ChromaRetriever(chroma_index, log_dir=None)
    rows = retriever.search("supply chain disruption", {"ticker": "ACME"}, 3, method)["results"]
    assert rows
    validate_results(rows, top_k=3)
