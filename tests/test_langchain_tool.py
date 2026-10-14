import pytest

from rag.langchain_tool import format_passages

CHUNK = {
    "rank": 1, "chunk_id": "abc", "text": "Total revenue was $82,886 million.", "score": 1.0,
    "section": "Part I Item 2", "ticker": "MSFT", "cik": "0000789019", "company_name": "MICROSOFT CORP",
    "form": "10-Q", "accession_number": "0001193125-26-191507", "filing_date": "2026-04-29",
    "reporting_period_end": "2026-03-31", "source_url": None, "chunking_version": "v", "extraction_version": "v",
    "index_version": "x", "metadata": {"fiscal_year": 2026, "fiscal_period": "Q3"},
}


def test_format_passages_has_citation_line():
    out = format_passages([CHUNK])
    assert out.startswith("[1] MSFT 10-Q Q3 FY2026 (period ending 2026-03-31) | Part I Item 2 | chunk abc")
    assert "82,886" in out


def test_format_passages_empty():
    assert "No matching passages" in format_passages([])


def test_tool_schema():
    pytest.importorskip("langchain_core")
    from rag.langchain_tool import make_sec_retrieval_tool

    tool = make_sec_retrieval_tool()
    assert tool.name == "sec_filing_search"
    assert set(tool.args) == {"query", "tickers", "form", "fiscal_year", "fiscal_period", "top_k"}
