"""Optional second-stage reranking with a cross-encoder.

Hybrid retrieval (BM25 + dense + RRF) is good at *finding* the evidence (recall@8 0.83 on Gold v0) but
weak at *ordering* it (MRR 0.48): the right table often sits next to several look-alike rows. A
cross-encoder reads (query, passage) pairs jointly and re-scores the top candidates.

    from rag.rerank import load_reranker
    rr = load_reranker("st:BAAI/bge-reranker-base")      # local, free; downloads once from HF
    Retriever(index_dir, reranker=rr, rerank_pool=30)

Enable for the default `retrieve()` with the env var RAG_RERANKER=st:BAAI/bge-reranker-base.
Specs: "st:<model>" (sentence-transformers CrossEncoder) or "none".
The reranker sees the same contextual header the index uses (company, form, period, section),
so it can use period words like "Three Months Ended" that only appear in the header.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class Reranker(Protocol):
    spec: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, max_length: int = 512, batch_size: int = 16):
        from sentence_transformers import CrossEncoder  # heavy import, keep lazy

        self.spec = f"st:{model_name}"
        self.model = CrossEncoder(model_name, max_length=max_length)
        self.batch_size = batch_size

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        out = self.model.predict([(query, p) for p in passages], batch_size=self.batch_size, show_progress_bar=False)
        return [float(x) for x in out]


def load_reranker(spec: str | None) -> Reranker | None:
    if not spec or spec.lower() == "none":
        return None
    if spec.startswith("st:"):
        return CrossEncoderReranker(spec[3:])
    raise ValueError(f"unknown reranker spec {spec!r} (expected 'st:<model>' or 'none')")
