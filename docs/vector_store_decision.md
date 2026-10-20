# Architecture Review and Vector Store Decision

**Decision date:** 2026-10-16  
**Owners:** Retrieval/RAG workstream  
**Status:** MVP selected for implementation; team review due 2026-10-19  
**Scope:** Compare the current PostgreSQL export + custom hybrid pipeline with Chroma and Amazon OpenSearch, select the MVP serving architecture, and preserve Retrieval API v0 for the Agent team.

## 1. Decision summary

Use **Chroma Persistent Client as the MVP vector serving backend**. Keep the current custom implementation as a reproducible baseline and rollback path. In the Chroma MVP, dense candidates are retrieved from Chroma; the existing BM25 implementation and reciprocal rank fusion (RRF) are retained so Experiment 1 remains comparable. Reconsider Amazon OpenSearch when the end-to-end MVP is stable and shared AWS deployment, concurrency, or corpus size requires a managed search service.

This decision does **not** replace the Data team's PostgreSQL/RDS database. RDS remains the upstream system of record. Chroma is a derived, rebuildable serving index optimized for document retrieval.

## 2. Problem clarified after the 10/15 review

The existing pipeline exports canonical chunks from `sec.chunk_catalog`, writes `chunks.jsonl`, and creates local BM25, NumPy embedding, and metadata files. This was appropriate for a transparent first experiment, but it combines three responsibilities:

1. authoritative SEC data storage;
2. vector index persistence;
3. online lexical/vector ranking.

The review question was not whether SQL is allowed. It was whether online RAG queries should depend on a manual SQL export and brute-force local vector calculation when a vector store can persist embeddings and search them directly.

The target separation is:

```text
Data RDS/PostgreSQL (system of record)
    -> repeatable export/sync using stable chunk_id
    -> Chroma (derived vector serving index)
    -> retrieve(query, filters, top_k) / Retrieval API v0
    -> Agent LangChain tool
```

SQL is used during index build/refresh and for structured facts. It is not an extra online hop for every semantic retrieval request.

## 3. Requirements and decision criteria

The selected MVP must:

- work with the Data team's current RDS export and stable `chunk_id`;
- support BGE-small dense embeddings and metadata pre-filtering;
- preserve BM25 + dense + RRF hybrid behavior where practical;
- return the same 17-field Retrieval API v0 schema;
- require no Agent-side Python changes;
- remain reproducible on the fixed pilot corpus;
- be implementable and testable by 2026-10-22;
- avoid unnecessary cloud/IAM/cost blockers during the MVP;
- preserve a path to a shared production deployment.

## 4. Options

### Option A - Current RDS export + custom hybrid index

**Flow:** RDS -> CSV -> `chunks.jsonl` -> custom BM25 pickle + NumPy embedding matrix -> Python filtering/RRF.

**Strengths**

- already implemented and measured in Experiment 1;
- transparent scoring and easy error analysis;
- no external service or usage cost;
- deterministic rebuild from the same `chunks.jsonl`;
- full control over section-prefix filtering and RRF.

**Weaknesses**

- embeddings are searched by brute-force matrix multiplication;
- local files are difficult to share and update across services;
- process startup loads chunks, BM25, embeddings, and model locally;
- scaling, concurrency, backup, access control, and monitoring are owned by the team;
- does not demonstrate the vector-store architecture requested in the review.

**Best use:** experimental baseline, debugging, and rollback.

### Option B - Chroma MVP

**Flow:** RDS -> canonical `chunks.jsonl` -> persistent Chroma collection -> Chroma dense search + existing BM25/RRF -> Retrieval API v0.

**Strengths**

- lowest-risk change from the working baseline;
- persistent document, embedding, ID, and metadata storage;
- supports similarity search and metadata filters;
- runs locally without AWS/IAM work and can later run in client-server or managed mode;
- stable Data `chunk_id` can be used directly as the Chroma record ID;
- backend can be hidden behind the existing `retrieve()` contract.

**Weaknesses**

- local Persistent Client is not a multi-user production service;
- the MVP still owns BM25 and RRF outside Chroma to preserve exact baseline behavior;
- section-prefix semantics require translation to exact stored section values;
- a later shared deployment requires Chroma server/cloud or another backend.

**Best use:** current MVP and end-to-end demonstration.

### Option C - Amazon OpenSearch

**Flow:** RDS/S3 ingestion -> OpenSearch index containing text, metadata, and vectors -> native keyword/vector/hybrid query -> Retrieval API v0 adapter.

**Strengths**

- native lexical, vector, metadata-filtered, and hybrid search;
- managed AWS deployment, access policies, monitoring, and horizontal scale;
- better fit for shared services and a much larger S&P 500 corpus;
- reduces custom ranking infrastructure in the long term.

**Weaknesses**

- highest setup effort before 10/22: AWS permissions, collection/domain, network policy, index mapping, embedding ingestion, and credentials;
- cost and OCU/capacity decisions must be reviewed;
- more difficult to reproduce locally and in CI;
- tuning OpenSearch hybrid relevance would introduce another variable before the Gold Set is reviewed;
- schedule risk is high while Data backfill and pilot scope are still changing.

