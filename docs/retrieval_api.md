# Retrieval API Contract v1

**Status:** v1, 2026-10-29. Additive over v0 (signed off 2026-10-08): every v0 field, filter and error is unchanged, so v0 consumers keep working without edits. §16 lists what v1 adds.
**Owner:** RAG team
**Enforced by:** `rag/contract.py` (schema and validation) and `tests/test_contract.py`. The conformance tests run against both the real retriever and the Agent mock.
**Consumers:** Agent, Evaluation, UI, Data Engineering.

This document defines the interface between the RAG retrieval layer and the teams that use it. v0 replaces three earlier versions that did not match each other: the RAG draft, repo doc v0.1, and the Agent mock. Section 12 lists what changed for each of them.

---

## 1. Function

```python
from rag.retrieve import retrieve          # real tool
# from mock_retrieval_tool import retrieve  # drop-in mock (same contract), see §11

def retrieve(
    query: str,
    filters: dict | None = None,
    top_k: int = 10,
    trace_id: str | None = None,   # v1
) -> list[RetrievedChunk]:
    ...
```

| Parameter | Type | Required | Default | Rules |
|---|---|---|---|---|
| `query` | `str` | yes | — | Non-empty after stripping whitespace. The Agent may pass a rewritten query. |
| `filters` | `dict \| None` | no | `None` | Metadata filters, applied **before** ranking (§3). |
| `top_k` | `int` | no | `10` | `1 ≤ top_k ≤ 50`. `bool` is rejected. The Agent uses 8 (Gold v1 knee). |
| `trace_id` | `str \| None` | no | `None` | **v1.** The caller's trace / correlation ID (e.g. the LangGraph run ID). Non-empty, at most 128 characters, otherwise `ValueError`. Echoed in `metadata.trace_id` and in `logs/retrieval.jsonl`. |

`retrieve()` **does**: locate evidence, rank chunks, and return the exact chunk text with provenance.
`retrieve()` **does not**: generate answers, perform calculations, judge correctness, rewrite or summarize chunk text, or hide retrieved evidence.

The ranking method is fixed by the RAG team. It is currently `hybrid`: BM25 plus dense retrieval, combined with Reciprocal Rank Fusion (RRF) using k=60. Method is not a parameter of the public tool. The Evaluation team compares methods through the internal `Retriever.search(..., method=...)` (§10).

Index location: `$RAG_INDEX_DIR` if set, otherwise `paths.index` in `config.yaml`.

---

## 2. Return value

The function returns `list[RetrievedChunk]`:

* The list is ordered by `score` descending. Ties are broken by `chunk_id` ascending, so the order is deterministic.
* `rank` runs from 1 to n in list order, and `len(results) <= top_k`.
* For the same query, filters, `top_k` and `index_version`, the result is identical.
* A valid request with no matches returns `[]`. It never returns `None` and never raises.

---

## 3. Filters

All keys are optional. Within one key, a list means OR. Across keys, conditions are combined with AND. A key whose value is `None` is ignored, so the Agent can always send the full dict.

| Key | Value type | Matching | Example |
|---|---|---|---|
| `ticker` | `str` / `list[str]` | exact, case-insensitive | `"MSFT"`, `["JPM","BAC"]` |
| `cik` | `str` / `int` / list | normalized to 10 digits | `789019` or `"0000789019"` |
| `form` | `str` / list | exact, case-insensitive | `"10-Q"` |
| `accession_number` | `str` / list | exact. Dashes optional on input. | `"0001193125-26-191507"` |
| `filing_date` | `"YYYY-MM-DD"` / list | exact | `"2026-04-29"` |
| `reporting_period_end` | `"YYYY-MM-DD"` / list | exact | `"2026-03-31"` |
| `fiscal_year` | `int` / list | exact. Fiscal year = calendar year in which the company's fiscal year **ends**. | `2026` |
| `fiscal_period` | `"FY"\|"Q1"\|"Q2"\|"Q3"\|"Q4"` / list | exact, case-insensitive | `"Q3"` |
| `section` | `str` / list | **whole-word prefix**, case-insensitive (see below) | `"Part I Item 2"`, `"Item 1A"`, `"Part I"` |
| `is_table` | `bool` | exact | `true` |

