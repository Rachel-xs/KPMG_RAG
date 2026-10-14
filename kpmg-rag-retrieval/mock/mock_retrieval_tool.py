"""
Mock retrieve() for Agent integration testing — conforms to Retrieval API Contract v0
(docs/retrieval_api.md).

Same signature, filters, output schema, ordering and errors as the real tool, so Agent code
written against this file works unchanged when you switch to:

    from rag.retrieve import retrieve

Important:
- Mock only: 6 chunks from the Microsoft 10-Q (accession 0001193125-26-191507), keyword-overlap
  scoring. No LLM, embeddings, BM25 or vector database.
- Prose chunks are verbatim filing text; table chunks keep selected rows verbatim (others omitted)
  and are flattened. Whitespace is collapsed.
- Chunk IDs are placeholders. Do not parse chunk_id; treat it as an opaque string.
- Gold-set questions and reference answers are NOT included (no benchmark leakage).
- Standalone: standard library only.
"""

from __future__ import annotations

import re
from math import sqrt

CONTRACT_VERSION = "v0"
DEFAULT_TOP_K = 10
MAX_TOP_K = 50

SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/"
    "789019/000119312526191507/msft-20260331.htm"
)

_FILING = {
    "ticker": "MSFT",
    "cik": "0000789019",
    "company_name": "Microsoft Corporation",
    "form": "10-Q",
    "accession_number": "0001193125-26-191507",
    "filing_date": "2026-04-29",
    "reporting_period_end": "2026-03-31",
    "source_url": SOURCE_URL,
    "chunking_version": "mock-v0",
    "extraction_version": "mock-v0",
    "index_version": "mock-v0",
}
# Microsoft's fiscal year ends June 30, so the quarter ended March 31, 2026 is Q3 FY2026.
_FISCAL = {"fiscal_year": 2026, "fiscal_period": "Q3"}


def _chunk(seq, section, section_title, is_table, text):
    return {
        "chunk_id": f"MSFT-0001193125-26-191507-{seq:04d}",
        "section": section,
        "section_title": section_title,
        "is_table": is_table,
        "text": text,
    }


MOCK_CHUNKS = [
    _chunk(1, "Part I Item 1", "Income Statements", True,
           "INCOME STATEMENTS (In millions, except per share amounts) (Unaudited) Three Months Ended "
           "March 31, Nine Months Ended March 31, 2026 2025 2026 2025 Revenue: Product $ 15,089 $ 15,319 "
           "$ 47,462 $ 46,810 Service and other 67,797 54,747 194,370 158,473 Total revenue 82,886 70,066 "
           "241,832 205,283 Total cost of revenue 26,828 21,919 76,849 63,817 Gross margin 56,058 48,147 "
           "164,983 141,466 Operating income 38,398 32,000 114,634 94,205 Net income $ 31,778 $ 25,824 "
           "$ 97,983 $ 74,599"),
    _chunk(2, "Part I Item 1", "Cash Flows Statements", True,
           "CASH FLOWS STATEMENTS (In millions) (Unaudited) Three Months Ended March 31, Nine Months Ended "
           "March 31, 2026 2025 2026 2025 Net cash from operations 46,679 37,044 127,494 93,515 Net cash "
           "used in financing (11,351 ) (13,036 ) (40,767 ) (40,855 ) Additions to property and equipment "
           "(30,876 ) (16,745 ) (80,146 ) (47,472 ) Net cash used in investing (27,405 ) (12,714 ) "
           "(84,669 ) (42,027 ) Net change in cash and cash equivalents 7,809 11,346 1,863 10,513"),
    _chunk(3, "Part I Item 1", "Note 16 — Segment Information and Geographic Data", True,
           "(In millions) Three Months Ended March 31, Nine Months Ended March 31, 2026 2025 2026 2025 "
           "Productivity and Business Processes Revenue $ 35,013 $ 29,944 $ 102,149 $ 87,698 Operating "
           "income $ 20,973 $ 17,379 $ 61,979 $ 50,780 Intelligent Cloud Revenue $ 34,681 $ 26,751 "
           "$ 98,485 $ 76,387 Operating income $ 13,753 $ 11,095 $ 41,017 $ 32,449 More Personal Computing "
           "Revenue $ 13,192 $ 13,371 $ 41,198 $ 41,198 Operating income $ 3,672 $ 3,526 $ 11,638 $ 10,976"),
    _chunk(4, "Part I Item 1", "Note 16 — Segment Information and Geographic Data", False,
           "Our Microsoft Cloud revenue, which includes Microsoft 365 Commercial cloud, Azure and other "
           "cloud services, the commercial portion of LinkedIn, and Dynamics 365, was $54.5 billion and "
           "$155.1 billion for the three and nine months ended March 31, 2026, respectively, and $42.4 "
           "billion and $122.2 billion for the three and nine months ended March 31, 2025, respectively."),
    _chunk(5, "Part I Item 1", "Note 11 — Remaining Performance Obligations", False,
           "Revenue allocated to remaining performance obligations, which includes unearned revenue and "
           "amounts expected to be invoiced and recognized as revenue in future periods, was $633 billion "
           "as of March 31, 2026."),
    _chunk(6, "Part I Item 2", "Management's Discussion and Analysis — Overview", False,
           "Three Months Ended March 31, 2026 Compared with Three Months Ended March 31, 2025 Revenue "
           "increased $12.8 billion or 18% driven by growth in Microsoft Cloud. Intelligent Cloud revenue "
           "increased driven by Azure. Productivity and Business Processes revenue increased driven by "
           "Microsoft 365 Commercial cloud. More Personal Computing revenue decreased with lower hardware "
           "sales across Devices and Gaming, offset in part by growth in Search advertising."),
]


