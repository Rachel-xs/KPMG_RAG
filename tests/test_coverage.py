"""rag/coverage.py: deterministic pre-check (contract v1.3 draft)."""
from datetime import date

import pytest

from rag.coverage import CoverageIndex, Filing, extract_request


@pytest.fixture(scope="module")
def idx():
    return CoverageIndex([
        Filing("MSFT", "Microsoft Corporation", "10-Q", "A-MSFT-Q3", date(2026, 3, 31), 2026, "Q3"),
        Filing("MSFT", "Microsoft Corporation", "10-K", "A-MSFT-K", date(2026, 6, 30), 2026, "FY"),
        Filing("AAPL", "Apple Inc.", "10-Q", "A-AAPL-Q2", date(2026, 3, 28), 2026, "Q2"),
        Filing("CASY", "CASEY’S GENERAL STORES, INC.", "10-K", "A-CASY-K", date(2026, 4, 30), 2026, "FY"),
        Filing("NTAP", "NetApp, Inc.", "10-K", "A-NTAP-K", date(2026, 4, 24), 2026, "FY"),
    ])


@pytest.mark.parametrize("name,ticker,match", [
    ("MSFT", "MSFT", "ticker"), ("msft", "MSFT", "ticker"), ("Microsoft", "MSFT", "alias"),
    ("Microsoft Corp.", "MSFT", "alias"), ("Casey's", "CASY", "alias"), ("Caseys", "CASY", "alias"),
    ("Mcirosoft", "MSFT", "fuzzy"), ("Microsofft", "MSFT", "fuzzy"), ("Aplpe", "AAPL", "fuzzy"),
    ("NeAtpp", "NTAP", "fuzzy"), ("Tesla", None, None), ("Azure", None, None),
])
def test_resolve(idx, name, ticker, match):
    r = idx.resolve(name)
    assert (r["ticker"], r["match"]) == (ticker, match)


def test_all_hit_structured(idx):
    r = idx.check(tickers="MSFT", forms="10-Q", fiscal_years=2026, fiscal_periods="Q3")
    assert r["status"] == "all_hit"
    assert r["targets"][0]["accessions"] == ["A-MSFT-Q3"]
    assert r["filters"] == {"accession_number": ["A-MSFT-Q3"]}


def test_missing_period_is_none_and_lists_what_we_have(idx):
    r = idx.check(companies="Microsoft", period_ends="2026-09-30")
    assert r["status"] == "none"
    assert "MSFT" in r["message"] and "10-K FY2026 FY" in r["message"]
    assert r["filters"] is None


def test_unknown_company(idx):
    assert idx.check(companies="Tesla")["status"] == "unresolved"
    r = idx.check(companies=["Tesla", "Microsoft"], fiscal_years=2026, fiscal_periods="FY")
    assert r["status"] == "partial" and r["unresolved"] == ["Tesla"]


def test_partial_across_companies(idx):
    r = idx.check(tickers=["MSFT", "NTAP"], forms="10-Q")
    assert r["status"] == "partial"
    assert {t["ticker"]: t["status"] for t in r["targets"]} == {"MSFT": "hit", "NTAP": "miss"}


def test_no_company_is_no_target(idx):
    assert idx.check(fiscal_years=2026)["status"] == "no_target"


@pytest.mark.parametrize("d,status", [
    ("2026-03-31", "all_hit"),   # the quarter itself
    ("2025-03-31", "all_hit"),   # prior-year comparative column
    ("2025-06-30", "all_hit"),   # last fiscal year end (balance-sheet comparative in the 10-Q)
    ("2026-06-30", "all_hit"),   # 10-K
    ("2026-09-30", "none"),      # not filed yet in this corpus
])
def test_dates(idx, d, status):
    assert idx.check(tickers="MSFT", period_ends=d)["status"] == status


def test_52_week_calendar_tolerance(idx):
    assert idx.check(tickers="AAPL", period_ends="2026-03-31")["status"] == "all_hit"   # Apple closed 3/28


def test_q4_needs_the_10k(idx):
    assert idx.check(tickers="MSFT", fiscal_years=2026, fiscal_periods="Q4")["status"] == "all_hit"
    assert idx.check(tickers="MSFT", forms="10-Q", fiscal_years=2026, fiscal_periods="Q4")["status"] == "none"


def test_independent_mode_for_derived_question(idx):
    q = ("Using the FY2026 10-K and the Q3 FY2026 10-Q, derive Microsoft's revenue for the three months "
         "ended June 30, 2026.")
    req = extract_request(q, idx)
    assert idx.check(**req, combine="independent")["status"] == "all_hit"
    assert idx.check(**req)["status"] != "all_hit"   # the strict product makes no sense for free text


def test_extract_request(idx):
    r = extract_request("What was Mcirosoft’s total revenue for the three months ended March 31, 2026, per its 10-Q?", idx)
    assert [idx.resolve(c)["ticker"] for c in r["companies"]] == ["MSFT"]
    assert r["period_ends"] == ["2026-03-31"] and r["forms"] == ["10-Q"]
    r = extract_request("What was Micron's revenue for the first quarter of fiscal 2027?", idx)
    assert r["fiscal_years"] == [2027] and r["fiscal_periods"] == ["Q1"]
    r = extract_request("Which company had the highest revenue in the November 3, 2026 database snapshot?", idx)
    assert r["period_ends"] is None and r["companies"] is None


def test_no_fuzzy_on_ordinary_words(idx):
    r = extract_request("Explain the Revenue Recognition policy and Apply it to Quarterly Results.", idx)
    assert r["companies"] is None


def test_bad_fiscal_period(idx):
    with pytest.raises(ValueError):
        idx.check(tickers="MSFT", fiscal_periods="H1")


def test_langchain_coverage_tool(monkeypatch, idx):
    import rag.coverage as cov
    from rag.langchain_tool import make_coverage_tool
    monkeypatch.setattr(cov, "_DEFAULT", idx)
    tool = make_coverage_tool()
    msg = tool.invoke({"type": "tool_call", "id": "1", "name": tool.name,
                       "args": {"companies": ["Microsoft"], "period_ends": ["2026-09-30"]}})
    assert msg.artifact["status"] == "none" and "no filing" in msg.content.lower()
