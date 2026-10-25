# Retrieval API Contract v0

**Status:** Draft v0  
**Owner:** RAG Team  
**Purpose:** Define the interface between the RAG retrieval layer and downstream Agent / Evaluation components.

---

## 1. Purpose

`retrieve()` is the public retrieval interface exposed by the RAG team.

Its responsibilities are to:

1. Accept a natural-language query.
2. Optionally restrict retrieval using SEC filing metadata.
3. Retrieve and rank relevant text chunks.
4. Return chunk text together with provenance metadata for answer generation, citation, debugging, and evaluation.

`retrieve()` does **not** generate the final answer and does **not** perform financial calculations itself.

---

## 2. Proposed Function Signature

```python
def retrieve(
    query: str,
    filters: dict | None = None,
    top_k: int = 10
) -> list[RetrievedChunk]:
    ...
```

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `str` | Yes | — | Natural-language retrieval query |
| `filters` | `dict \| None` | No | `None` | Optional SEC filing metadata filters |
| `top_k` | `int` | No | `10` | Maximum number of ranked chunks returned |

---

## 3. Supported Filters

Version 0 proposes the following filters:

```python
filters = {
    "ticker": "MSFT",
    "cik": "0000789019",
    "form": "10-Q",
    "accession_number": "0001193125-26-191507",
    "filing_date": "2026-04-29",
    "reporting_period_end": "2026-03-31",
    "section": "Part I Item 1"
}
```

All filter fields are optional.

| Field | Type | Description |
|---|---|---|
| `ticker` | `str` | Company ticker, e.g. `MSFT` |
| `cik` | `str` | SEC Central Index Key |
| `form` | `str` | SEC filing type, e.g. `10-Q` |
| `accession_number` | `str` | Unique SEC filing accession number |
| `filing_date` | `str` | Filing date in `YYYY-MM-DD` format |
| `reporting_period_end` | `str` | Reporting-period end date |
| `section` | `str` | Filing section associated with the chunk |

If multiple filters are provided, they should be treated as an AND condition.

Example:

```python
results = retrieve(
    query="What was Microsoft's quarterly revenue?",
    filters={
        "ticker": "MSFT",
        "form": "10-Q"
    },
    top_k=10
)
```

---

## 4. Return Type

`retrieve()` returns a ranked list of retrieved chunks:

```python
list[RetrievedChunk]
```

The results must be ordered from most relevant to least relevant.

```python
len(results) <= top_k
```

---

## 5. RetrievedChunk Schema

```python
RetrievedChunk = {
    "chunk_id": str,
    "text": str,
    "score": float,

    "section": str | None,

    "ticker": str | None,
    "cik": str,
    "company_name": str,

    "form": str,
    "accession_number": str,
    "filing_date": str,
    "reporting_period_end": str | None,

    "source_url": str | None,

    "chunking_version": str,
    "extraction_version": str,

    "metadata": dict
}
```

---

## 6. Field Definitions

### `chunk_id`

Unique identifier for the retrieved chunk.

This field is intended to support evaluation, debugging, and citation.

---

### `text`

The exact stored chunk text.

The retrieval layer should not rewrite or summarize this field.

---

### `score`

Ranking score produced by the retrieval layer.

Example:

```json
"score": 0.93
```

Higher values should indicate higher relevance within the same retrieval call.

The exact numeric scale may depend on the retrieval method, such as:

- dense retrieval
- lexical retrieval
- hybrid retrieval
- reranking

Consumers should primarily rely on result ordering unless score normalization is explicitly documented.

---

### `section`

Section associated with the chunk.

Example:

```text
Part I Item 2 — Results of Operations
```

This field may be `null` if no section label is available.

---

### Company Metadata

Example:

```json
{
  "ticker": "MSFT",
  "cik": "0000789019",
  "company_name": "Microsoft Corporation"
}
```

These fields identify the company associated with the filing.

---

### Filing Metadata

Example:

```json
{
  "form": "10-Q",
  "accession_number": "0001193125-26-191507",
  "filing_date": "2026-04-29",
  "reporting_period_end": "2026-03-31"
}
```

These fields identify the SEC filing associated with the returned chunk.

---

### `source_url`

URL of the source document associated with the chunk.

This supports citation and provenance tracing.

---

### Version Fields

Example:

```json
{
  "chunking_version": "manual-example-v1",
  "extraction_version": "manual-example-v1"
}
```

These fields allow retrieval results to be traced back to the correct corpus version.

---

### `metadata`

Additional chunk-level metadata provided by the extraction / chunking pipeline.

Example:

```json
{}
```

Consumers should not assume undocumented keys inside `metadata`.

---

## 7. Example Request

```python
results = retrieve(
    query="What was Microsoft's total revenue for the three months ended March 31, 2026?",
    filters={
        "ticker": "MSFT",
        "form": "10-Q",
        "reporting_period_end": "2026-03-31"
    },
    top_k=10
)
```

---

## 8. Example Response

```json
[
  {
    "chunk_id": "example-chunk-id-1",
    "text": "Total revenue 82,886 70,066 241,832 205,283 ...",
    "score": 0.93,

    "section": "Part I Item 1 — Income Statements",

    "ticker": "MSFT",
    "cik": "0000789019",
    "company_name": "Microsoft Corporation",

    "form": "10-Q",
    "accession_number": "0001193125-26-191507",
    "filing_date": "2026-04-29",
    "reporting_period_end": "2026-03-31",

    "source_url": "https://www.sec.gov/...",

    "chunking_version": "manual-example-v1",
    "extraction_version": "manual-example-v1",

    "metadata": {}
  }
]
```

