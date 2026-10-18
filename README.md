
## For the Agent team: LangChain tool

```python
from rag.langchain_tool import make_sec_retrieval_tool
tool = make_sec_retrieval_tool()   # StructuredTool "sec_filing_search"
# args: query, tickers, form ("10-K"/"10-Q"), fiscal_year, fiscal_period ("FY"/"Q1".."Q4"), top_k
```

The LLM receives numbered passages with a citation line (`[1] MSFT 10-Q Q3 FY2026 (period ending 2026-03-31) | Part I Item 2 | chunk …`);
the full Retrieval API v0 chunks come back as the ToolMessage `artifact`, for citations and provenance.
Point `RAG_INDEX_DIR` at a built index (`data/index`). No LangChain? Call `rag.langchain_tool.search_sec_filings(...)`
or `rag.retrieve.retrieve(...)` directly.

## Selected MVP vector store: Chroma

PostgreSQL/RDS remains the Data team's system of record. Chroma is the derived vector-serving layer behind the unchanged Retrieval API v0. The custom NumPy/BM25 implementation remains available as the Experiment 1 baseline and rollback.

```bash
pip install -r requirements.txt

# Build the selected MVP backend from the canonical chunks export.
python -m rag.cli index --backend chroma

# Search through the same API used by the Agent tool.
python -m rag.cli search "Microsoft total revenue" --ticker MSFT --backend chroma

# Reproduce the previous custom baseline when needed.
python -m rag.cli index --backend custom
python -m rag.cli search "Microsoft total revenue" --ticker MSFT --backend custom
```

Set `RAG_BACKEND=chroma` and `RAG_CHROMA_DIR=data/chroma` in the RAG service environment. The Agent-side import and arguments do not change. See [the vector-store decision](docs/vector_store_decision.md) for the SQL/custom vs. Chroma vs. OpenSearch trade-off and acceptance criteria.