**Best use:** production candidate after the end-to-end MVP and evaluation harness are stable.

## 5. Trade-off matrix

Scores are 1 (poor) to 5 (strong) for the current project phase. A higher implementation-speed score means faster/safer delivery.

| Criterion | Weight | Custom | Chroma MVP | OpenSearch |
|---|---:|---:|---:|---:|
| Delivery by 10/22 | 25% | 5 | 4 | 2 |
| Retrieval features | 20% | 4 | 4 | 5 |
| Reproducibility/local testing | 15% | 5 | 5 | 2 |
| Shared deployment/scalability | 15% | 2 | 3 | 5 |
| Operational simplicity | 10% | 3 | 4 | 2 |
| Current Data/Agent compatibility | 10% | 4 | 5 | 3 |
| MVP cost control | 5% | 5 | 5 | 2 |
| **Weighted score / 5** | **100%** | **4.05** | **4.25** | **3.15** |

The custom approach remains viable, but Chroma better satisfies the review request without putting the 10/22 integration at risk. OpenSearch is technically strongest for production, not for this MVP deadline.

## 6. Selected MVP architecture

### Storage responsibilities

| Layer | Responsibility | Canonical? |
|---|---|---|
| Data PostgreSQL/RDS | filings, sections, tables, facts, provenance, preferred processing sets | Yes |
| `chunks.jsonl` export | versioned handoff/build input | Rebuildable snapshot |
| Chroma | chunk text, BGE embedding, flat filter metadata, stable Data `chunk_id` | Rebuildable serving index |
| BM25/RRF in RAG service | lexical candidates and rank fusion | Rebuildable runtime/index component |

### Online query path

1. Agent calls the existing `retrieve(query, filters, top_k)` or `sec_filing_search` tool.
2. The RAG service validates the same contract and filters.
3. Chroma returns dense candidates using the stored BGE embeddings and metadata filters.
4. Existing BM25 returns lexical candidates over the same records.
5. Existing RRF combines both rankings.
6. Results are mapped to the same 17 top-level fields, logged, and returned to the Agent.

### Configuration

```bash
RAG_BACKEND=chroma
RAG_CHROMA_DIR=data/chroma
```

Rollback/reproduction of Experiment 1:

```bash
RAG_BACKEND=custom
RAG_INDEX_DIR=data/index
```

No Agent code or tool schema changes between these configurations.

## 7. Acceptance criteria

The implementation is complete when:

- `python -m rag.cli index --backend chroma` builds a persistent collection;
- every Chroma ID equals the Data team's stable `chunk_id`;
- `retrieve()` accepts the existing query, filters, and `top_k` arguments;
- Chroma results pass Retrieval API v0 schema validation;
- ticker, form, period, table, and section-prefix filters behave consistently;
- no-match requests return `[]` and invalid input behavior is unchanged;
- the existing LangChain Agent wrapper imports and calls the same function;
- custom and Chroma can be switched only through configuration/environment;
- both backends can run on the same fixed corpus and Gold Set for comparison;
- logs record the backend and index version.

## 8. Evaluation plan

Use exactly the same frozen pilot export, BGE-small model, 30-question Gold Set, filter modes, and `top_k` values. Report:

- evidence recall@5 and @10;
- hit@5 and @10;
- MRR;
- provenance@10;
- mean and p95 retrieval latency;
- index build time and disk size;
- contract-test pass/fail.

Gold Set evidence is still draft, so architecture results remain preliminary until human review. Architecture selection is based mainly on delivery risk, reproducibility, interface compatibility, and operational fit; small quality differences should not be over-interpreted yet.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Local Chroma cannot serve multiple deployed processes safely | Use one RAG service for the MVP; evaluate Chroma server/cloud or OpenSearch for shared deployment |
| Metadata types/nulls are rejected | Flatten metadata and omit null values during ingestion |
| Section prefix filter differs from exact vector-store filters | Resolve allowed prefixes to the exact section values present in the collection |
| Chroma and custom dense rankings differ | Use the same contextual embedding text, BGE model, cosine metric, candidate count, and fixed corpus |
| Data backfill changes experiment results | Freeze accessions, processing versions, export timestamp, row count, and file hash |
| Chroma rollout blocks the demo | Keep `RAG_BACKEND=custom` as tested rollback |
| OpenSearch is delayed indefinitely | Re-open the decision when corpus/concurrency/deployment thresholds are defined after MVP |

## 10. Revisit triggers for OpenSearch

Re-evaluate OpenSearch if any of the following becomes true:

- the RAG service needs a shared AWS-managed endpoint;
- multiple users/services require concurrent retrieval;
- corpus growth makes local index build or query latency unacceptable;
- KPMG requires AWS-native access control, monitoring, backup, or networking;
- native managed hybrid-search operations materially reduce maintenance;
- a cost estimate and AWS permissions are approved.

## 11. References

- Chroma documentation: https://docs.trychroma.com/
- Chroma architecture and deployment modes: https://docs.trychroma.com/docs/overview/architecture
- OpenSearch hybrid search: https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/
- OpenSearch reciprocal rank fusion: https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/
- Amazon OpenSearch Serverless vector search: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html

