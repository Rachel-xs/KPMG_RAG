"""Retrieval API Contract v0 conformance tests (docs/retrieval_api.md).

The same checks run against the real retrieve() and the Agent mock, so the two cannot drift apart.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

import rag.retrieve as rr
from rag.chunk import chunk_corpus
from rag.contract import (
    MAX_TOP_K,
    RetrievalUnavailableError,
    normalize_filters,
    section_matches,
    validate_chunk,
    validate_results,
)
from rag.index import build_index

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).parent / "fixtures"


def _load_mock():
    spec = importlib.util.spec_from_file_location("mock_retrieval_tool", ROOT / "mock" / "mock_retrieval_tool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def real_retrieve(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("contract")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    mp = pytest.MonkeyPatch()
    mp.setenv("RAG_INDEX_DIR", str(tmp / "index"))
    mp.setenv("RAG_LOG_DIR", str(tmp / "logs"))
    rr._DEFAULT = None
    yield rr.retrieve
    rr._DEFAULT = None
    mp.undo()


MOCK = _load_mock()

# (implementation, a query that should hit, a filter set that matches nothing, an exact-match ticker)
CASES = {
    "real": ("real", "total net revenue operating profit", {"ticker": "NOPE"}, "ACME"),
    "mock": ("mock", "Microsoft total revenue", {"ticker": "NOPE"}, "MSFT"),
}


@pytest.fixture(params=list(CASES))
def impl(request, real_retrieve):
    name, q, nomatch, ticker = CASES[request.param]
    fn = real_retrieve if name == "real" else MOCK.retrieve
    return fn, q, nomatch, ticker


# ---------- output ----------
def test_schema_and_ordering(impl):
    fn, q, _, _ = impl
    res = fn(q)
    assert res, "expected at least one result"
    validate_results(res, top_k=10)


def test_top_k_bounds_result_length(impl):
    fn, q, _, _ = impl
    assert len(fn(q, top_k=1)) <= 1
    validate_results(fn(q, top_k=2), top_k=2)


def test_deterministic(impl):
    fn, q, _, _ = impl
    a = [(r["chunk_id"], r["score"]) for r in fn(q, top_k=5)]
    b = [(r["chunk_id"], r["score"]) for r in fn(q, top_k=5)]
    assert a == b


def test_no_match_returns_empty_list(impl):
    fn, q, nomatch, _ = impl
    assert fn(q, filters=nomatch) == []


def test_filters_restrict_results(impl):
    fn, q, _, ticker = impl
    res = fn(q, filters={"ticker": ticker.lower(), "form": None})       # case-insensitive; None ignored
    assert res and all(r["ticker"] == ticker for r in res)
    res = fn(q, filters={"ticker": [ticker, "NOPE"]})                      # list = OR
    assert res and all(r["ticker"] == ticker for r in res)


def test_cik_is_normalized(impl):
    fn, q, _, _ = impl
    res = fn(q)
    cik = res[0]["cik"]
    assert len(cik) == 10 and cik.isdigit()
    assert fn(q, filters={"cik": int(cik)})                               # int or unpadded str accepted


# ---------- input errors ----------
@pytest.mark.parametrize("query", ["", "   ", None, 3])
def test_bad_query(impl, query):
    fn = impl[0]
    with pytest.raises(ValueError, match="query must be a non-empty string"):
        fn(query)


@pytest.mark.parametrize("top_k", [0, -5, 2.5, True, "10"])
def test_bad_top_k(impl, top_k):
    fn, q, _, _ = impl
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        fn(q, top_k=top_k)


def test_top_k_cap(impl):
    fn, q, _, _ = impl
    with pytest.raises(ValueError, match="top_k must be <="):
        fn(q, top_k=MAX_TOP_K + 1)


@pytest.mark.parametrize(
    "filters,msg",
    [
        ({"random_field": "abc"}, "unsupported filter: random_field"),
        ({"form_type": "10-Q"}, "use 'form'"),
        ({"accession": "0001193125-26-191507"}, "use 'accession_number'"),
        ({"fiscal_period": "three_months_ended_2026-03-31"}, "put"),
        ({"filing_date": "04/29/2026"}, "YYYY-MM-DD"),
        ({"ticker": []}, "must not be an empty list"),
        ({"is_table": "yes"}, "is_table"),
        ("MSFT", "filters must be a dict"),
    ],
)
def test_bad_filters(impl, filters, msg):
    fn, q, _, _ = impl
    with pytest.raises(ValueError, match=msg):
        fn(q, filters=filters)


# ---------- unit checks on the contract module ----------
def test_section_matching_is_word_prefix():
    allowed = normalize_filters({"section": "Part I"})["section"]
    assert section_matches("Part I Item 2", allowed)
    assert not section_matches("Part II Item 1A", allowed)
    assert not section_matches("Item 1A", normalize_filters({"section": "Item 1"})["section"])


def test_accession_without_dashes_is_accepted():
    assert normalize_filters({"accession_number": "000119312526191507"})["accession_number"] == {"0001193125-26-191507"}


def test_validate_chunk_rejects_missing_fields():
    with pytest.raises(ValueError, match="missing field"):
        validate_chunk({"chunk_id": "x"})


def test_missing_index_raises_unavailable(tmp_path):
    with pytest.raises(RetrievalUnavailableError):
        rr.Retriever(tmp_path / "nothing-here")


def test_evidence_item_chunk_ids_are_any_of():
    from rag.evaluate import score_question

    q = {"gold": {"evidence": [{"chunk_ids": ["a", "b"]}, {"ticker": "X", "contains": ["rev"]}]}}
    mk = lambda cid, t, txt: {"chunk_id": cid, "text": txt, "ticker": t, "metadata": {}}  # noqa: E731
    s = score_question(q, [mk("b", "Y", "z"), mk("c", "X", "rev up")], ks=(2,))
    assert s["evidence_recall@2"] == 1.0 and s["mrr"] == 1.0
