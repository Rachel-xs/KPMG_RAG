"""Build the BM25 + dense index from chunks.jsonl (one-command rebuild).

Each chunk is indexed with a short contextual header, e.g.
  "JPMORGAN CHASE & CO (JPM) 10-K FY2025 | Item 1A Risk Factors"
so that company / period / section words are searchable even when the body never repeats them.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path

import numpy as np

from .bm25 import BM25
from .embed import EmbeddingCache, get_embedder, save_embedder
from .text_utils import tokenize


def index_text(c: dict) -> str:
    period = f"{c['fiscal_period']}{c['fiscal_year']}" if c["fiscal_period"] != "FY" else f"FY{c['fiscal_year']}"
    head = f"{c['company']} ({c['ticker']}) {c['form']} {period} | {c['section']} {c['section_title']}".strip()
    return f"{head}\n{c['text']}"


def build_index(chunks_path: Path, index_dir: Path, embedder_spec: str, cache_dir: Path | None = None) -> dict:
    t0 = time.time()
    chunks_path, index_dir = Path(chunks_path), Path(index_dir)
    raw = chunks_path.read_bytes()
    chunks = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    if not chunks:
        raise ValueError(f"No chunks in {chunks_path}")
    texts = [index_text(c) for c in chunks]
    index_dir.mkdir(parents=True, exist_ok=True)

    print(f"[index] BM25 over {len(chunks)} chunks")
    bm25 = BM25([tokenize(t) for t in texts])

    print(f"[index] dense embeddings with {embedder_spec}")
    emb = get_embedder(embedder_spec)
    tokens = 0
    if embedder_spec == "lsa":
        emb.fit(texts)
        vecs = emb.encode(texts)
    else:
        cache = EmbeddingCache(cache_dir or index_dir / "cache", embedder_spec)
        vecs, tokens = cache.encode_with_cache(emb, texts)

    (index_dir / "chunks.jsonl").write_bytes(raw)
    with open(index_dir / "bm25.pkl", "wb") as f:
        pickle.dump(bm25, f)
    np.save(index_dir / "embeddings.npy", vecs.astype(np.float32))
    save_embedder(emb, index_dir / "embedder.pkl")
    meta = {
        "index_version": hashlib.sha1(raw).hexdigest()[:12],
        "embedder": embedder_spec,
        "n_chunks": len(chunks),
        "dim": int(vecs.shape[1]),
        "embedding_api_tokens": tokens,
        "tickers": sorted({c["ticker"] for c in chunks}),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "build_seconds": round(time.time() - t0, 1),
    }
    (index_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[index] done: {meta}")
    return meta