**Section matching:** `"Part I"` matches `Part I Item 1` and `Part I Item 2`, but not `Part II Item 1A`. `"Item 1"` does not match `Item 1A`.

**Durations are not filters.** A single chunk, such as an income-statement table, usually contains three-month and nine-month columns together. Phrases like "three months ended" or "nine months ended" therefore go **in the query**. `reporting_period_end` and `fiscal_period` identify the *filing*, not the column.

Example: Microsoft's fiscal year ends June 30, so the 10-Q for the period ended 2026-03-31 has `fiscal_year=2026, fiscal_period="Q3"`.

---

## 4. `RetrievedChunk` schema

```python
RetrievedChunk = {
    "rank": int,                         # 1-based position in this response
    "chunk_id": str,                     # opaque, see §5
    "text": str,                         # exact stored chunk text, never rewritten
    "score": float,                      # higher = more relevant; comparable only within one call

    "section": str | None,               # canonical SEC item, e.g. "Part I Item 2"; None if unlabeled

    "ticker": str | None,
    "cik": str,                          # always 10-digit zero-padded string
    "company_name": str,

    "form": str,                         # "10-K" | "10-Q"
    "accession_number": str,             # with dashes
    "filing_date": str,                  # YYYY-MM-DD
    "reporting_period_end": str | None,  # YYYY-MM-DD (EDGAR period of report)

    "source_url": str | None,            # SEC document URL

    "chunking_version": str,
    "extraction_version": str,
    "index_version": str,

    "metadata": dict,                    # optional documented keys, see §6
}
```

All 17 top-level fields are always present, and only those marked `| None` may be null. `rag.contract.validate_chunk()` checks this.

### Example

```json
{
  "rank": 1,
  "chunk_id": "MSFT-0001193125-26-191507-0001",
  "text": "INCOME STATEMENTS (In millions, ...) ... Total revenue 82,886 70,066 241,832 205,283 ...",
  "score": 0.032787,
  "section": "Part I Item 1",
  "ticker": "MSFT",
  "cik": "0000789019",
  "company_name": "Microsoft Corporation",
  "form": "10-Q",
  "accession_number": "0001193125-26-191507",
  "filing_date": "2026-04-29",
  "reporting_period_end": "2026-03-31",
  "source_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm",
  "chunking_version": "item-aware-v0-t600-m800",
  "extraction_version": "rag.parse-v0",
  "index_version": "a41f09c2e1d3",
  "metadata": {
    "section_title": "Income Statements",
    "fiscal_year": 2026,
    "fiscal_period": "Q3",
    "is_table": true,
    "n_tokens": 512,
    "retrieval_method": "hybrid",
    "retrieval_backend": "chroma",
    "bm25_rank": 1,
    "dense_rank": 2,
    "request_id": "b7c1..."
  }
}
```

---

## 5. Field rules

* **`chunk_id`** is an **opaque string**. Do not parse it. It is unique within an `index_version`, and stable across rebuilds as long as `chunking_version` does not change. The current format is `{ticker}-{accession}-{seq:04d}`, but Data Engineering may replace it once `sec.chunks` becomes the source of truth.
* **`text`** is the exact stored text. Tables are rendered as Markdown with their caption line. The contextual header used for indexing (company, form, period, section) is **not** included in `text`.
* **`score`** is a raw value: the RRF score for hybrid, the BM25 score, or cosine similarity. It is rounded to 6 decimals and is **not normalized**. Scores are comparable only within one call, so consumers should rely on order and must not apply fixed thresholds.
* **`section`** is the canonical SEC Item key. 10-Q items carry their Part prefix (`"Part I Item 2"`) because Item numbers repeat across Parts. Text that cannot be assigned to an Item returns `None`. The human-readable title is in `metadata.section_title`.
* **Versions:**
  * `chunking_version` changes when chunk boundaries change.
  * `extraction_version` changes when parsed text changes.
  * `index_version` is a hash of the chunk file, so it changes whenever the corpus or chunks change.
  * Every evaluation result must record `index_version`.

---