class RetrievalUnavailableError(RuntimeError):
    """Raised when the index cannot be loaded (never for a valid query with no matches)."""


# ------------------------------------------------------------------ filters
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACC_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_RENAMED = {"form_type": "form", "accession": "accession_number",
            "period_of_report": "reporting_period_end", "k": "top_k", "top_k": "top_k"}


def _upper(v):
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"expected a non-empty string, got {v!r}")
    return v.strip().upper()


def _cik(v):
    s = str(v).strip()
    if isinstance(v, bool) or not s.isdigit() or len(s) > 10:
        raise ValueError(f"cik must be up to 10 digits, got {v!r}")
    return s.zfill(10)


def _acc(v):
    s = str(v).strip()
    if s.isdigit() and len(s) == 18:
        s = f"{s[:10]}-{s[10:12]}-{s[12:]}"
    if not _ACC_RE.match(s):
        raise ValueError(f"bad accession_number {v!r}")
    return s


def _date(v):
    if not _DATE_RE.match(str(v).strip()):
        raise ValueError(f"dates must be YYYY-MM-DD, got {v!r}")
    return str(v).strip()


def _year(v):
    if isinstance(v, bool):
        raise ValueError("fiscal_year must be an integer")
    return int(str(v).strip())


def _period(v):
    s = _upper(v)
    if s not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
        raise ValueError(f"fiscal_period must be FY/Q1/Q2/Q3/Q4, got {v!r}; put durations in the query")
    return s


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("is_table must be true/false")
    return v


def _section(v):
    return " ".join(_upper(v).split())


_NORMALIZERS = {
    "ticker": _upper, "cik": _cik, "form": _upper, "accession_number": _acc,
    "filing_date": _date, "reporting_period_end": _date, "fiscal_year": _year,
    "fiscal_period": _period, "section": _section, "is_table": _bool,
}


def _normalize_filters(filters):
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be a dict or None")
    out = {}
    for key, val in filters.items():
        if key not in _NORMALIZERS:
            hint = f" (use '{_RENAMED[key]}')" if key in _RENAMED else ""
            raise ValueError(f"unsupported filter: {key}{hint}")
        if val is None:
            continue
        vals = list(val) if isinstance(val, (list, tuple, set, frozenset)) else [val]
        if not vals:
            raise ValueError(f"filter '{key}' must not be an empty list")
        try:
            out[key] = {_NORMALIZERS[key](v) for v in vals}
        except ValueError as e:
            raise ValueError(f"invalid value for filter '{key}': {e}") from None
    return out


def _matches(item, nf):
    for key, allowed in nf.items():
        if key == "section":
            s = _section(item["section"]) if item.get("section") else ""
            if not any(s == a or s.startswith(a + " ") for a in allowed):
                return False
            continue
        if _NORMALIZERS[key](item[key]) not in allowed:
            return False
    return True


# ------------------------------------------------------------------ scoring
def _tokenize(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _mock_score(query, passage):
    q, p = _tokenize(query), _tokenize(passage)
    if not q or not p:
        return 0.0
    return round(len(q & p) / sqrt(len(q) * len(p)), 6)


# ------------------------------------------------------------------ public API
def retrieve(query, filters=None, top_k=DEFAULT_TOP_K):
    """Retrieval API Contract v0 (mock).

    Returns list[RetrievedChunk] ordered by score desc, then chunk_id asc; [] if nothing matches.
    Raises ValueError for invalid query / top_k / filters.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if top_k > MAX_TOP_K:
        raise ValueError(f"top_k must be <= {MAX_TOP_K}")
    nf = _normalize_filters(filters)

    rows = [{**_FILING, **_FISCAL, **c} for c in MOCK_CHUNKS]
    rows = [r for r in rows if _matches(r, nf)]
    scored = [(_mock_score(query, r["text"]), r) for r in rows]
    scored = [(s, r) for s, r in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], x[1]["chunk_id"]))

    results = []
    for rank, (score, r) in enumerate(scored[:top_k], start=1):
        results.append({
            "rank": rank,
            "chunk_id": r["chunk_id"],
            "text": r["text"],
            "score": float(score),
            "section": r["section"],
            "ticker": r["ticker"],
            "cik": r["cik"],
            "company_name": r["company_name"],
            "form": r["form"],
            "accession_number": r["accession_number"],
            "filing_date": r["filing_date"],
            "reporting_period_end": r["reporting_period_end"],
            "source_url": r["source_url"],
            "chunking_version": r["chunking_version"],
            "extraction_version": r["extraction_version"],
            "index_version": r["index_version"],
            "metadata": {
                "section_title": r["section_title"],
                "fiscal_year": r["fiscal_year"],
                "fiscal_period": r["fiscal_period"],
                "is_table": r["is_table"],
                "retrieval_method": "mock_keyword_overlap",
            },
        })
    return results


if __name__ == "__main__":
    for res in retrieve(
        "What was Microsoft's total revenue for the three months ended March 31, 2026?",
        filters={"ticker": "MSFT", "form": "10-Q", "reporting_period_end": "2026-03-31"},
        top_k=3,
    ):
        print(f"#{res['rank']} score={res['score']:.4f} {res['chunk_id']} | {res['section']} — "
              f"{res['metadata']['section_title']}")
        print("   ", res["text"][:160], "...\n")
