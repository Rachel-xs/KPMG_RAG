"""Smoke tests for the real Agent <-> RAG integration.

Task:
    Agent integration smoke test

Done when:
    - Agent calls retrieve() on real data
    - 17-field Retrieval API v0 payload is valid
    - metadata filters work
    - citation / provenance metadata is preserved
    - no-evidence requests are handled cleanly

These tests require:
    1. A built RAG index.
    2. The Agent repository available locally.
    3. KPMG_RAG_BACKEND=real.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from rag.contract import REQUIRED_FIELDS, validate_chunk, validate_results
from rag.retrieve import retrieve


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_REPO_DIR = os.getenv("KPMG_AGENT_REPO_DIR")

if AGENT_REPO_DIR:
    agent_repo = Path(AGENT_REPO_DIR).resolve()
    if str(agent_repo) not in sys.path:
        sys.path.insert(0, str(agent_repo))


def _agent_available() -> bool:
    """Return True when the Agent repository is importable."""
    try:
        import agent.integration  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# 1. Retrieval API v0 payload validation
# ---------------------------------------------------------------------------

def test_real_retrieve_returns_valid_contract_payload():
    """Real retrieve() should return chunks satisfying the 17-field v0 contract."""

    results = retrieve(
        query=(
            "What was Microsoft's total revenue for the "
            "three months ended March 31, 2026?"
        ),
        filters={
            "ticker": "MSFT",
            "form": "10-Q",
        },
        top_k=5,
    )

    assert results, "Expected real retrieval to return at least one result."

    # Contract-level list validation:
    # length <= top_k, ranks ordered correctly, scores correctly sorted, etc.
    validate_results(results, top_k=5)

    assert len(REQUIRED_FIELDS) == 17

    for chunk in results:
        validate_chunk(chunk)

        assert set(REQUIRED_FIELDS).issubset(chunk.keys())

        assert chunk["ticker"] == "MSFT"
        assert chunk["form"] == "10-Q"

        assert chunk["chunk_id"]
        assert chunk["text"]
        assert chunk["cik"]
        assert chunk["accession_number"]
        assert chunk["filing_date"]
        assert chunk["index_version"]

        assert isinstance(chunk["metadata"], dict)


# ---------------------------------------------------------------------------
# 2. Metadata filter validation
# ---------------------------------------------------------------------------

def test_real_retrieve_respects_metadata_filters():
    """Every returned chunk must satisfy the requested metadata filters."""

    filters = {
        "ticker": "MSFT",
        "form": "10-Q",
        "reporting_period_end": "2026-03-31",
    }

    results = retrieve(
        query="Microsoft revenue growth",
        filters=filters,
        top_k=5,
    )

    assert results, "Expected matching Microsoft 10-Q evidence."

    for chunk in results:
        assert chunk["ticker"] == "MSFT"
        assert chunk["form"] == "10-Q"
        assert chunk["reporting_period_end"] == "2026-03-31"


# ---------------------------------------------------------------------------
# 3. Citation / provenance validation
# ---------------------------------------------------------------------------

def test_retrieved_chunks_preserve_citation_provenance():
    """Retrieved evidence must contain enough provenance for Agent citations."""

    results = retrieve(
        query="What drove Microsoft's revenue growth?",
        filters={
            "ticker": "MSFT",
            "form": "10-Q",
        },
        top_k=5,
    )

    assert results

    for chunk in results:
        # Unique evidence identifier
        assert chunk["chunk_id"]

        # Filing identity
        assert chunk["ticker"] == "MSFT"
        assert chunk["cik"]
        assert chunk["form"] == "10-Q"
        assert chunk["accession_number"]

        # Filing date / period
        assert chunk["filing_date"]

        # Version provenance
        assert chunk["chunking_version"]
        assert chunk["extraction_version"]
        assert chunk["index_version"]

        # Citation text must exist
        assert chunk["text"].strip()


# ---------------------------------------------------------------------------
# 4. No-evidence behavior at the RAG layer
# ---------------------------------------------------------------------------

def test_real_retrieve_returns_empty_list_when_filters_match_nothing():
    """A valid request with no matching evidence should return [], not an error."""

    results = retrieve(
        query="What was the company's revenue?",
        filters={
            # Valid ticker syntax, but intentionally not present in this corpus.
            "ticker": "ZZZZ",
        },
        top_k=5,
    )

    assert results == []


# ---------------------------------------------------------------------------
# 5. Agent -> real RAG smoke test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _agent_available(),
    reason=(
        "Agent repo not importable. Set KPMG_AGENT_REPO_DIR to the local "
        "kpmg-agentic-backbone repository."
    ),
)
def test_agent_calls_real_rag_and_returns_evidence(monkeypatch):
    """The Agent workflow should call the real RAG backend and return evidence."""

    monkeypatch.setenv("KPMG_RAG_BACKEND", "real")

    from agent.integration import run_integrated_agent

    result = run_integrated_agent(
        query=(
            "What was Microsoft's total revenue for the "
            "three months ended March 31, 2026?"
        ),
        top_k=5,
    )

    assert isinstance(result, dict)

    assert "status" in result
    assert "evidence" in result
    assert "logs" in result

    evidence = result["evidence"]

    assert evidence, "Expected Agent workflow to receive evidence from real RAG."

    for item in evidence:
        assert "text" in item
        assert "metadata" in item

        assert item["text"].strip()

        metadata = item["metadata"]

        # rag_tool.py preserves Retrieval API fields as Agent metadata.
        assert metadata["chunk_id"]
        assert metadata["ticker"] == "MSFT"
        assert metadata["form"] == "10-Q"
        assert metadata["cik"]
        assert metadata["accession_number"]

        # Agent adapter adds source=form for its citation contract.
        assert metadata["source"] == "10-Q"


# ---------------------------------------------------------------------------
# 6. Agent no-evidence smoke test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _agent_available(),
    reason=(
        "Agent repo not importable. Set KPMG_AGENT_REPO_DIR to the local "
        "kpmg-agentic-backbone repository."
    ),
)
def test_agent_handles_no_evidence_cleanly(monkeypatch):
    """Agent should handle a valid request with no retrieved evidence."""

    monkeypatch.setenv("KPMG_RAG_BACKEND", "real")

    # Test the Agent RAG adapter directly so we can deliberately provide
    # a filter known not to match the corpus.
    from agent.tools.rag_tool import retrieve_evidence

    evidence = retrieve_evidence(
        query="What was the company's revenue?",
        filters={
            "ticker": "ZZZZ",
        },
        top_k=5,
    )

    assert evidence == []