## 6. `metadata` (optional, documented keys only)

Consumers must read these keys with `.get()` and must not depend on any key not listed here.

| Key | Type | Meaning |
|---|---|---|
| `section_title` | `str \| None` | e.g. `"Results of Operations"` |
| `fiscal_year` | `int \| None` | see §3 |
| `fiscal_period` | `str \| None` | `FY`/`Q1`–`Q4` |
| `is_table` | `bool` | chunk is (part of) a table |
| `n_tokens` | `int \| None` | chunk length |
| `retrieval_method` | `str` | `hybrid` / `bm25` / `dense` / `mock_keyword_overlap` |
| `retrieval_backend` | `str` | `custom` / `chroma`; enables like-for-like architecture comparisons |
| `bm25_rank`, `dense_rank` | `int \| None` | component ranks (hybrid only, for error analysis) |
| `request_id` | `str` | joins this result to `logs/retrieval.jsonl` |
| `first_stage_rank` | `int \| None` | rank before the optional reranker (only when reranking is on; off by default) |
| `trace_id` | `str` | **v1.** the caller's `trace_id`, present only when one was passed |
| `section_id` | `str` | **v1.** Data Engineering's section ID for the chunk's section |
| `section_path` | `str` | **v1.** readable breadcrumb, e.g. `"Part I Item 1 > Note 16 — Segment Information > Revenue by segment"`. Built from section, section title and table name; empty, `Unlabeled` and repeated parts are skipped |
| `table_id` | `str` | **v1.** table chunks only: ID of the source table, shared by all pieces of one table |
| `table_name` | `str` | **v1.** table chunks only: the table's caption as printed (max 160 characters) |
| `parent_id` | `str` | **v1.** ID of the parent context (`table_id` for a whole table, `win:<chunk_ids>` for a text window) |
| `parent_text` | `str` | **v1.** parent context for small-to-big reading: the whole table if it fits 1,500 tokens, else the chunk; for text, previous + this + next chunk of the same section, shrunk to fit. `text` is always contained in it. Cite `text`/`chunk_id`, read `parent_text` |

v1 keys appear **only when the index carries them** (indexes built with `build_chunk_variant.py --with-parents`). A v0 index returns exactly the v0 keys. Consumers must keep using `.get()`.

`score` is comparable only within one call of this tool. It is not comparable with scores from GraphRAG, SQL or any other tool, or across calls.

Reserved for v0.x, to be added once Data Engineering provides them (additive, so no new contract version is needed): `char_start`, `char_end` (offsets in the source text), `source_sha256`, and `source_locator` (XPath).

---

## 7. Errors

| Situation | Behavior |
|---|---|
| Empty or non-string `query` | `ValueError("query must be a non-empty string")` |
| `top_k` not a positive int (incl. `0`, `-5`, `2.5`, `True`, `"10"`) | `ValueError("top_k must be a positive integer")` |
| `top_k > 50` | `ValueError("top_k must be <= 50")` |
| `filters` not a dict | `ValueError("filters must be a dict or None")` |
| Unknown filter key | `ValueError("unsupported filter: <key>")`. Old names get a hint, e.g. `unsupported filter: form_type (use 'form')`. Unknown keys are never silently ignored. |
| Malformed filter value (bad date, empty list, non-bool `is_table`, `fiscal_period="three_months_ended_..."`) | `ValueError("invalid value for filter '<key>': ...")` |
| Valid request, nothing matches | `[]` |
| Index missing or unreadable | `rag.contract.RetrievalUnavailableError` (a `RuntimeError`) |

**Rule for the Agent:** `[]` means "no evidence found". An exception means "retrieval is broken". The Agent must not answer as if there is no evidence when an exception was raised.

---

## 8. Quantitative questions

`retrieve()` returns the text that contains the numbers, usually table chunks. To bias toward tables, pass `is_table=True`. The Agent or reasoning layer does the arithmetic.

Structured XBRL facts and text-to-SQL are **out of scope for v0**. They are expected in a separate tool or a v1 hybrid contract, and will not be added to `retrieve()` silently.

---

## 9. Provenance

