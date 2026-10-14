"""retrieve() — the tool the Agent team calls. Contract: docs/retrieval_api.md (v0), enforced in rag/contract.py.

Public API (what other teams use):
    from rag.retrieve import retrieve
    chunks = retrieve("What was Microsoft's total revenue?", filters={"ticker": "MSFT"}, top_k=10)

Internal / eval API:
    Retriever(index_dir).search(query, filters, top_k, method) -> envelope with request-level info
    (request_id, index_version, latency, warnings). Used by rag.evaluate and rag.cli.

Methods
  bm25    lexical (Okapi BM25)
  dense   cosine similarity on embeddings (brute force; fine for <1M chunks)
  hybrid  Reciprocal Rank Fusion of the two (Decision D1) — the default behind retrieve()
Metadata filters are applied BEFORE ranking (FinRank: filtering removes most hard negatives).
Every call is appended to logs/retrieval.jsonl (Decision D7).
"""
from __future__ import annotations

import json
import os
import pickle
import time
import uuid
from pathlib import Path

import numpy as np

from .contract import (
    DEFAULT_TOP_K,
    RetrievalUnavailableError,
    RetrievedChunk,
    chunk_matches,
    normalize_cik,
    normalize_filters,
    validate_query,
    validate_top_k,
)
from .embed import load_embedder
from .index import index_text  # noqa: F401  (re-exported for convenience)
from .text_utils import tokenize

METHODS = ("bm25", "dense", "hybrid")


def rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for r, doc in enumerate(ranks, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + r)
    return scores


def _filter_fields(c: dict) -> dict:
    """Filterable values of a stored chunk under the canonical v0 filter names."""
    return {
        "ticker": c.get("ticker"),
        "cik": c.get("cik"),
        "form": c.get("form"),
        "accession_number": c.get("accession_number", c.get("accession")),
        "filing_date": c.get("filing_date"),
        "reporting_period_end": c.get("reporting_period_end", c.get("period_of_report")),
        "fiscal_year": c.get("fiscal_year"),
        "fiscal_period": c.get("fiscal_period"),
        "section": c.get("section"),
        "is_table": c.get("is_table"),
    }


def to_contract(c: dict, rank: int, score: float, index_version: str, extra_meta: dict | None = None) -> RetrievedChunk:
    """Map a stored chunk record (rag.chunk format) to the v0 RetrievedChunk schema."""
    meta = {
        "section_title": c.get("section_title") or None,
        "fiscal_year": c.get("fiscal_year"),
        "fiscal_period": c.get("fiscal_period"),
        "is_table": bool(c.get("is_table", False)),
        "n_tokens": c.get("n_tokens"),
    }
    meta.update(extra_meta or {})
    section = c.get("section")
    return {
        "rank": rank,
        "chunk_id": str(c["chunk_id"]),
        "text": c["text"],
        "score": float(score),
        "section": section if section and section != "Unlabeled" else None,
        "ticker": c.get("ticker") or None,
        "cik": normalize_cik(c["cik"]),
        "company_name": c.get("company_name", c.get("company", "")),
        "form": c["form"],
        "accession_number": c.get("accession_number", c.get("accession")),
        "filing_date": c["filing_date"],
        "reporting_period_end": c.get("reporting_period_end", c.get("period_of_report")) or None,
        "source_url": c.get("source_url") or None,
        "chunking_version": c.get("chunking_version") or "unversioned",
        "extraction_version": c.get("extraction_version") or "unversioned",
        "index_version": index_version,
        "metadata": meta,
    }


