"""Offline tests on synthetic filings in tests/fixtures (no network, no API key)."""
import json
import shutil
from pathlib import Path

import pytest

from rag.bm25 import BM25
from rag.chunk import chunk_corpus, chunk_filing
from rag.evaluate import load_gold, run_eval, score_question
from rag.index import build_index
from rag.ingest import fiscal_label
from rag.parse import html_to_blocks
from rag.retrieve import Retriever, rrf

FX = Path(__file__).parent / "fixtures"


def _manifest():
    return [json.loads(l) for l in open(FX / "raw" / "manifest.jsonl")]


def _html(meta):
    return (FX / "raw" / meta["local_path"]).read_text()


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("idx")
    shutil.copytree(FX / "raw", tmp / "raw")
    chunk_corpus(tmp / "raw", tmp / "chunks.jsonl", 120, 200)
    build_index(tmp / "chunks.jsonl", tmp / "index", "lsa")
    return tmp


# ---------- ingest ----------
@pytest.mark.parametrize(
    "por,fye,form,expected",
    [
        ("2025-12-31", "1231", "10-K", (2025, "FY")),
        ("2025-03-31", "1231", "10-Q", (2025, "Q1")),
        ("2025-09-30", "1231", "10-Q", (2025, "Q3")),
        ("2025-04-27", "1102", "10-Q", (2025, "Q2")),   # Deere-style fiscal year (ends ~Nov 1)
        ("2025-01-26", "1102", "10-Q", (2025, "Q1")),
        ("2024-11-03", "1102", "10-K", (2024, "FY")),   # 52/53-week drift tolerated
        ("2024-12-29", "1102", "10-Q", (2025, "Q1")),   # early close of Q1 FY2025
    ],
)
def test_fiscal_label(por, fye, form, expected):
    assert fiscal_label(por, fye, form) == expected


# ---------- parse ----------
def test_parse_removes_hidden_xbrl_and_builds_tables():
    blocks = html_to_blocks(_html(_manifest()[0]))
    text = "\n".join(b["text"] for b in blocks)
    assert "HIDDENJUNK" not in text
    tables = [b for b in blocks if b["type"] == "table"]
    rev = [t for t in tables if "Total net revenue" in t["text"]][0]["text"]
    assert "| Total net revenue | $64,809 | $60,012 |" in rev and "(412)" in rev   # "$"/")" cells merged
    assert rev.startswith("|  | 2025 | 2024 |")                                   # header re-aligned
    # layout table with the Item 7 heading was flattened into a text line
    assert any(b["type"] == "text" and b["text"].startswith("Item 7.") for b in blocks)


# ---------- chunk ----------
def test_chunk_sections_10k():
    recs, rep = chunk_filing(_manifest()[0], _html(_manifest()[0]), 120, 200)
    assert rep["sections"] == ["Item 1", "Item 1A", "Item 7"]
    assert rep["section_coverage"] > 0.9
    risk = [r for r in recs if r["section"] == "Item 1A"]
    assert risk and all("RISK" in r["section_title"].upper() for r in risk)
    assert any("supply chain disruption" in r["text"].lower() for r in risk)
    tables = [r for r in recs if r["is_table"]]
    assert len(tables) == 1 and tables[0]["text"].startswith("Consolidated results of operations")
    assert all(r["n_tokens"] <= 200 for r in recs)
    assert len({r["chunk_id"] for r in recs}) == len(recs)


def test_chunk_sections_10q_uses_parts():
    recs, rep = chunk_filing(_manifest()[1], _html(_manifest()[1]), 120, 200)
    assert "Part II Item 1A" in rep["sections"] and "Part I Item 2" in rep["sections"]
    risk = [r for r in recs if r["section"] == "Part II Item 1A"]
    assert risk[0]["section_title"] == "Risk Factors"      # title taken from the next line
    assert not any(r["text"].strip() in ("Risk Factors", "PART II. OTHER INFORMATION") for r in recs)


# ---------- bm25 / rrf ----------
def test_bm25_prefers_matching_doc():
    bm = BM25([["tariff", "steel"], ["deposit", "bank"], ["steel", "steel", "mill"]])
    s = bm.scores(["steel"])
    assert s[1] == 0 and s[2] > s[0] > 0


def test_rrf():
    fused = rrf([[1, 2, 3], [3, 1]], k=60)
    assert max(fused, key=fused.get) == 1 and set(fused) == {1, 2, 3}


# ---------- retrieve ----------
def test_filters_are_applied_before_ranking(index_dir):
    r = Retriever(index_dir / "index", log_dir=index_dir / "logs")
    resp = r.search("risk factors", {"ticker": "BETA"}, top_k=10, method="hybrid")
    assert resp["results"] and all(x["ticker"] == "BETA" for x in resp["results"])
    resp = r.search("risk", {"ticker": "NOPE"}, top_k=5)
    assert resp["results"] == [] and resp["warnings"]


