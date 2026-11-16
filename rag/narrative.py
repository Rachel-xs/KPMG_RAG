"""Retrieval variants for narrative questions (#6 step 3). Experimental: compared on the dev set only.

Round 1 narrative misses (scripts/narrative_failure_table.py, 9 of 34 anchored-prose questions at hybrid @10):
  fusion     7/9  BM25 alone or dense alone has the evidence in its top 10, but RRF pushes it out
  scattered  3/9  the answer spans 2-3 chunks that sit next to each other in the filing
Variants (all return the same envelope as Retriever.search, so scoring code does not change):
  rrf         baseline: hybrid RRF (what final_v1 uses)
  union       the first `each` results of BM25 and of dense, interleaved (BM25 #1, dense #1, BM25 #2, ...),
              duplicates kept once, then filled up to top_k in RRF order          -> targets "fusion"
  neighbors   RRF results; the top `n_seed` results each bring their previous and next chunk from the same
              filing (same section only), inserted right after them; cut back to top_k  -> targets "scattered"
  union+neighbors  both
Every variant returns exactly top_k chunks (or fewer when the filter has fewer), so the reader's context size stays
comparable; compare at k=10 against rrf k=10 and at k=15 against rrf k=15.
"""
from __future__ import annotations

from .contract import normalize_filters

VARIANTS = ("rrf", "union", "neighbors", "union+neighbors")


def _seq_key(c: dict):
    return (c.get("accession_number") or c.get("accession"), c.get("seq"))


class NarrativeSearch:
    def __init__(self, retriever, each: int | None = None, n_seed: int = 3, window: int = 1):
        self.r = retriever
        self.each, self.n_seed, self.window = each, n_seed, window
        self._by_seq = {_seq_key(c): i for i, c in enumerate(retriever.chunks) if c.get("seq") is not None}
        self._by_id = {str(c["chunk_id"]): i for i, c in enumerate(retriever.chunks)}

    def search(self, query: str, filters: dict | None = None, top_k: int = 10, variant: str = "rrf",
               trace_id: str | None = None) -> dict:
        if variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}")
        pool_k = max(top_k * 3, 30)
        base = self.r.search(query, filters, pool_k, "hybrid", trace_id=trace_id)
        order = [r["chunk_id"] for r in base["results"]]
        neighbor_of: dict[str, str] = {}
        if "union" in variant:
            each = self.each or max(1, top_k // 2)
            b = [r["chunk_id"] for r in self.r.search(query, filters, each, "bm25")["results"]]
            d = [r["chunk_id"] for r in self.r.search(query, filters, each, "dense")["results"]]
            head = [x for pair in zip(b + [None] * (each - len(b)), d + [None] * (each - len(d))) for x in pair if x]
            order = list(dict.fromkeys(head + order))
        if "neighbors" in variant:
            nf = normalize_filters(filters)
            out, seen = [], set()
            for pos, cid in enumerate(order):
                if cid not in seen:
                    out.append(cid)
                    seen.add(cid)
                if pos < self.n_seed:
                    for nb in self._neighbors(cid, nf):
                        if nb not in seen:
                            out.append(nb)
                            seen.add(nb)
                            neighbor_of[nb] = cid
            order = out
        order = order[:top_k]
        meta_by_id = {r["chunk_id"]: r for r in base["results"]}
        results = []
        for rank, cid in enumerate(order, 1):
            if cid in meta_by_id:
                r = dict(meta_by_id[cid])
            else:
                from .retrieve import to_contract
                r = to_contract(self.r.chunks[self._by_id[cid]], rank, 0.0, self.r.meta["index_version"],
                                {"retrieval_method": "neighbor", "retrieval_backend": "custom"})
            r["rank"] = rank
            r["metadata"] = {**(r.get("metadata") or {}), "narrative_variant": variant,
                             **({"neighbor_of": neighbor_of[cid]} if cid in neighbor_of else {})}
            results.append(r)
        env = dict(base)
        env.update(results=results, top_k=top_k, method=f"hybrid/{variant}")
        return env

    def _neighbors(self, cid: str, nf: dict) -> list[str]:
        from .contract import chunk_matches
        from .retrieve import _filter_fields
        c = self.r.chunks[self._by_id[cid]]
        acc, seq = _seq_key(c)
        if seq is None:
            return []
        out = []
        for delta in [d for w in range(1, self.window + 1) for d in (-w, w)]:
            j = self._by_seq.get((acc, seq + delta))
            if j is None:
                continue
            n = self.r.chunks[j]
            if (n.get("section") or "") != (c.get("section") or ""):
                continue  # do not cross into another Item
            if nf and not chunk_matches(_filter_fields(n), nf):
                continue
            out.append(str(n["chunk_id"]))
        return out
