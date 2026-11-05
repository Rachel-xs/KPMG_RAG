import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from rag.chunk import chunk_corpus
from rag.chroma_backend import build_chroma_index
from rag.index import build_index
from scripts.chroma_parity import compare


FX = Path(__file__).parent / "fixtures"


def test_same_snapshot_custom_and_chroma_pass(tmp_path):
    chunks = tmp_path / "chunks.jsonl"
    chunk_corpus(FX / "raw", chunks, 120, 200)
    custom_dir, chroma_dir = tmp_path / "custom", tmp_path / "chroma"
    build_index(chunks, custom_dir, "lsa")
    build_chroma_index(chunks, chroma_dir, "lsa")

    report = compare(
        custom_dir,
        chroma_dir,
        FX / "gold_fixture.jsonl",
        tmp_path / "out",
        top_k=3,
        max_recall_delta=0.02,
    )

    assert report["status"] == "PASS"
    assert report["controls"] == {
        "same_index_version": True,
        "same_embedder": True,
        "same_chunk_count": True,
    }
    manifest = json.loads((tmp_path / "out" / "handoff_manifest.json").read_text())
    assert manifest["source_chunks_sha256"]
    assert manifest["agent_configuration"]["RAG_BACKEND"] == "chroma"
