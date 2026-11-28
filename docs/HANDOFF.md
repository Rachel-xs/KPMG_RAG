# Handoff: Retrieval & RAG workstream

For whoever takes over or extends the RAG component after the practicum (code freeze 2026-11-30, final report 2026-12-11). Start with the [README](../README.md) to install the system and reproduce its numbers. This page covers what the README does not: what exists, where it lives, what may and may not be shared, what was tested, and what is left.

## 1. What is handed over

| Item | Where | Notes |
|---|---|---|
| Code | this repository, `main` | Frozen 2026-11-30. Retrieval library `rag/`, scripts `scripts/`, tests `tests/` |
| Frozen systems | `configs/final_v1.yaml`, `configs/final_v2.yaml` | `final_v1` is the default. `final_v2` differs only in longer narrative answers. Do not edit them: every official score refers to them |
| Interface | [`docs/retrieval_api.md`](retrieval_api.md) | Contract v1.3 (§21) is the version Agents built on |
| Pre-registration and run record | [`docs/preregistration_objective_eval.md`](preregistration_objective_eval.md) | Every independent run with its commit, index, cost and date; disclosures |
| Index packages | shared privately (see §3) | Not in Git |
| Final report | shared with KPMG separately | Results, limitations, future work |

## 2. How the system fits with the other teams

```
user question
   │
   ▼
Agents (LangGraph): query understanding ─► RAG pre-check (check_coverage)
   │                                          │ all_hit / partial ─► RAG retrieve_with_status / retrieve_multi
   │                                          │ none / unresolved ─► GraphRAG if it covers the company, else a direct reply
   │                                          ▼
   ├─ ranking / filtering ─────────────────► GraphRAG structured search
   ├─ RAG weak / empty ────────────────────► one fallback to GraphRAG
   ▼
answer step: quotes chunk `text` verbatim; figures computed by a deterministic calculator
```

- **Data Engineering** owns the database (AWS RDS, PostgreSQL) of filings, sections, chunks and XBRL facts. RAG exports from it read-only and builds its own chunks and indexes.
- **Agents** call RAG through `rag.retrieve` / `rag.coverage` (contract §21). Their repository: `yz5405/kpmg-agentic-backbone`.
- **GraphRAG** covers 16 companies: RAG's 10, plus GOOGL, AMZN, WMT and WDC, plus CAH and INTC (on hold). For the 10 core companies its configuration lists the same 233 filings as RAG's demo index; what each GraphRAG arm (Graph, Structured) has actually loaded is checked with its `describe_corpus()` (on 11/28 the Neo4j graph held 20 filings). Their repository: `ZiyiClaudiaWang/KPMG-GraphRAG`.
- **Evaluation** writes and seals the question sets, scores every run, and keeps the seeds. Their repository: `thomassong0604-oss/kpmg-eval`.

## 3. Index packages

| Package | `index_version` | Size | Use |
|---|---|---|---|
| `round1_frozen_7a7ad9801f86_full.zip` | `7a7ad9801f86` | 43 MB | Evaluation and reproduction (`index_C1` + `chroma_C1`). SHA-256 `1903a19f4145dd25eb0e9d3b39d8572de1f0195f2163b4ee4a578aaf81d7fc3a` |
| `chroma_C1_persisted_7a7ad9801f86.zip` | `7a7ad9801f86` | 35 MB | Serving only (`chroma_C1`); superseded by the full package above |
| `chroma_full233_v2_3abed1490b13.zip` | `3abed1490b13` | 318 MB | The demo index (233 filings, 10 companies) |
| 645-filing index (folder `data/fullplus/`) | `37c4eb2f1628` | 3.6 GB | XBRL B/C and the scale analysis; rebuild with `scripts/build_full.sh` rather than copying |

All packages are kept in `share/` on the RAG lead's machine and are passed on by direct message or drive link, never through GitHub. After unzipping, run `python scripts/repersist_chroma.py <dir>/chroma_C1 --check` before any use.

## 4. What may and may not be shared

| Never in a public repository or channel | Why |
|---|---|
| Chunks, answers, index packages, database exports | They contain filing text and Data's internal IDs (Data's request) |
| `eval/*_filings*.csv` freeze lists | They carry Data's internal `filing_id` / `processing_set_id` |
| Sealed question sets (holdout, XBRL) and their seeds | Eval's; sharing them breaks the independent tests |
| `.env` (OpenAI key, database credentials) | Secrets; never send them over Slack |

Holdout and XBRL files: check the SHA-256 against Eval's manifest before opening, run each configuration once, and return the answers before any analysis.

## 5. What was tested

All official scores are Eval's, on the frozen system. Details and intervals are in the final report.

| Test | Result |
|---|---|
| Dev, Gold Set v2.2 (tuning set) | Numbers 0.935 (87/93) with `final_v1`; retrieval hybrid @10 0.850 |
| Holdout A (40 sealed questions) | Numbers 28/30 = 0.933; unanswerable questions declined 5/5; all citations valid |
| Holdout B (30 sealed questions) | Narrative answers stating every point 17/18 (`final_v2`); confirmed by a blind human review (two raters, 71/75 points agreed) |
| XBRL B (Set A's 150 questions on 645 filings) | 0.873 with gold filters, 0.767 with the pre-check |
| XBRL A, C2 | Returned 11/25 and 11/27; Eval's scores in the final report |
| Robustness (messy wording, abstention) | Abstention 51/51; query-rewriting study (exploratory) in the report |
| Reproducibility | A fresh clone and environment reproduces the dev numbers exactly (2026-11-26) |

## 6. Known issues and open items

**Limits of the frozen system** (see the README and the report for numbers):
- On large corpora, ranking depends on the pre-check's filters; without filters, retrieval on 645 filings finds the evidence only 35% of the time.
- Company-name matching needs an alias table beyond the 10 core companies ("Amazon" does not resolve; "Cardinal Health" also matches Carnival).
- Period words with typos are not read; compound questions are not split; two-filing questions decline more often (3/5 on the holdouts).
- Exhibits and note tables are not indexed; relationship questions go to GraphRAG.
- The answer model ignores `temperature=0`, so repeated runs vary by about one question in 93.

**Open items at handoff:**
- Agents' LLM-mode tests (query understanding and final answers) were deferred: all joint tests ran in `rule_based` mode.
- GraphRAG had not yet loaded Amazon into its graph; CAH and INTC wait for Data's section-split fix.
- Cell-level citations (`rag.cells`, contract §20) use RAG's own table parsing until Data publishes stable table and cell IDs.
- Data's section split failed for 10 filings of the 645 (CAH, CL, ILMN, INTC, JPM, USB); list sent to Data on 11/25.

**Suggested next steps:**
1. BM25 statistics computed within the filtered filings (recovers the small loss at scale).
2. An alias table for company names, and typo-tolerant period reading in the pre-check.
3. Sub-searches for compound questions; separate retrieval of each filing for two-filing questions.
4. Indexes for GraphRAG's extra companies once Data's fixes land (needs new gold questions to evaluate them).

## 7. After the freeze

- Ask Data Engineering to rotate the read-only database password that RAG used.
- Keep the old RAG machine's data until the final report is accepted (12/11).
- Changes after the freeze go through a PR, and must not touch `configs/final_v*.yaml` or `data/round1/`.
