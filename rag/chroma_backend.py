"""Chroma-backed implementation of Retrieval API v0.

Chroma is the persistent vector serving layer.  The Data team's PostgreSQL/RDS
database remains the system of record and is read only during an index build or
refresh.  To preserve the Experiment 1 hybrid baseline, dense candidates come
from Chroma while lexical candidates still use the repository's BM25 and the
two rankings are fused with the same reciprocal-rank-fusion implementation.

The public Agent-facing function remains ``rag.retrieve.retrieve``.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import numpy as np

from .bm25 import BM25
from .contract import (
    DEFAULT_TOP_K,
    RetrievalUnavailableError,
    RetrievedChunk,
    chunk_matches,
    normalize_filters,
    validate_query,
    validate_top_k,
)
from .embed import EmbeddingCache, get_embedder, load_embedder, save_embedder
from .index import index_text
from .text_utils import tokenize

METHODS = ("bm25", "dense", "hybrid")
DEFAULT_COLLECTION = "sec_filing_chunks"


def _chromadb():
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - exercised only in incomplete environments
        raise RetrievalUnavailableError(
            "Chroma backend selected but chromadb is not installed; run `pip install -r requirements.txt`"
        ) from exc
    return chromadb


def _flat_metadata(chunk: dict) -> dict:
    """Return Chroma-compatible scalar metadata without null values."""
    values = {
        "ticker": chunk.get("ticker"),
        "cik": str(chunk.get("cik", "")).zfill(10),
        "company_name": chunk.get("company_name", chunk.get("company", "")),
        "form": chunk.get("form"),
        "accession_number": chunk.get("accession_number", chunk.get("accession")),
        "filing_date": chunk.get("filing_date"),
        "reporting_period_end": chunk.get("reporting_period_end", chunk.get("period_of_report")),
        "fiscal_year": chunk.get("fiscal_year"),
        "fiscal_period": chunk.get("fiscal_period"),
        "section": chunk.get("section"),
        "section_title": chunk.get("section_title"),
        "is_table": bool(chunk.get("is_table", False)),
        "n_tokens": chunk.get("n_tokens"),
        "source_url": chunk.get("source_url"),
        "chunking_version": chunk.get("chunking_version") or "unversioned",
        "extraction_version": chunk.get("extraction_version") or "unversioned",
    }
    return {k: v for k, v in values.items() if v is not None and v != ""}


def _stored_chunk(chunk_id: str, document: str, metadata: dict) -> dict:
    """Map a Chroma record back to the repository's canonical stored-chunk shape."""
    return {
        "chunk_id": chunk_id,
        "text": document,
        "ticker": metadata.get("ticker"),
        "cik": metadata.get("cik"),
        "company": metadata.get("company_name", ""),
        "company_name": metadata.get("company_name", ""),
        "form": metadata.get("form"),
        "accession": metadata.get("accession_number"),
        "accession_number": metadata.get("accession_number"),
        "filing_date": metadata.get("filing_date"),
        "period_of_report": metadata.get("reporting_period_end"),
        "reporting_period_end": metadata.get("reporting_period_end"),
        "fiscal_year": metadata.get("fiscal_year"),
        "fiscal_period": metadata.get("fiscal_period"),
        "section": metadata.get("section"),
        "section_title": metadata.get("section_title", ""),
        "is_table": bool(metadata.get("is_table", False)),
        "n_tokens": metadata.get("n_tokens"),
        "source_url": metadata.get("source_url", ""),
        "chunking_version": metadata.get("chunking_version", "unversioned"),
        "extraction_version": metadata.get("extraction_version", "unversioned"),
    }


