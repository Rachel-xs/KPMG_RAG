"""LangChain wrapper around `retrieve()` for the Agent team.

    from rag.langchain_tool import make_sec_retrieval_tool
    tool = make_sec_retrieval_tool()          # a LangChain StructuredTool named "sec_filing_search"
    agent = create_react_agent(llm, [tool])   # or bind_tools([tool]) / AgentExecutor ...

What the LLM sees: compact, numbered passages, each with a citation line
    [1] MSFT 10-Q Q3 FY2026 (period ending 2026-03-31) | Part I Item 2 | chunk 59fa6620-...
What your code gets: the full Retrieval API v0 chunks (docs/retrieval_api.md) as the tool message's
`artifact`, so citations / provenance never depend on the LLM copying ids correctly.

Index location: $RAG_INDEX_DIR, else config.yaml paths.index (see rag.retrieve.retrieve).
Bad arguments (unknown form, top_k out of range...) come back as a short error text the LLM can fix,
not as an exception; an index that cannot be loaded still raises RetrievalUnavailableError.
"""
from __future__ import annotations

from typing import Literal, Optional

from .contract import RetrievalUnavailableError
from .retrieve import retrieve

TOOL_NAME = "sec_filing_search"
TOOL_DESCRIPTION = (
    "Search the text of SEC 10-K and 10-Q filings and return the most relevant passages with citations. "
    "Use it for any question about what a company reported (revenue, segments, risks, guidance, accounting). "
    "Always pass `tickers` when the question names a company, and `form` / `fiscal_year` / `fiscal_period` "
    "when it names a report or period: filters strongly improve accuracy. "
    "fiscal_year = the year the company's fiscal year ENDS (Microsoft FY2026 = Jul 2025 - Jun 2026). "
    "For comparisons across companies or periods, call the tool once per company/period. "
    "Cite passages by their [n] number; if no passage contains the answer, say so."
)
MAX_CHARS_PER_PASSAGE = 1800


def _period_label(c: dict) -> str:
    m = c.get("metadata", {})
    fy, fp = m.get("fiscal_year"), m.get("fiscal_period")
    label = f"FY{fy}" if fp == "FY" else f"{fp} FY{fy}" if fy and fp else ""
    end = c.get("reporting_period_end")
    return f"{label} (period ending {end})" if end else label


def format_passages(chunks: list[dict], max_chars: int = MAX_CHARS_PER_PASSAGE) -> str:
    """Numbered passages with a citation line each; what the LLM reads."""
    if not chunks:
        return "No matching passages. Try fewer filters or different wording."
    out = []
    for i, c in enumerate(chunks, 1):
        head = " | ".join(
            x for x in (
                f"{c.get('ticker') or c.get('company_name')} {c.get('form')} {_period_label(c)}".strip(),
                c.get("section") or "",
                f"chunk {c['chunk_id']}",
            ) if x
        )
        text = c["text"].strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + " ..."
        out.append(f"[{i}] {head}\n{text}")
    return "\n\n".join(out)


def search_sec_filings(
    query: str,
    tickers: Optional[list[str]] = None,
    form: Optional[Literal["10-K", "10-Q"]] = None,
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[Literal["FY", "Q1", "Q2", "Q3", "Q4"]] = None,
    top_k: int = 8,
) -> tuple[str, list[dict]]:
    """Plain-Python entry point (no LangChain needed): returns (text for the LLM, raw contract chunks)."""
    filters: dict = {}
    if tickers:
        filters["ticker"] = [t.upper() for t in tickers]
    if form:
        filters["form"] = form
    if fiscal_year:
        filters["fiscal_year"] = fiscal_year
    if fiscal_period:
        filters["fiscal_period"] = fiscal_period
    try:
        chunks = [dict(c) for c in retrieve(query, filters or None, top_k)]
    except RetrievalUnavailableError:
        raise
    except ValueError as e:  # invalid argument -> let the LLM correct itself
        return f"Invalid search arguments: {e}", []
    return format_passages(chunks), chunks


def make_sec_retrieval_tool(name: str = TOOL_NAME, description: str = TOOL_DESCRIPTION):
    """Build the LangChain StructuredTool (response_format='content_and_artifact')."""
    try:
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install langchain-core to use the LangChain tool") from e

    class SecSearchArgs(BaseModel):
        query: str = Field(description="What to look for, in natural language, e.g. 'total revenue three months ended March 31, 2026'.")
        tickers: Optional[list[str]] = Field(default=None, description="Company tickers, e.g. ['MSFT'] or ['MSFT','AAPL'].")
        form: Optional[Literal["10-K", "10-Q"]] = Field(default=None, description="10-K = annual report, 10-Q = quarterly report.")
        fiscal_year: Optional[int] = Field(default=None, description="Fiscal year (the year the fiscal year ends).")
        fiscal_period: Optional[Literal["FY", "Q1", "Q2", "Q3", "Q4"]] = Field(default=None, description="FY for a 10-K, Q1-Q3 for a 10-Q.")
        top_k: int = Field(default=8, ge=1, le=20, description="Number of passages to return.")

    return StructuredTool.from_function(
        func=search_sec_filings,
        name=name,
        description=description,
        args_schema=SecSearchArgs,
        response_format="content_and_artifact",
    )