Every result carries `chunk_id, section, ticker, cik, company_name, form, accession_number, filing_date, reporting_period_end, source_url, chunking_version, extraction_version, index_version`. From these you can identify the company, filing, source document, chunk and processing version behind any answer. `accession_number` is the cross-team document key.

---

## 10. Evaluation compatibility

* **Relevance:** the Evaluation team judges relevance by `chunk_id` when gold chunk IDs exist. Until then, they use evidence matching: metadata keys plus `contains` strings, as described in `eval/README.md` and `rag/evaluate.py`. Gold labels survive re-chunking only through evidence matching.
* **Multiple acceptable chunks** for one evidence region are stored as an any-of set within one evidence item. The item counts as found if any of those chunks appears.
* **Default metrics:**
  * `evidence_recall@10`, also reported @5. Deep multi-evidence questions are scored by the share of evidence items found.
  * `MRR@10`, computed against the first relevant chunk.
  * `hit@k` and `provenance@k` are secondary metrics.
* **Envelope for experiments:** a backend retriever's `search(query, filters, top_k, method)` returns `{request_id, index_version, backend, method, top_k, latency_ms, tokens, warnings, results: [RetrievedChunk]}`. The `results` list is the same as `retrieve()` with the same arguments. This is an internal API for Evaluation and the CLI, not part of the Agent contract.
* **Logging:** every call appends one line to `logs/retrieval.jsonl` with `timestamp, request_id, query, filters, backend, method, top_k, latency_ms, n_candidates, chunk_ids, scores, index_version`.
* **Benchmark leakage:** gold questions, answers and grading metadata must never be indexed.

---

## 11. Mock for other teams

`mock/mock_retrieval_tool.py` is a standalone file (standard library only) with the **same signature, filters, schema, ordering and errors**. It contains 6 chunks from the MSFT 10-Q, accession `0001193125-26-191507`, and ranks them by keyword overlap. Its ranking quality is meaningless; only its shape is guaranteed. `tests/test_contract.py` runs the same conformance tests against the mock and the real tool, so code built on the mock works unchanged when you switch to `from rag.retrieve import retrieve`.

---

## 12. What changed from the earlier versions

| Earlier version | Old | v0 final |
|---|---|---|
| Agent mock | `retrieve(query, ticker=..., form_type=..., fiscal_period=..., section=..., top_k=5)` | `retrieve(query, filters={...}, top_k=10)` |
| Agent mock | `form_type` | `form` |
| Agent mock | `fiscal_period="three_months_ended_2026-03-31"` | Use `reporting_period_end="2026-03-31"` and/or `fiscal_period="Q3"`. Put the duration in the query. |
| Agent mock | substring `section` match | whole-word prefix match on canonical key |
| Agent mock | `document_id`, `latency_ms` per result | removed. Use `accession_number`; latency is in logs and `search()`. |
| Agent mock | `retrieval_method` top-level | `metadata.retrieval_method` |
| Repo v0.1 | `Retriever.retrieve(...)` returned an envelope dict | `retrieve()` returns a list. The envelope moved to `Retriever.search()`. |
| Repo v0.1 | `k`, `method` params | `top_k`. `method` is internal only. |
| Repo v0.1 | `metadata.accession`, `metadata.company`, `period_of_report`, int `cik` | top-level `accession_number`, `company_name`, `reporting_period_end`, 10-digit string `cik` |
| Repo v0.1 | `debug` | `metadata.bm25_rank` / `metadata.dense_rank` |
| Repo v0.1 | unknown filter error text | `unsupported filter: <key>` |
| RAG draft | no `rank`, `index_version`; open questions | added. Open questions are resolved in §13. |

---

## 13. Decisions on the draft's open questions

