
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
