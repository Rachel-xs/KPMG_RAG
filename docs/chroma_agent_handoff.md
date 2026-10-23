# Chroma -> Agent Handoff (MVP)

**Purpose:** let the Agent team run the existing Chroma backend through the unchanged RAG retrieval interface, then record a small, reproducible smoke test.

## Current status

- Chroma backend and the Custom baseline are available in the RAG repository.
- The RAG README documents the build/search commands and Agent tool entry point.
- A prior local validation indexed 210 MSFT 10-Q chunks from an earlier RDS export; revenue evidence ranked first and the RAG test suite reported 82 passing tests (PR #5).
- The Agent team's two Microsoft FY2026 Q3 checks were run against the October 14 Custom index. Those are useful test questions, but they do not count as Chroma-Agent integration.
- Data Engineering still needs to confirm the authoritative processing set and formal frozen snapshot. Until then, label the 210-chunk export as a technical smoke-test snapshot, not the formal evaluation corpus.

## Build and search Chroma

Run from the repository root in an environment with project requirements installed:

```bash
pip install -r requirements.txt
python -m rag.cli index --backend chroma
python -m rag.cli search "Microsoft total revenue" --ticker MSFT --backend chroma
```

The index command expects the canonical chunks export configured for this checkout. Confirm the input path and snapshot before building. For the integration environment, set:

```text
RAG_BACKEND=chroma
RAG_CHROMA_DIR=data/chroma
```

The generated Chroma directory is a derived local index. Record its corpus and index version; the Chroma directory itself is not the authoritative data snapshot.

## Agent entry point

The current README exposes this LangChain tool:

```python
from rag.langchain_tool import make_sec_retrieval_tool

tool = make_sec_retrieval_tool()
# tool name: sec_filing_search
```

The stable RAG contract is:

```python
retrieve(query: str, filters: dict | None = None, top_k: int = 10)
```

Use the same query, filters, and `top_k` for Custom and Chroma. The Agent should receive exact chunk text and citation/provenance fields. Keep `chunk_id`, `text`, accession number, section, filing metadata, source URL, and version fields intact. Chroma should be selected through RAG configuration; the Agent should not need a backend-specific retrieval call.

## Monday smoke-test sequence

1. Agree with Data Engineering which available export to use and label its snapshot/version. If the formal set is still pending, use the existing export only as a clearly labeled technical test.
2. Build the Chroma index from that export and record the index version.
3. Run the same two Microsoft FY2026 Q3 questions previously used by Agent, copied verbatim from the Agent demo, through the Agent's normal workflow.
4. Save the returned evidence and citation metadata for each query. Check that each citation points back to the expected filing and chunk.
5. If time permits, run the same questions through Custom with the same snapshot, filters, and `top_k`; compare evidence and ranks.
6. Log failures and missing fields. Two questions are a smoke test, not a formal benchmark.

## Parent context and token budget

Agent has asked for optional parent context. Keep it additive: preserve the original chunk `text`, `chunk_id`, and citation metadata. Do not make it required by the current v0 retrieval contract until both teams agree on the response shape.

The meeting discussed comparing roughly 1.9k and 3k tokens, with 3k as an initial budget. This is an Agent context-assembly setting, not a Chroma index setting. The current MVP does not generate an LLM answer, so record this as a follow-up check if the Agent demo actually assembles context; it does not affect the retrieval-only smoke-test result.

## Acceptance checklist

- [ ] Chroma index builds from a named input snapshot.
- [ ] Agent calls the normal RAG interface with Chroma selected by configuration.
- [ ] The same agreed query and filters run successfully.
- [ ] Retrieved results include exact text and usable citation/provenance metadata.
- [ ] Test record includes corpus/snapshot label, index version, backend, query, filters, `top_k`, ranks, chunk IDs, latency if available, and any errors.
- [ ] Any Custom-vs-Chroma comparison uses the same input snapshot and query settings.
