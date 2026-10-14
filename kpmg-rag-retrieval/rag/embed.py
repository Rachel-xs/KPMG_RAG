"""Pluggable embedders. All return L2-normalised float32 arrays.

Specs (config.yaml -> retrieval.embedder):
  "st:BAAI/bge-small-en-v1.5"        sentence-transformers, local & free (default baseline)
  "st:intfloat/e5-base-v2"           another open-source option to benchmark
  "openai:text-embedding-3-small"    OpenAI API (needs OPENAI_API_KEY; costs money -> cached)
  "lsa"                              TF-IDF + SVD. Offline smoke tests only, NOT a real dense baseline.
"""
from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path

import numpy as np


def _normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)


class Embedder:
    spec = "base"
    tokens_used = 0  # API tokens consumed by the last encode() call

    def fit(self, texts: list[str]) -> None:  # only needed for corpus-fitted models (lsa)
        pass

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        raise NotImplementedError


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, keep lazy

        self.spec = f"st:{model_name}"
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def _prefix(self, is_query: bool) -> str:
        name = self.model_name.lower()
        if "e5" in name:
            return "query: " if is_query else "passage: "
        if "bge" in name and "en" in name and is_query:
            return "Represent this sentence for searching relevant passages: "
        return ""

    def encode(self, texts, is_query=False):
        self.tokens_used = 0
        p = self._prefix(is_query)
        vecs = self.model.encode([p + t for t in texts], batch_size=32, show_progress_bar=len(texts) > 200)
        return _normalize(vecs)


class OpenAIEmbedder(Embedder):
    def __init__(self, model_name: str):
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set (put it in .env, never commit it)")
        self.spec = f"openai:{model_name}"
        self.model_name = model_name
        self.client = OpenAI()

    def encode(self, texts, is_query=False):
        self.tokens_used = 0
        out = []
        for i in range(0, len(texts), 100):
            resp = self.client.embeddings.create(model=self.model_name, input=texts[i : i + 100])
            out += [d.embedding for d in resp.data]
            self.tokens_used += resp.usage.total_tokens
        return _normalize(np.array(out))


class LSAEmbedder(Embedder):
    spec = "lsa"

    def __init__(self, dims: int = 256):
        self.dims = dims
        self.vec = self.svd = None

    def fit(self, texts):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(sublinear_tf=True, max_features=50000, stop_words="english")
        X = self.vec.fit_transform(texts)
        n = max(2, min(self.dims, X.shape[0] - 1, X.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=n, random_state=0).fit(X)

    def encode(self, texts, is_query=False):
        self.tokens_used = 0
        return _normalize(self.svd.transform(self.vec.transform(texts)))


def get_embedder(spec: str) -> Embedder:
    if spec.startswith("st:"):
        return SentenceTransformerEmbedder(spec[3:])
    if spec.startswith("openai:"):
        return OpenAIEmbedder(spec[7:])
    if spec == "lsa":
        return LSAEmbedder()
    raise ValueError(f"Unknown embedder spec: {spec}")


def save_embedder(emb: Embedder, path: Path) -> None:
    """Persist corpus-fitted embedders (lsa). Model-based ones are re-loaded by spec."""
    if isinstance(emb, LSAEmbedder):
        with open(path, "wb") as f:
            pickle.dump(emb, f)


def load_embedder(spec: str, path: Path) -> Embedder:
    if spec == "lsa":
        with open(path, "rb") as f:
            return pickle.load(f)
    return get_embedder(spec)


class EmbeddingCache:
    """Disk cache keyed by (embedder spec, text hash) so re-indexing never re-pays for API calls."""

    def __init__(self, cache_dir: Path, spec: str):
        safe = spec.replace("/", "_").replace(":", "_")
        self.path = Path(cache_dir) / f"emb_{safe}.pkl"
        self.data: dict[str, np.ndarray] = {}
        if self.path.exists():
            with open(self.path, "rb") as f:
                self.data = pickle.load(f)

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def encode_with_cache(self, emb: Embedder, texts: list[str]) -> tuple[np.ndarray, int]:
        keys = [self.key(t) for t in texts]
        todo = [i for i, k in enumerate(keys) if k not in self.data]
        tokens = 0
        if todo:
            vecs = emb.encode([texts[i] for i in todo])
            tokens = emb.tokens_used
            for i, v in zip(todo, vecs):
                self.data[keys[i]] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "wb") as f:
                pickle.dump(self.data, f)
        print(f"[embed] {len(texts) - len(todo)} cached, {len(todo)} newly embedded ({tokens} API tokens)")
        return np.stack([self.data[k] for k in keys]), tokens