| # | Question | v0 decision |
|---|---|---|
| RAG-1 | Raw or normalized score? | Raw, rounded to 6 decimals. Order is authoritative. |
| RAG-2 | Expose hybrid component scores? | Component **ranks** in `metadata` (`bm25_rank`, `dense_rank`), not scores. |
| RAG-3 | Structured facts in `retrieve()`? | No. Deferred to v1 or a separate tool (§8). |
| RAG-4 | Typed filter object? | Plain `dict` in v0, validated strictly. A typed object may come in v1. |
| Agent-1 | Fields sufficient for citation? | Yes. Cite `company_name, form, reporting_period_end, section, source_url`. |
| Agent-2/3 | Offsets, SHA-256? | Reserved optional `metadata` keys (§6), filled once Data Engineering delivers them. |
| Agent-4 | Raw scores needed? | Provided, but don't threshold on them. |
| Agent-5 | More filters? | Added `fiscal_year`, `fiscal_period`, `is_table`, and lists for OR. Date ranges are deferred. |
| Eval-1 | Relevance by `chunk_id`? | Yes when gold chunk IDs exist; otherwise evidence matching (§10). |
| Eval-2 | Multiple acceptable chunks? | Any-of set per evidence item. |
| Eval-3/4 | Recall@10? MRR? | `evidence_recall@10` (+@5) and MRR@10 against the first relevant chunk. |
| Eval-5 | Multi-evidence deep questions? | Score by the share of evidence items found within top-k. |
| DE-1..4 | `sec.chunk_citations` fields, `chunks.metadata` shape, version names, final chunk IDs | **Still open, owned by Data Engineering.** The contract treats `chunk_id` as opaque and versions as free strings, so their answers will not break v0. |

---

## 14. Versioning

This document is contract **v1**, and `rag.contract.CONTRACT_VERSION == "v1"`. v1 is additive only (§16); it carries its own number because it adds a call parameter (`trace_id`) and the teams asked to refer to it by name.

**Breaking changes require v1 and a heads-up to all consumer teams.** These include renaming or removing a top-level field, changing filter semantics, changing the return type, or changing error behavior.

**Additive changes are v0.x and do not break consumers.** These include adding a new optional `metadata` key or a new optional filter.

---

## 15. Definition of done (sign-off)

- [x] Inputs, output schema, provenance fields, empty-result and error behavior are specified (§1–7).
- [x] Real retriever and mock conform. 73 offline tests pass, including the contract tests run against both.
- [ ] Agent confirms they can consume the output (switch from old mock to new mock).
- [ ] Evaluation confirms metrics in §10.
- [ ] Data Engineering confirms the field sources and answers DE-1..4.
- [ ] Review comments from at least three groups resolved.

---

## 16. v1 changes (2026-10-29)

| Change | Why | Effect on consumers |
|---|---|---|
| `trace_id` parameter on `retrieve()`, `Retriever.search()`, the Chroma backend and the mock; echoed in `metadata.trace_id`, the `search()` envelope and the log row | Agents asked for end-to-end trace IDs (10/29 sync) | none unless passed |
| `section_id`, `section_path` | GraphRAG and UI asked for a section breadcrumb (View Sources) | optional keys |
| `table_id`, `table_name` | tables are cited by name; groups the pieces of one table | optional keys |
| `parent_id`, `parent_text` | small-to-big context: Gold v1 recall 0.852 → 0.890 at the same ~2.6k tokens | optional keys; the Agent passes `parent_text` to the reader instead of `text` |
| LangSmith retriever span `rag.retrieve` (`rag/observability.py`) | the call shows up nested inside the Agent's LangGraph trace with query, filters, index_version, backend, trace_id and the returned documents (`parent_text` left out) | only when `LANGSMITH_TRACING=true` and `langsmith` is installed; otherwise a no-op |
| Explicit note that `score` is not comparable across tools | GraphRAG gap doc | documentation only |

Not in v1: abstention signal (to be agreed with Evaluation and GraphRAG), structured numeric facts (separate SQL tool, see the routing proposal), `char_start`/`char_end`.

## 17. v1.1 changes (2026-11-09): evidence check

| Change | Why | Effect on consumers |
|---|---|---|
| `search()` envelope gains `evidence_status` (`ok` / `weak` / `empty`), `weak_reasons` and `evidence_checks` (custom and Chroma backends) | Mentor asked for a "weak result" signal so the Agent can fall back to GraphRAG. Round 1 showed RRF scores cannot be thresholded: median top-1 ≈ 0.032 and top-1/top-2 margin ≈ 0.0007 for hits, misses and unanswerable questions alike | additive fields; `retrieve()` and `RetrievedChunk` unchanged |
| New `retrieve_with_status(query, filters, top_k, trace_id)` returning `{results, evidence_status, weak_reasons, evidence_checks, warnings, request_id, trace_id}` | the Agent needs the status without switching to the debug envelope | opt-in; `retrieve()` stays the v1 entry point |