---

## 9. Empty Results

If the request is valid but no matching chunks are found, return:

```python
[]
```

Do not return:

```python
None
```

---

## 10. Input Validation

### Empty Query

Invalid:

```python
retrieve("")
```

or:

```python
retrieve("   ")
```

Recommended behavior:

```python
ValueError("query must be a non-empty string")
```

---

### Invalid `top_k`

Invalid:

```python
top_k = 0
```

or:

```python
top_k = -5
```

Recommended behavior:

```python
ValueError("top_k must be a positive integer")
```

---

### Unknown Filter

Invalid example:

```python
filters = {
    "random_field": "abc"
}
```

Recommended behavior:

```python
ValueError("unsupported filter: random_field")
```

Unknown filters should not be silently ignored.

---

## 11. Ranking Contract

Returned chunks must be ordered from most relevant to least relevant.

```text
results[0] = highest-ranked result
results[1] = second-highest result
...
```

For evaluation purposes, ranking should be deterministic when the corpus, query, filters, retrieval configuration, and index version remain unchanged.

If two results have equal scores, the implementation should use a deterministic tie-break rule.

---

## 12. Evaluation Compatibility

The interface must support retrieval evaluation against the Gold Set.

Gold Set v0 currently contains:

- basic questions
- comparative questions
- deep questions
- quantitative questions

Some deep questions require evidence from multiple regions of the filing.

Therefore, `retrieve()` must return multiple ranked chunks rather than only one result.

The default:

```python
top_k = 10
```

is intended to support retrieval metrics such as:

- Recall@10
- MRR

The Evaluation team should be able to compare returned `chunk_id` values against approved gold evidence chunk IDs once final chunk IDs are available.

---

## 13. Retrieval vs Answer Generation

`retrieve()` SHOULD:

- locate relevant evidence
- rank chunks
- return chunk text
- return provenance metadata

`retrieve()` SHOULD NOT:

- generate the final natural-language answer
- perform financial calculations
- decide whether the answer is correct
- hide the retrieved evidence

For quantitative questions, the retrieval layer should retrieve the evidence containing the required values.

The downstream Agent or reasoning layer is responsible for performing the calculation.

---

## 14. Quantitative Data

The Data Engineering schema separately stores structured financial facts, including:

- numeric value
- unit
- period type
- period start
- period end
- instant date
- dimensions
- source reference

Version 0 defines `retrieve()` primarily as a ranked text-chunk retrieval interface.

Structured financial-fact retrieval or text-to-SQL may be incorporated into a future hybrid retrieval contract.

This remains an open design decision for later phases.

---

## 15. Source and Provenance

Every returned result should preserve enough information to trace the chunk back to the SEC filing and source document.

At minimum, v0 returns:

```text
chunk_id
section
ticker
cik
company_name
form
accession_number
filing_date
reporting_period_end
source_url
chunking_version
extraction_version
```

This allows Agent and Evaluation components to identify:

1. which company
2. which SEC filing
3. which source
4. which chunk
5. which processing version

produced a retrieved result.

---

## 16. Versioning

This document defines:

```text
Retrieval API Contract v0
```

Breaking interface changes should result in a new contract version.

Examples of potentially breaking changes include:

- renaming required output fields
- changing filter semantics
- changing return types
- removing fields

Adding optional metadata fields should normally not require a new major contract version.

---

## 17. Open Questions for Team Review

### Data Engineering

1. Which fields in `sec.chunk_citations` are guaranteed to remain available?
2. What structure may appear inside `chunks.metadata`?
3. What chunking-version naming convention should downstream teams expect?
4. When will final chunk IDs for the Gold Set corpus be available?

### Evaluation

1. Will retrieval relevance be evaluated primarily using `chunk_id`?
2. How should multiple acceptable chunks for the same evidence region be represented?
3. Is Recall@10 the default retrieval metric?
4. Is MRR calculated against the first relevant chunk?
5. How should multi-evidence deep questions be scored?

### Agent

1. Are the proposed output fields sufficient for answer generation and citation?
2. Does Agent need `offset_start` and `offset_end`?
3. Does Agent need source-document IDs or SHA-256?
4. Does Agent need raw retrieval scores?
5. Are additional company or filing filters required?

### RAG

1. Should `score` be raw or normalized?
2. Should hybrid retrieval expose component scores?
3. Should structured financial facts eventually be returned by `retrieve()`?
4. Should filters later use a typed object instead of a generic dictionary?

---

## 18. v0 Definition of Done

The Retrieval API Contract v0 is ready when:

- function inputs are agreed
- output schema is agreed
- required provenance fields are agreed
- empty-result behavior is agreed
- error behavior is agreed
- Evaluation confirms the schema supports retrieval metrics
- Agent confirms the output can be consumed
- Data Engineering confirms the required fields exist
- review comments from at least three relevant groups are resolved

---

## 19. Summary

Proposed public interface:

```python
def retrieve(
    query: str,
    filters: dict | None = None,
    top_k: int = 10
) -> list[RetrievedChunk]:
    ...
```

Core output:

```python
{
    "chunk_id": str,
    "text": str,
    "score": float,
    "section": str | None,

    "ticker": str | None,
    "cik": str,
    "company_name": str,

    "form": str,
    "accession_number": str,
    "filing_date": str,
    "reporting_period_end": str | None,

    "source_url": str | None,

    "chunking_version": str,
    "extraction_version": str,

    "metadata": dict
}
```

This contract is intentionally small for v0 and can be extended after Agent, Evaluation, and Data Engineering review.
