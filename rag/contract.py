"""Retrieval API Contract v0 — single source of truth for inputs, filters, output schema and errors.

Human-readable spec: docs/retrieval_api.md. Anything here and there must agree; if they ever
disagree, this module is what the code enforces and the doc must be fixed.

Other teams can import `validate_chunk` / `REQUIRED_FIELDS` to check what they consume.
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

CONTRACT_VERSION = "v0"

DEFAULT_TOP_K = 10
MAX_TOP_K = 50

FISCAL_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")

# Names people used in earlier drafts / the Agent mock -> canonical v0 name (used only for error hints).
_RENAMED = {
    "form_type": "form",
    "accession": "accession_number",
    "period_of_report": "reporting_period_end",
    "k": "top_k (a function argument, not a filter)",
    "top_k": "top_k (a function argument, not a filter)",
    "company": "ticker or cik",
    "company_name": "ticker or cik",
}


class RetrievalError(RuntimeError):
    """Base class for infrastructure errors (never raised for a valid request with no matches)."""


class RetrievalUnavailableError(RetrievalError):
    """The index/backing store could not be loaded or queried."""


class RetrievedChunk(TypedDict):
    rank: int
    chunk_id: str
    text: str
    score: float
    section: str | None
    ticker: str | None
    cik: str
    company_name: str
    form: str
    accession_number: str
    filing_date: str
    reporting_period_end: str | None
    source_url: str | None
    chunking_version: str
    extraction_version: str
    index_version: str
    metadata: dict[str, Any]


# field -> (allowed python types, nullable)
REQUIRED_FIELDS: dict[str, tuple[tuple[type, ...], bool]] = {
    "rank": ((int,), False),
    "chunk_id": ((str,), False),
    "text": ((str,), False),
    "score": ((float, int), False),
    "section": ((str,), True),
    "ticker": ((str,), True),
    "cik": ((str,), False),
    "company_name": ((str,), False),
    "form": ((str,), False),
    "accession_number": ((str,), False),
    "filing_date": ((str,), False),
    "reporting_period_end": ((str,), True),
    "source_url": ((str,), True),
    "chunking_version": ((str,), False),
    "extraction_version": ((str,), False),
    "index_version": ((str,), False),
    "metadata": ((dict,), False),
}

# Documented optional keys inside `metadata` (consumers must use .get()).
METADATA_KEYS = {
    "section_title",      # str  human-readable section title, e.g. "Results of Operations"
    "fiscal_year",        # int  calendar year in which the fiscal year ends
    "fiscal_period",      # str  FY | Q1 | Q2 | Q3 | Q4
    "is_table",           # bool chunk is (part of) a table rendered as Markdown
    "n_tokens",           # int
    "retrieval_method",   # str  bm25 | dense | hybrid | mock_keyword_overlap
    "bm25_rank",          # int | None (hybrid only)
    "dense_rank",         # int | None (hybrid only)
    "request_id",         # str  joins the result to logs/retrieval.jsonl
}


# ---------------------------------------------------------------- normalizers
def normalize_cik(v: Any) -> str:
    s = str(v).strip()
    if isinstance(v, bool) or not s.isdigit() or len(s) > 10:
        raise ValueError(f"cik must be up to 10 digits, got {v!r}")
    return s.zfill(10)


def _norm_upper(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"expected a non-empty string, got {v!r}")
    return v.strip().upper()


def _norm_accession(v: Any) -> str:
    s = str(v).strip()
    if s.isdigit() and len(s) == 18:
        s = f"{s[:10]}-{s[10:12]}-{s[12:]}"
    if not _ACCESSION_RE.match(s):
        raise ValueError(f"accession_number must look like 0001193125-26-191507, got {v!r}")
    return s


def _norm_date(v: Any) -> str:
    s = str(v).strip()
    if not _DATE_RE.match(s):
        raise ValueError(f"dates must be YYYY-MM-DD, got {v!r}")
    return s


def _norm_year(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError(f"fiscal_year must be an integer, got {v!r}")
    try:
        y = int(str(v).strip())
    except ValueError:
        raise ValueError(f"fiscal_year must be an integer, got {v!r}") from None
    if not 1990 <= y <= 2100:
        raise ValueError(f"fiscal_year out of range: {v!r}")
    return y


def _norm_fiscal_period(v: Any) -> str:
    s = _norm_upper(v)
    if s not in FISCAL_PERIODS:
        raise ValueError(
            f"fiscal_period must be one of {sorted(FISCAL_PERIODS)}, got {v!r}. "
            "Durations such as 'three months ended' are not filters: put them in the query."
        )
    return s


def _norm_bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"is_table must be true/false, got {v!r}")
    return v


def _norm_section(v: Any) -> str:
    return " ".join(_norm_upper(v).split())


FILTER_NORMALIZERS = {
    "ticker": _norm_upper,
    "cik": normalize_cik,
    "form": _norm_upper,
    "accession_number": _norm_accession,
    "filing_date": _norm_date,
    "reporting_period_end": _norm_date,
    "fiscal_year": _norm_year,
    "fiscal_period": _norm_fiscal_period,
    "section": _norm_section,
    "is_table": _norm_bool,
}
FILTER_KEYS = frozenset(FILTER_NORMALIZERS)


# ---------------------------------------------------------------- validation
def validate_query(query: Any) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    return query


def validate_top_k(top_k: Any) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if top_k > MAX_TOP_K:
        raise ValueError(f"top_k must be <= {MAX_TOP_K}")
    return top_k


def normalize_filters(filters: Any) -> dict[str, set]:
    """Validate `filters` and return {key: set(normalized allowed values)}.

    - None / {} -> no filtering.  A key whose value is None is ignored.
    - Scalar value -> exact match. List/tuple/set -> OR within the key. Keys are ANDed.
    - Unknown keys and malformed values raise ValueError (never silently ignored).
    """
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be a dict or None")
    out: dict[str, set] = {}
    for key, val in filters.items():
        if key not in FILTER_NORMALIZERS:
            hint = f" (use '{_RENAMED[key]}')" if key in _RENAMED else ""
            raise ValueError(f"unsupported filter: {key}{hint}")
        if val is None:
            continue
        vals = list(val) if isinstance(val, (list, tuple, set, frozenset)) else [val]
        if not vals:
            raise ValueError(f"filter '{key}' must not be an empty list")
        try:
            out[key] = {FILTER_NORMALIZERS[key](v) for v in vals}
        except ValueError as e:
            raise ValueError(f"invalid value for filter '{key}': {e}") from None
    return out


def section_matches(chunk_section: str | None, allowed: set[str]) -> bool:
    """Case-insensitive match on whole words from the start: 'Part I' matches 'Part I Item 2'
    but not 'Part II Item 1'; 'Item 1' does not match 'Item 1A'."""
    if not chunk_section:
        return False
    s = _norm_section(chunk_section)
    return any(s == a or s.startswith(a + " ") for a in allowed)


def chunk_matches(fields: dict[str, Any], nf: dict[str, set]) -> bool:
    """`fields` holds the filterable values of one chunk under canonical filter names."""
    for key, allowed in nf.items():
        v = fields.get(key)
        if key == "section":
            if not section_matches(v, allowed):
                return False
            continue
        if v is None:
            return False
        try:
            nv = FILTER_NORMALIZERS[key](v)
        except ValueError:
            return False
        if nv not in allowed:
            return False
    return True


def validate_chunk(chunk: dict) -> None:
    """Raise ValueError if `chunk` does not satisfy the RetrievedChunk schema."""
    for field, (types, nullable) in REQUIRED_FIELDS.items():
        if field not in chunk:
            raise ValueError(f"missing field: {field}")
        v = chunk[field]
        if v is None:
            if not nullable:
                raise ValueError(f"field {field} must not be null")
            continue
        if isinstance(v, bool) or not isinstance(v, types):
            raise ValueError(f"field {field} has type {type(v).__name__}")
    if chunk["rank"] < 1:
        raise ValueError("rank must be >= 1")
    if len(chunk["cik"]) != 10 or not chunk["cik"].isdigit():
        raise ValueError("cik must be a 10-digit string")


def validate_results(results: list, top_k: int) -> None:
    """Check list-level guarantees: length, ranks 1..n, score order, deterministic tie-break."""
    if not isinstance(results, list):
        raise ValueError("retrieve() must return a list")
    if len(results) > top_k:
        raise ValueError("more results than top_k")
    for i, c in enumerate(results, start=1):
        validate_chunk(c)
        if c["rank"] != i:
            raise ValueError("ranks must be 1..n in order")
    for a, b in zip(results, results[1:]):
        if (-a["score"], a["chunk_id"]) > (-b["score"], b["chunk_id"]):
            raise ValueError("results must be sorted by score desc, then chunk_id asc")
