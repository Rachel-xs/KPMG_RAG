# Retrieval & RAG workstream — QMSS Practicum × KPMG

The vector/hybrid retrieval arm of the "AI Q&A over SEC filings" project. It turns EDGAR 10-K / 10-Q
filings into section-aware chunks, indexes them with BM25 and dense embeddings, and serves a logged
`retrieve()` tool for the Agent and Evaluation teams. Interface: [`docs/retrieval_api.md`](docs/retrieval_api.md).

```
EDGAR ──ingest──> data/raw/*.htm ──chunk──> data/chunks/chunks.jsonl ──index──> data/index/
                                                                                  │
                     Agent / CLI ──> retrieve(query, filters, top_k)   <────────┘
                                          │  logs/retrieval.jsonl
                                          └──> eval harness (Recall@k, MRR, provenance) ──> eval/results/
```

## Quick start

```bash
# 1. environment (Python 3.10+)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. check everything works offline (no network, no API key)
make test
make demo

# 3. SEC requires a User-Agent with your contact info
cp .env.example .env        # then edit SEC_USER_AGENT

# 4. pilot corpus: JPM, BAC, C, CAT, DE, HON — latest 10-K + 2 latest 10-Qs
make pilot                  # = python -m rag.cli pilot   (first run downloads the embedding model)

# 5. try it
python -m rag.cli search "supply chain risks" --ticker CAT,DE --section "Item 1A"
python -m rag.cli search "CET1 capital ratio" --ticker JPM --tables-only --method bm25
python -m rag.cli search "..." --json          # full contract output
```

After `make pilot`, read the `[chunk]` lines: `coverage` is the share of text assigned to an SEC Item.
Filings with **low coverage** (some bank 10-Ks are formatted as annual reports with a cross-reference
index) are flagged. Their text is still indexed, as section `"Unlabeled"`.

## Experiment 1 (target Oct 14)

1. Label the gold set (see [`eval/README.md`](eval/README.md)); set `status` to `labeled`.
2. `make exp1` runs BM25 vs. dense vs. hybrid, each with and without metadata filters, and prints
   evidence-recall@5/10, MRR, provenance and latency by tier.
3. Compare embedders: `python -m rag.cli index --embedder st:intfloat/e5-base-v2`, then `make exp1` again.
   With an OpenAI key: `--embedder openai:text-embedding-3-small`. Embeddings are cached in `data/cache/`,
   so each chunk is only paid for once.

## Layout

| Path | What | Owner (charter) |
|---|---|---|
| `rag/ingest.py` | EDGAR download (pilot only; replaced by Data Eng pipeline later) | B |
| `rag/parse.py`, `rag/chunk.py` | HTML → text/table blocks → Item-aware chunks + metadata | B |
| `rag/bm25.py`, `rag/embed.py`, `rag/index.py` | BM25, pluggable embedders, index build | C |
| `rag/contract.py` | Retrieval API v0: schema, filter validation, errors | A / C |
| `rag/retrieve.py` | public `retrieve()`; `Retriever.search()` for eval — filters, bm25/dense/hybrid (RRF), logging | C |
| `mock/mock_retrieval_tool.py` | standalone contract-conformant mock for the Agent team | A |
| `rag/generate.py` | baseline answer-with-citations + token/cost log | E |
| `rag/evaluate.py`, `eval/` | gold set, metrics, Experiment 1 runner | D |
| `docs/retrieval_api.md` | interface contract v0 for other teams | A / E |
| `tests/` | offline tests on synthetic filings | all |

## Decisions implemented (see charter §8)

* **D1** Hybrid BM25 + dense with Reciprocal Rank Fusion (k=60); metadata filters applied before ranking.
* **D2** Chunk metadata: `chunk_id, ticker, cik, company, form, fiscal_year, fiscal_period,
  period_of_report, filing_date, accession, section, section_title, is_table, source_url`.
* **D3** Item-aware chunking, ~600 tokens (cap 800), tables whole as Markdown with their caption.
* **D6 (proposed change)** The vector store is a plain NumPy matrix (brute-force cosine) instead of
  FAISS/Chroma. The pilot corpus has a few thousand chunks, where this takes milliseconds and adds
  no dependencies. It sits behind `Retriever`, so FAISS can be added later without changing the contract.
* **D7** Every call is logged to `logs/retrieval.jsonl`. MIT License. Keys only in `.env`.
* Each chunk is indexed with a contextual header (company, form, period, section), so those words are
  searchable even when the chunk body never mentions them.

## Known limitations / next steps

* The Item detection is heuristic. Check `data/chunks/chunk_report.json` for each new company.
* `fiscal_year` = the calendar year in which the fiscal year ends. Quarter labels are derived from
  EDGAR's `fiscalYearEnd`, so spot-check companies with non-calendar years (e.g. Deere).
* Not yet built: reranker (cross-encoder), query rewriting/decomposition, FAISS backend, cost dashboard.
