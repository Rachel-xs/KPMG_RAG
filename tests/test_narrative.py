"""rag/narrative.py: retrieval variants for narrative questions."""
import shutil
from pathlib import Path

import pytest

from rag.chunk import chunk_corpus
from rag.index import build_index
from rag.narrative import NarrativeSearch
from rag.retrieve import Retriever

FX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ns(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("narr")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    return NarrativeSearch(Retriever(tmp / "index", log_dir=None), n_seed=2)


Q = "revenue growth explanation"


@pytest.mark.parametrize("variant", ["rrf", "union", "neighbors", "union+neighbors"])
def test_size_and_ranks(ns, variant):
    env = ns.search(Q, top_k=5, variant=variant)
    res = env["results"]
    assert len(res) == 5
    assert [r["rank"] for r in res] == [1, 2, 3, 4, 5]
    assert len({r["chunk_id"] for r in res}) == 5
    assert all(r["metadata"]["narrative_variant"] == variant for r in res)


def test_rrf_matches_plain_hybrid(ns):
    a = [r["chunk_id"] for r in ns.search(Q, top_k=5, variant="rrf")["results"]]
    b = [r["chunk_id"] for r in ns.r.search(Q, None, 5, "hybrid")["results"]]
    assert a == b


def test_union_starts_with_each_methods_top(ns):
    res = ns.search(Q, top_k=6, variant="union")["results"]
    b1 = ns.r.search(Q, None, 1, "bm25")["results"][0]["chunk_id"]
    d1 = ns.r.search(Q, None, 1, "dense")["results"][0]["chunk_id"]
    assert res[0]["chunk_id"] == b1
    assert d1 in [r["chunk_id"] for r in res[:2]]


def test_neighbors_are_adjacent_same_filing_and_section(ns):
    res = ns.search(Q, top_k=8, variant="neighbors")["results"]
    by_id = {str(c["chunk_id"]): c for c in ns.r.chunks}
    added = [r for r in res if r["metadata"].get("neighbor_of")]
    assert added, "expected at least one neighbour to be pulled in"
    for r in added:
        c, seed = by_id[r["chunk_id"]], by_id[r["metadata"]["neighbor_of"]]
        assert c["accession"] == seed["accession"]
        assert abs(c["seq"] - seed["seq"]) == 1
        assert (c.get("section") or "") == (seed.get("section") or "")
        # it sits right after its seed (or after the seed's other neighbour)
        pos = {x["chunk_id"]: x["rank"] for x in res}
        assert 0 < pos[r["chunk_id"]] - pos[seed["chunk_id"]] <= 2


def test_neighbors_respect_filters(ns):
    res = ns.search(Q, {"ticker": "ACME"}, top_k=6, variant="neighbors")["results"]
    assert res and all(r["ticker"] == "ACME" for r in res)


def test_bad_variant(ns):
    with pytest.raises(ValueError):
        ns.search(Q, variant="magic")