def build_chroma_index(
    chunks_path: str | Path,
    persist_dir: str | Path,
    embedder_spec: str,
    cache_dir: str | Path | None = None,
    collection_name: str = DEFAULT_COLLECTION,
    batch_size: int = 1000,
) -> dict:
    """Build a reproducible persistent Chroma collection from canonical chunks.jsonl."""
    started = time.time()
    chunks_path, persist_dir = Path(chunks_path), Path(persist_dir)
    raw = chunks_path.read_bytes()
    chunks = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not chunks:
        raise ValueError(f"No chunks in {chunks_path}")
    ids = [str(c["chunk_id"]) for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("chunk_id values must be unique before indexing in Chroma")

    texts_for_embedding = [index_text(c) for c in chunks]
    embedder = get_embedder(embedder_spec)
    if embedder_spec == "lsa":
        embedder.fit(texts_for_embedding)
        vectors = embedder.encode(texts_for_embedding)
        tokens = 0
    else:
        cache = EmbeddingCache(Path(cache_dir or persist_dir / "cache"), embedder_spec)
        vectors, tokens = cache.encode_with_cache(embedder, texts_for_embedding)

    persist_dir.mkdir(parents=True, exist_ok=True)
    save_embedder(embedder, persist_dir / "embedder.pkl")
    index_version = hashlib.sha1(raw).hexdigest()[:12]
    client = _chromadb().PersistentClient(path=str(persist_dir))
    try:
        client.get_collection(collection_name)
    except Exception:
        pass
    else:
        client.delete_collection(collection_name)
    collection = client.create_collection(
        collection_name,
        metadata={"hnsw:space": "cosine", "index_version": index_version, "embedder": embedder_spec},
    )
    for start in range(0, len(chunks), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=[c["text"] for c in chunks[start:end]],
            metadatas=[_flat_metadata(c) for c in chunks[start:end]],
            embeddings=np.asarray(vectors[start:end], dtype=np.float32).tolist(),
        )

    meta = {
        "backend": "chroma",
        "collection": collection_name,
        "index_version": index_version,
        "embedder": embedder_spec,
        "n_chunks": len(chunks),
        "dim": int(vectors.shape[1]),
        "embedding_api_tokens": tokens,
        "tickers": sorted({c.get("ticker") for c in chunks if c.get("ticker")}),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "build_seconds": round(time.time() - started, 1),
    }
    (persist_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[chroma-index] done: {meta}")
    return meta


class ChromaRetriever:
    """Contract-compatible dense/hybrid retriever backed by persistent Chroma."""

    def __init__(
        self,
        persist_dir: str | Path,
        log_dir: str | Path | None = "logs",
        rrf_k: int = 60,
        candidate_k: int = 100,
        method: str = "hybrid",
        collection_name: str = DEFAULT_COLLECTION,
    ):
        self.persist_dir = Path(persist_dir)
        meta_path = self.persist_dir / "meta.json"
        if not meta_path.exists():
            raise RetrievalUnavailableError(
                f"no Chroma index found at {self.persist_dir} (run `python -m rag.cli index --backend chroma`)"
            )
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        self.meta = json.loads(meta_path.read_text())
        self.client = _chromadb().PersistentClient(path=str(self.persist_dir))
        try:
            self.collection = self.client.get_collection(collection_name)
        except Exception as exc:
            raise RetrievalUnavailableError(
                f"Chroma collection {collection_name!r} is unavailable in {self.persist_dir}"
            ) from exc
        got = self.collection.get(include=["documents", "metadatas"])
        self.chunks = [
            _stored_chunk(str(cid), doc, metadata or {})
            for cid, doc, metadata in zip(got["ids"], got["documents"], got["metadatas"])
        ]
        self._by_id = {c["chunk_id"]: i for i, c in enumerate(self.chunks)}
        self._fields = [self._filter_fields(c) for c in self.chunks]
        self.bm25 = BM25([tokenize(index_text(c)) for c in self.chunks])
        self.embedder = load_embedder(self.meta["embedder"], self.persist_dir / "embedder.pkl")
        self.rrf_k, self.candidate_k, self.method = rrf_k, candidate_k, method
        self.log_path = Path(log_dir) / "retrieval.jsonl" if log_dir else None

    @staticmethod
    def _filter_fields(c: dict) -> dict:
        return {
            "ticker": c.get("ticker"),
            "cik": c.get("cik"),
            "form": c.get("form"),
            "accession_number": c.get("accession_number"),
            "filing_date": c.get("filing_date"),
            "reporting_period_end": c.get("reporting_period_end"),
            "fiscal_year": c.get("fiscal_year"),
            "fiscal_period": c.get("fiscal_period"),
            "section": c.get("section"),
            "is_table": c.get("is_table"),
        }

    def _mask(self, normalized_filters: dict) -> np.ndarray:
        if not normalized_filters:
            return np.ones(len(self.chunks), dtype=bool)
        return np.array([chunk_matches(f, normalized_filters) for f in self._fields], dtype=bool)

    def _chroma_where(self, normalized_filters: dict) -> dict | None:
        """Translate contract filters to Chroma while preserving section-prefix semantics."""
        clauses = []
        for key, allowed in normalized_filters.items():
            values = sorted(allowed)
            if key == "section":
                values = sorted(
                    {f["section"] for f in self._fields if f.get("section") and chunk_matches(f, {"section": allowed})}
                )
            if not values:
                continue
            clauses.append({key: values[0] if len(values) == 1 else {"$in": values}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def _rank_bm25(self, query: str, idx: np.ndarray) -> tuple[list[int], dict[int, float]]:
        scores = self.bm25.scores(tokenize(query))[idx]
        order = np.argsort(-scores, kind="stable")[: self.candidate_k]
        return (
            [int(idx[o]) for o in order if scores[o] > 0],
            {int(idx[o]): float(scores[o]) for o in order},
        )

    def _rank_dense(self, query: str, normalized_filters: dict, top_k: int):
        query_vector = self.embedder.encode([query], is_query=True)[0]
        where = self._chroma_where(normalized_filters)
        n_results = min(self.collection.count(), max(self.candidate_k, top_k))
        kwargs = {
            "query_embeddings": [query_vector.tolist()],
            "n_results": n_results,
            "include": ["distances"],
        }
        if where:
            kwargs["where"] = where
        got = self.collection.query(**kwargs)
        order, scores = [], {}
        for cid, distance in zip(got["ids"][0], got["distances"][0]):
            i = self._by_id.get(str(cid))
            if i is None or not chunk_matches(self._fields[i], normalized_filters):
                continue
            order.append(i)
            scores[i] = 1.0 - float(distance)
        return order, scores, self.embedder.tokens_used

    def retrieve(self, query: str, filters: dict | None = None, top_k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
        return self.search(query, filters, top_k, self.method)["results"]

    def search(
        self,
        query: str,
        filters: dict | None = None,
        top_k: int = DEFAULT_TOP_K,
        method: str | None = None,
    ) -> dict:
        from .retrieve import rrf, to_contract

        started = time.perf_counter()
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
        debug: dict[int, dict] = {}
        if len(idx) == 0:
            warnings.append("No chunks match the filters.")
        elif method == "bm25":
            order, scores = self._rank_bm25(query, idx)
            scored = [(i, scores[i]) for i in order]
        elif method == "dense":
            order, scores, tokens = self._rank_dense(query, nf, top_k)
            scored = [(i, scores[i]) for i in order]
        else:
            bm25_order, _ = self._rank_bm25(query, idx)
            dense_order, _, tokens = self._rank_dense(query, nf, top_k)
            scored = list(rrf([bm25_order, dense_order], self.rrf_k).items())
            bm25_pos = {doc: rank for rank, doc in enumerate(bm25_order, 1)}
            dense_pos = {doc: rank for rank, doc in enumerate(dense_order, 1)}
            debug = {
                doc: {"bm25_rank": bm25_pos.get(doc), "dense_rank": dense_pos.get(doc)}
                for doc, _ in scored
            }

        scored = [(doc, round(float(score), 6)) for doc, score in scored]
        scored.sort(key=lambda item: (-item[1], str(self.chunks[item[0]]["chunk_id"])))
        results = [
            to_contract(
                self.chunks[doc],
                rank,
                score,
                self.meta["index_version"],
                {"retrieval_method": method, "retrieval_backend": "chroma", "request_id": request_id, **debug.get(doc, {})},
            )
            for rank, (doc, score) in enumerate(scored[:top_k], start=1)
        ]
        response = {
            "request_id": request_id,
            "query": query,
            "filters": filters or {},
            "method": method,
            "backend": "chroma",
            "top_k": top_k,
            "index_version": self.meta["index_version"],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "tokens": {"query_embedding": tokens},
            "warnings": warnings,
            "results": results,
        }
        self._log(response, n_candidates=len(idx))
        return response

    def _log(self, response: dict, n_candidates: int) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **{
                key: response[key]
                for key in ("request_id", "query", "filters", "method", "backend", "top_k", "latency_ms", "index_version")
            },
            "query_embedding_tokens": response["tokens"]["query_embedding"],
            "n_candidates": n_candidates,
            "chunk_ids": [result["chunk_id"] for result in response["results"]],
            "scores": [result["score"] for result in response["results"]],
        }
        with open(self.log_path, "a") as stream:
            stream.write(json.dumps(row) + "\n")
