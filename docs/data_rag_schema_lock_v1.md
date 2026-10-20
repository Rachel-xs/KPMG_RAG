# Data Engineering -> RAG Chunk Schema Lock v1

**Status:** Proposed for cross-team sign-off  
**Owners:** Data Engineering and RAG  
**Consumers:** RAG, Agent, Evaluation  
**Handoff format:** UTF-8 JSONL, one chunk per line  
**Contract boundary:** This document governs Data -> RAG input. `docs/retrieval_api.md` separately governs RAG -> Agent/Evaluation output.

## 1. Lock decision

After sign-off, Data Engineering will deliver one record per retrievable chunk using the canonical names and rules below. RAG may derive serving-only fields such as fiscal labels, token counts, embeddings, retrieval scores, and `index_version`, but it must preserve Data's stable identifiers and source text.

Schema lock means fields cannot be renamed, removed, retyped, or semantically changed without the version/change process in section 7. Additive nullable fields are allowed after notice.

## 2. Required fields

| Field | Type | Nullable? | Rule |
|---|---|---:|---|
| `chunk_id` | string | No | Globally unique within the delivered processing version; stable across identical rebuilds; treated as opaque by consumers. |
| `text` | string | No | Non-empty original extracted chunk text. Do not summarize or rewrite it. Preserve Markdown table rows when present. |
| `accession_number` | string | No | SEC accession with dashes, e.g. `0001193125-26-191507`; canonical cross-team filing key. |
| `cik` | string | No | Ten-digit, zero-padded CIK. |
| `company_name` | string | No | Filing company name. |
| `ticker` | string | Conditional | Uppercase ticker when available; may be null only if the filing has no validated ticker mapping. |
| `form` | string | No | Canonical SEC form, initially `10-K` or `10-Q`. |
| `filing_date` | date string | No | `YYYY-MM-DD`. |
| `reporting_period_end` | date string | Conditional | `YYYY-MM-DD`; null only when the source filing does not provide a period of report. |
| `chunk_index` | integer | No | Zero-based position inside one accession and processing version; unique with `accession_number`. |
| `section_id` | string | Conditional | Stable source section identifier when extraction produces one. |
| `section_type` | string | Conditional | Canonical SEC section/item label when known, e.g. `Part I Item 2`; otherwise null, not a fabricated label. |
| `original_title` | string | Conditional | Human-readable source section/table title when known. |
| `is_table` | boolean | No | Explicit Data-owned table flag. Do not require RAG to infer this from punctuation or digits. |
| `source_url` | string | No | Direct SEC source document URL used for citation. |
| `chunking_version` | string | No | Changes whenever chunk boundaries, ordering, overlap, or table splitting rules change. |
| `extraction_version` | string | No | Changes whenever extraction/parsing changes the emitted text or source mapping. |
| `source_sha256` | string | Conditional | Hash of the source artifact when available; recommended for reproducibility. |
| `offset_start` | integer | Conditional | Inclusive character offset in the identified source representation, when available. |
| `offset_end` | integer | Conditional | Exclusive character offset; must be greater than `offset_start`, when available. |

`Conditional` means the field must be present in every JSON object, but its value may be `null` only under the stated condition. This keeps row shape stable while acknowledging current extraction gaps.

## 3. Optional/additive fields

| Field | Type | Purpose |
|---|---|---|
| `section_topic` | string or null | Normalized topic for analysis/routing. |
| `parent_chunk_id` | string or null | Links split table/text fragments to their logical parent. |
| `language` | string or null | Document language code. |
| `processing_timestamp` | timestamp or null | Audit only; not used as a retrieval identifier. |

Unknown fields must be preserved where practical but cannot be required by RAG, Agent, or Evaluation until documented here.

## 4. RAG-derived fields

RAG may derive the following and must record the rule/configuration used:

- `fiscal_year` and `fiscal_period`, until Data supplies validated values;
- `section` as the Retrieval API canonical label, using `section_type` and `original_title`;
- `section_title` from `original_title`;
- `n_tokens`;
- contextual embedding text (never returned as the original `text`);
- embeddings, lexical index, retrieval scores, and ranks;
- `index_version`, computed from the frozen handoff snapshot and index configuration.

Derived values do not overwrite Data's original fields.

## 5. Record-level invariants

Every delivered snapshot must satisfy all of the following:

1. `chunk_id` is unique; `(accession_number, chunk_index)` is also unique within one processing version.
2. `text.strip()` is non-empty.
3. Dates and accession numbers use the formats above.
4. `source_url` points to the same filing identified by `accession_number`.
5. All chunks from one accession agree on filing-level metadata.
6. Table text preserves headers and rows in Markdown or another agreed lossless representation, with `is_table=true`.
7. No gold questions, expected answers, or evaluation labels appear in the index corpus.
8. A snapshot manifest records row count, accessions, export timestamp, source table/view, schema version, processing versions, and file SHA-256.

## 6. Snapshot and pilot-corpus lock

A formal experiment may begin only after the teams record:

- the authoritative RDS source table/view (`sec.chunk_catalog`, `sec.chunk_citations`, or a validated view);
- the approved company/accession list;
- `schema_version=data-rag-chunk-v1`;
- included `chunking_version` and `extraction_version` values;
- row count, export timestamp, and snapshot hash;
- known data-quality exceptions.

The current MSFT validation used 210 records from `sec.chunk_citations`. It proves technical compatibility with Chroma, but it is not yet the formal frozen pilot corpus because the authoritative processing set and corpus list still require Data-team confirmation.

## 7. Change process

- **Patch/no contract bump:** documentation clarification or an additive nullable field.
- **Minor version:** new optional semantics that consumers may adopt gradually.
- **Major version:** rename, removal, type change, nullability change, identifier change, or changed meaning of an existing field.
- Proposed changes must identify affected Data export, RAG adapter/index, Agent citations, Evaluation labels, migration date, and backward-compatibility plan.
- RAG retains an adapter for the previous locked version until the new snapshot passes conformance and integration tests.

## 8. Sign-off checklist

| Decision | Data | RAG | Agent | Evaluation |
|---|---|---|---|---|
| Field names, types, nullability | Pending | Proposed | Review | Review |
| Stable `chunk_id` and accession join | Pending | Proposed | Review | Review |
| Canonical source table/view | Pending | Acknowledged blocker | FYI | FYI |
| Official pilot accessions | Pending | Pending | FYI | Review |
| Table representation and `is_table` | Pending | Proposed | Review | Review |
| Retrieval API v0 unchanged | FYI | Confirmed | Pending smoke test | Pending review |

The schema becomes **Locked v1** only after Data and RAG approve the first five decisions and Agent/Evaluation confirm there is no downstream blocker. Until then, its status remains **Proposed**.