`weak_reasons` (no score threshold; checks in `rag/evidence.py`):

| reason | fires when | status |
|---|---|---|
| `filter_no_match` | the filters match no chunk (e.g. a filing outside the snapshot) | `empty` |
| `no_results` | the filters match chunks but nothing is returned | `empty` |
| `multi_target` | the filters list several tickers, forms, fiscal years or periods; split the query instead | `weak` |
| `entity_missing` | a ticker, fiscal year or fiscal period from the filters is absent from the results | `weak` |
| `methods_disagree` | hybrid only: BM25 top 10 and dense top 10 share no chunk (`evidence_checks.bm25_dense_overlap@10` = 0) | `weak` |

Round 1 validation (Gold Set v2, `scripts/run_round1_diag.py`): the check marks 2/105 hits, 7/19 misses, 3/10 unanswerable and
5/11 Exhibit 21 questions as not `ok`. A looser `methods_disagree` (overlap ≤ 2) would flag 16% of hits. It catches only 3/10
unanswerable questions, so abstention still needs the Agent's own evidence-sufficiency check; this signal is one input to it.

Tested and not adopted: `rrf_k` 20. It helps at k=10 on Gold v2 (0.847 → 0.871) but is slightly worse at k=8 on both sets
(Gold v1 0.834 → 0.823, Gold v2 0.815 → 0.806), and the Agent tool uses top_k=8. Recommended instead: top_k=10, which
gains on both sets with the current `rrf_k` 60 (Gold v1 0.834 → 0.857, Gold v2 0.815 → 0.847).

## 18. v1.2 changes (2026-11-11): retrieve_multi

| Change | Why | Effect on consumers |
|---|---|---|
| New `retrieve_multi(query, filters, top_k, trace_id, subqueries=None, top_k_each=None)` (`rag/multi.py`) | Round 1: 6 of the 19 retrieval misses need several filings at once (cross-company rankings EV2-040/042/043; 10-K + 10-Q derived figures EV1-037/038, EV2-045). One search lets the strongest filing crowd the rest out of the top k. v1.1 flags these as `multi_target`; v1.2 answers them | opt-in; `retrieve()` and `retrieve_with_status()` unchanged |

**Splitting.** Each of `ticker`, `form`, `fiscal_year`, `fiscal_period` whose filter lists more than one value is split; one
sub-search per combination (at most 20), other filter keys kept. Without such a list it is exactly one search, identical to
`retrieve_with_status()`. Callers can pass their own `subqueries=[{"query", "filters", "label"}]` instead.

**Depth.** `top_k_each` results per sub-search; default `top_k` for up to 3 targets, else 5 (ten companies → up to 50 chunks).

**Merging.** Round robin by rank (every target's #1, then every #2, ...); duplicates kept once. Each result gets
`metadata.subquery` (e.g. `"ticker=AAPL"`) and `metadata.subquery_rank`; `rank` is renumbered 1..n.

**Status.** `evidence_status` is `ok` only if every sub-search is `ok`; `empty` if nothing is returned. `weak_reasons` are
prefixed with the sub-search label (`"ticker=MU:entity_missing"`). A combination that matches no filing (e.g. a 10-K with
`fiscal_period` Q3) is listed under `skipped` and in `warnings`, and does not make the result weak.

Returns `{results, subqueries: [{label, query, filters, n_results, evidence_status, weak_reasons, request_id}], skipped,
evidence_status, weak_reasons, warnings, trace_id, top_k_each}`.

**When the Agent should call it:** whenever `retrieve_with_status()` returns `multi_target`, or directly for questions that
compare companies or combine a 10-K with a 10-Q. For a derived Q4, filters such as
`{"ticker": "MSFT", "fiscal_year": 2026, "fiscal_period": ["FY", "Q3"]}` give one 10-K and one 10-Q sub-search.