class Retriever:
    def __init__(self, index_dir: str | Path, log_dir: str | Path | None = "logs", rrf_k: int = 60,
                 candidate_k: int = 100, method: str = "hybrid"):
        self.index_dir = Path(index_dir)
        if not (self.index_dir / "meta.json").exists():
            raise RetrievalUnavailableError(f"no index found at {self.index_dir} (run `make pilot` or `python -m rag.cli index`)")
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        self.meta = json.loads((self.index_dir / "meta.json").read_text())
        self.chunks = [json.loads(l) for l in open(self.index_dir / "chunks.jsonl") if l.strip()]
        with open(self.index_dir / "bm25.pkl", "rb") as f:
            self.bm25 = pickle.load(f)
        self.emb_matrix = np.load(self.index_dir / "embeddings.npy")
        self.embedder = load_embedder(self.meta["embedder"], self.index_dir / "embedder.pkl")
        self.rrf_k, self.candidate_k, self.method = rrf_k, candidate_k, method
        self.log_path = Path(log_dir) / "retrieval.jsonl" if log_dir else None
        self._fields = [_filter_fields(c) for c in self.chunks]

    # ---------- filtering ----------
    def _mask(self, nf: dict) -> np.ndarray:
        if not nf:
            return np.ones(len(self.chunks), dtype=bool)
        return np.array([chunk_matches(f, nf) for f in self._fields], dtype=bool)

    # ---------- rankers ----------
    def _rank_bm25(self, query: str, idx: np.ndarray) -> tuple[list[int], dict[int, float]]:
        s = self.bm25.scores(tokenize(query))[idx]
        order = np.argsort(-s, kind="stable")[: self.candidate_k]
        return [int(idx[o]) for o in order if s[o] > 0], {int(idx[o]): float(s[o]) for o in order}

    def _rank_dense(self, query: str, idx: np.ndarray):
        q = self.embedder.encode([query], is_query=True)[0]
        s = self.emb_matrix[idx] @ q
        order = np.argsort(-s, kind="stable")[: self.candidate_k]
        return [int(idx[o]) for o in order], {int(idx[o]): float(s[o]) for o in order}, self.embedder.tokens_used

    # ---------- public API ----------
    def retrieve(self, query: str, filters: dict | None = None, top_k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
        """Contract v0: ranked list of RetrievedChunk (possibly empty). Uses this Retriever's default method."""
        return self.search(query, filters, top_k, self.method)["results"]

    def search(self, query: str, filters: dict | None = None, top_k: int = DEFAULT_TOP_K, method: str | None = None) -> dict:
        """Envelope for eval/debugging: {request_id, index_version, latency_ms, warnings, results: [RetrievedChunk]}."""
        t0 = time.perf_counter()
        validate_query(query)
        validate_top_k(top_k)
        nf = normalize_filters(filters)
        method = method or self.method
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")

        request_id = uuid.uuid4().hex
        warnings, tokens = [], 0
        idx = np.flatnonzero(self._mask(nf))
        scored: list[tuple[int, float]] = []
        dbg: dict[int, dict] = {}

        if len(idx) == 0:
            warnings.append("No chunks match the filters.")
        elif method == "bm25":
            order, sc = self._rank_bm25(query, idx)
            scored = [(d, sc[d]) for d in order]
        elif method == "dense":
            order, sc, tokens = self._rank_dense(query, idx)
            scored = [(d, sc[d]) for d in order]
        else:
            b_order, _ = self._rank_bm25(query, idx)
            d_order, _, tokens = self._rank_dense(query, idx)
            scored = list(rrf([b_order, d_order], self.rrf_k).items())
            b_pos = {d: r for r, d in enumerate(b_order, 1)}
            d_pos = {d: r for r, d in enumerate(d_order, 1)}
            dbg = {d: {"bm25_rank": b_pos.get(d), "dense_rank": d_pos.get(d)} for d, _ in scored}

        # Deterministic order: score desc (as returned, 6 dp), then chunk_id asc.
        scored = [(d, round(float(s), 6)) for d, s in scored]
        scored.sort(key=lambda x: (-x[1], str(self.chunks[x[0]]["chunk_id"])))

        iv = self.meta["index_version"]
        results = [
            to_contract(self.chunks[d], rank, s, iv,
                        {"retrieval_method": method, "request_id": request_id, **dbg.get(d, {})})
            for rank, (d, s) in enumerate(scored[:top_k], start=1)
        ]
        resp = {
            "request_id": request_id,
            "query": query,
            "filters": filters or {},
            "method": method,
            "top_k": top_k,
            "index_version": iv,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tokens": {"query_embedding": tokens},
            "warnings": warnings,
            "results": results,
        }
        self._log(resp, n_candidates=len(idx))
        return resp

    def _log(self, resp: dict, n_candidates: int) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **{k: resp[k] for k in ("request_id", "query", "filters", "method", "top_k", "latency_ms", "index_version")},
            "query_embedding_tokens": resp["tokens"]["query_embedding"],
            "n_candidates": n_candidates,
            "chunk_ids": [r["chunk_id"] for r in resp["results"]],
            "scores": [r["score"] for r in resp["results"]],
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(row) + "\n")


# ---------- module-level tool (what the Agent imports) ----------
_DEFAULT: Retriever | None = None


def _default_retriever() -> Retriever:
    global _DEFAULT
    if _DEFAULT is None:
        index_dir = os.environ.get("RAG_INDEX_DIR")
        log_dir: str | Path | None = os.environ.get("RAG_LOG_DIR")
        if not index_dir or not log_dir:
            from .config import load_config

            paths = load_config()["paths"]
            index_dir = index_dir or paths["index"]
            log_dir = log_dir or paths["logs"]
        _DEFAULT = Retriever(index_dir, log_dir=log_dir)
    return _DEFAULT


def retrieve(query: str, filters: dict | None = None, top_k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
    """Retrieval API Contract v0.

    Returns up to `top_k` chunks ranked by relevance (score desc, then chunk_id asc); [] if nothing matches.
    Raises ValueError for invalid input; RetrievalUnavailableError if the index cannot be loaded.
    Index location: $RAG_INDEX_DIR, else config.yaml paths.index.
    """
    validate_query(query)
    validate_top_k(top_k)
    normalize_filters(filters)
    return _default_retriever().retrieve(query, filters, top_k)