@pytest.mark.parametrize("method", ["bm25", "dense", "hybrid"])
def test_methods_find_the_revenue_table(index_dir, method):
    r = Retriever(index_dir / "index", log_dir=None)
    resp = r.search("ACME total net revenue and operating profit in millions", None, top_k=3, method=method)
    assert any(x["metadata"]["is_table"] for x in resp["results"])


def test_envelope_fields_and_logging(index_dir):
    r = Retriever(index_dir / "index", log_dir=index_dir / "logs")
    resp = r.search("capital ratio", {"ticker": "BETA", "fiscal_period": "Q2"}, top_k=2)
    for key in ("request_id", "query", "filters", "method", "top_k", "index_version", "latency_ms", "tokens", "warnings", "results"):
        assert key in resp
    res = resp["results"][0]
    assert res["metadata"]["request_id"] == resp["request_id"]
    log = (index_dir / "logs" / "retrieval.jsonl").read_text().strip().splitlines()
    assert json.loads(log[-1])["request_id"] == resp["request_id"]


# ---------- eval ----------
def test_score_question_metrics():
    q = {"gold": {"evidence": [{"ticker": "A", "contains": ["x"]}, {"ticker": "B"}]}, "expected": {"ticker": ["A", "B"]}}
    mk = lambda cid, t, txt: {"chunk_id": cid, "text": txt, "ticker": t, "metadata": {}}  # noqa: E731
    results = [mk("1", "C", "x"), mk("2", "A", "has x"), mk("3", "B", "y")]
    s = score_question(q, results, ks=(1, 3))
    assert s["mrr"] == 0.5
    assert s["evidence_recall@1"] == 0 and s["evidence_recall@3"] == 1
    assert s["provenance@3"] == pytest.approx(2 / 3)


def test_run_eval_end_to_end(index_dir):
    assert len(load_gold(FX / "gold_fixture.jsonl")) == 4          # unlabeled draft skipped
    summary = run_eval(index_dir / "index", FX / "gold_fixture.jsonl", index_dir / "results", ks=(3,), log_dir=None)
    hybrid = [s for s in summary if s["method"] == "hybrid" and s["filters"] == "filtered" and s["tier"] == "ALL"][0]
    assert hybrid["evidence_recall@3"] >= 0.75


# ---------- ingest (mocked EDGAR, no network) ----------
class _Resp:
    def __init__(self, payload=None, content=b""):
        self._p, self.content = payload, content

    def json(self):
        return self._p


class _FakeClient:
    """Mimics EDGAR: 'recent' lacks the 10-K, which only appears in an older paginated file."""

    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url.endswith("company_tickers.json"):
            return _Resp({"0": {"cik_str": 19617, "ticker": "JPM", "title": "JPMORGAN CHASE & CO"}})
        if url.endswith("CIK0000019617.json"):
            recent = {
                "form": ["424B2", "10-Q", "8-K", "10-Q", "10-K/A", "10-Q"],
                "accessionNumber": ["a-1", "a-2", "a-3", "a-4", "a-5", "a-6"],
                "filingDate": ["2026-09-01", "2026-08-01", "2026-07-15", "2026-05-01", "2026-04-01", "2025-11-01"],
                "reportDate": ["", "2026-06-30", "", "2026-03-31", "2025-12-31", "2025-09-30"],
                "primaryDocument": ["p.htm", "q2.htm", "e.htm", "q1.htm", "ka.htm", "q3.htm"],
            }
            return _Resp({"name": "JPMORGAN CHASE & CO", "fiscalYearEnd": "1231",
                          "filings": {"recent": recent, "files": [{"name": "CIK0000019617-submissions-001.json"}]}})
        if url.endswith("submissions-001.json"):
            return _Resp({"form": ["10-K"], "accessionNumber": ["a-7"], "filingDate": ["2026-02-14"],
                          "reportDate": ["2025-12-31"], "primaryDocument": ["k.htm"]})
        return _Resp(content=b"<html><body><p>filing</p></body></html>")


def test_download_filings_with_pagination(tmp_path):
    from rag.ingest import download_filings

    client = _FakeClient()
    man = download_filings(client, ["jpm"], {"10-K": 1, "10-Q": 2}, tmp_path)
    got = {(m["form"], m["accession"], m["fiscal_period"]) for m in man}
    assert got == {("10-Q", "a-2", "Q2"), ("10-Q", "a-4", "Q1"), ("10-K", "a-7", "FY")}   # 10-K/A skipped
    k = [m for m in man if m["form"] == "10-K"][0]
    assert k["source_url"] == "https://www.sec.gov/Archives/edgar/data/19617/a7/k.htm"
    assert (tmp_path / "JPM" / "a-7.htm").exists() and (tmp_path / "manifest.jsonl").exists()
    n = len(client.urls)
    download_filings(client, ["JPM"], {"10-K": 1, "10-Q": 2}, tmp_path)          # cached: no filing re-download
    assert not any(u.endswith(".htm") for u in client.urls[n:])
