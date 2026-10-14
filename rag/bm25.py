"""Okapi BM25 over pre-tokenized documents (postings-based, numpy only)."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np


class BM25:
    def __init__(self, docs_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(docs_tokens)
        self.doc_len = np.array([len(d) for d in docs_tokens], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if self.N else 0.0
        postings: dict[str, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
        for doc_id, toks in enumerate(docs_tokens):
            for term, tf in Counter(toks).items():
                postings[term][0].append(doc_id)
                postings[term][1].append(tf)
        self.postings = {
            t: (np.array(ids, dtype=np.int32), np.array(tfs, dtype=np.float32)) for t, (ids, tfs) in postings.items()
        }
        self.idf = {t: math.log((self.N - len(ids) + 0.5) / (len(ids) + 0.5) + 1.0) for t, (ids, _) in self.postings.items()}

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        out = np.zeros(self.N, dtype=np.float32)
        norm = self.k1 * (1 - self.b + self.b * self.doc_len / (self.avgdl or 1.0))
        for term in set(query_tokens):
            if term not in self.postings:
                continue
            ids, tfs = self.postings[term]
            out[ids] += self.idf[term] * tfs * (self.k1 + 1) / (tfs + norm[ids])
        return out
