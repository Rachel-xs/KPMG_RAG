"""Contract v1: optional metadata (section_id, section_path, table_id, table_name, parent_id, parent_text),
backward compatibility with v0 indexes, both backends, the parent builder and the tracing hook."""
import json
import shutil
from pathlib import Path

import pytest

import rag.retrieve as rr
from rag.chunk import chunk_corpus
from rag.contract import CONTRACT_VERSION, METADATA_KEYS, validate_results
from rag.index import build_index
from rag.observability import _as_documents, traced_retriever
from rag.parents import attach_parents
from rag.retrieve import Retriever, section_path, to_contract

FX = Path(__file__).parent / "fixtures"
V1_KEYS = {"section_id", "section_path", "table_id", "table_name", "parent_id", "parent_text", "trace_id"}


def _v1_chunks(tmp: Path) -> Path:
    """Fixture chunks plus v1 fields, as build_chunk_variant.py --with-parents would write them."""
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks_v0.jsonl", 120, 200)
    rows = [json.loads(l) for l in open(tmp / "chunks_v0.jsonl")]
    for i, c in enumerate(rows):
        c["seq"] = i
        c["section_id"] = f"sec-{c['accession']}-{c['section']}"
        if c.get("is_table"):
            c["table_id"] = f"{c['section_id']}-t00"
            c["table_name"] = "Revenue by segment"
    attach_parents(rows, {}, lambda s: len(s.split()), cap=400)
    out = tmp / "chunks_v1.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return out


@pytest.fixture(scope="module")
def v1_index(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v1")
    build_index(_v1_chunks(tmp), tmp / "index", "lsa")
    return tmp


def test_contract_version_and_documented_keys():
    assert CONTRACT_VERSION == "v1"
    assert V1_KEYS <= METADATA_KEYS


def test_v1_fields_returned_and_still_valid(v1_index):
    r = Retriever(v1_index / "index", log_dir=None)
    res = r.search("total net revenue operating profit", top_k=5, method="bm25", trace_id="t-1")["results"]
    validate_results(res, 5)
    m = res[0]["metadata"]
    assert m["section_id"].startswith("sec-") and m["section_path"]
    assert m["parent_id"] and m["parent_text"] and res[0]["text"] in m["parent_text"]
    assert m["trace_id"] == "t-1"


def test_v0_index_returns_no_v1_keys(tmp_path):
    shutil.copytree(FX / "raw", tmp_path / "raw")
    chunk_corpus(tmp_path / "raw", tmp_path / "chunks.jsonl", 120, 200)
    build_index(tmp_path / "chunks.jsonl", tmp_path / "index", "lsa")
    res = Retriever(tmp_path / "index", log_dir=None).search("total net revenue", top_k=5, method="bm25")["results"]
    for r in res:
        assert not (V1_KEYS - {"section_id"}) & set(r["metadata"]), "v0 index must not grow new keys"


def test_section_path_skips_empty_and_repeats():
    assert section_path({"section": "Part I Item 1", "section_title": "part i item 1", "table_name": "Revenue"}) \
        == "Part I Item 1 > Revenue"
    assert section_path({"section": "Unlabeled", "section_title": "", "table_name": None}) is None


def test_to_contract_passthrough_only_when_present():
    base = {"chunk_id": "c1", "text": "t", "cik": 1, "form": "10-Q", "filing_date": "2026-01-01",
            "section": "Part I Item 2", "section_title": "MD&A"}
    assert "table_name" not in to_contract(base, 1, 1.0, "iv")["metadata"]
    m = to_contract({**base, "table_name": "Revenue", "section_id": "s"}, 1, 1.0, "iv")["metadata"]
    assert m["table_name"] == "Revenue" and m["section_path"] == "Part I Item 2 > MD&A > Revenue"


def test_trace_id_logged(v1_index, tmp_path):
    r = Retriever(v1_index / "index", log_dir=tmp_path)
    r.search("revenue", top_k=3, method="bm25", trace_id="agent-7")
    row = json.loads((tmp_path / "retrieval.jsonl").read_text().splitlines()[-1])
    assert row["trace_id"] == "agent-7"


def test_chroma_keeps_v1_fields(v1_index, tmp_path):
    pytest.importorskip("chromadb")
    from rag.chroma_backend import ChromaRetriever, build_chroma_index

    build_chroma_index(v1_index / "chunks_v1.jsonl", tmp_path / "chroma", "lsa")
    res = ChromaRetriever(tmp_path / "chroma", log_dir=None).search(
        "total net revenue operating profit", top_k=5, method="bm25", trace_id="t-2")["results"]
    validate_results(res, 5)
    m = res[0]["metadata"]
    assert m["parent_text"] and m["section_id"] and m["trace_id"] == "t-2"


def test_attach_parents_table_and_text_windows():
    chunks = [
        {"chunk_id": "a", "seq": 0, "accession": "x", "section_id": "s", "text": "one", "is_table": False},
        {"chunk_id": "b", "seq": 1, "accession": "x", "section_id": "s", "text": "two", "is_table": False},
        {"chunk_id": "t", "seq": 2, "accession": "x", "section_id": "s", "text": "| r |", "is_table": True,
         "table_id": "T"},
    ]
    attach_parents(chunks, {"T": "| whole table |"}, lambda s: len(s.split()), cap=50)
    assert chunks[2]["parent_id"] == "T" and chunks[2]["parent_text"] == "| whole table |"
    assert chunks[0]["parent_text"] == "one\n\ntwo"


def test_tracing_wrapper_is_transparent_when_off(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    fn = traced_retriever(lambda q, filters=None, top_k=10, trace_id=None: [{"text": q, "metadata": {}}])
    assert fn("hello") == [{"text": "hello", "metadata": {}}]


def test_langsmith_documents_drop_parent_text():
    docs = _as_documents([{"text": "x", "chunk_id": "c", "metadata": {"parent_text": "long", "table_name": "T"}}])
    d = docs["documents"][0]
    assert d["page_content"] == "x" and d["metadata"]["table_name"] == "T" and "parent_text" not in d["metadata"]


def test_public_retrieve_is_traced_and_accepts_trace_id(v1_index, monkeypatch):
    monkeypatch.setenv("RAG_INDEX_DIR", str(v1_index / "index"))
    monkeypatch.delenv("RAG_BACKEND", raising=False)
    monkeypatch.delenv("RAG_CHROMA_DIR", raising=False)
    monkeypatch.setenv("RAG_LOG_DIR", str(v1_index / "logs"))
    rr._DEFAULT = None
    try:
        res = rr.retrieve("total net revenue", top_k=3, trace_id="pub-1")
        assert res and res[0]["metadata"]["trace_id"] == "pub-1"
    finally:
        rr._DEFAULT = None
