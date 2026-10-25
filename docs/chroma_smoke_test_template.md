# Chroma / Custom Smoke-Test Record

Use one row per query per backend. Copy the Agent team's two Microsoft FY2026 Q3 questions verbatim into the query column. Keep the same snapshot, filters, and `top_k` when comparing backends.

**Purpose:** integration and evidence/citation sanity check. Two questions are not a formal benchmark.

## Run setup

| Field | Value |
|---|---|
| Run date / operator | |
| RAG commit or branch | |
| Data snapshot label | |
| Snapshot source table/view | |
| Snapshot row count / hash (if available) | |
| Chroma index version | |
| Embedding model | |
| Backend(s) tested | |
| Agent commit/version | |
| Known data limitations | |

## Query results

| Question ID | Backend | Exact query | Filters | top_k | Latency (ms) | Returned? | Relevant evidence rank(s) | Relevant chunk_id(s) | Section / table title | Citation fields present? | SEC source opens to expected filing? | Notes / error |
|---|---|---|---|---:|---:|---|---|---|---|---|---|---|
| Microsoft Revenue Number | Custom | | | 5 | | | | | | | | |
| Microsoft Revenue Number | Chroma | | | 5 | | | | | | | | |
| Microsoft Revenue Drivers | Custom | | | 5 | | | | | | | | |
| Microsoft Revenue Drivers | Chroma | | | 5 | | | | | | | | |

## Citation check per returned result

Check at least the key evidence result for each query.

| Question ID | Backend | Rank | chunk_id | accession_number | ticker / company | form and reporting period | section | source_url | Text matches cited source? | Pass / issue |
|---|---|---:|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

## Optional Agent context check

Only fill this in if the Agent assembles retrieved passages into a context window. It does not change retrieval ranking.

| Question ID | Backend | Target context budget | Actual context tokens | Parent context used? | Original chunk text and citations preserved? | Notes |
|---|---|---:|---:|---|---|---|
| Microsoft Revenue Number | | ~1.9k | | | | |
| Microsoft Revenue Number | | ~3k | | | | |
| Microsoft Revenue Drivers | | ~1.9k | | | | |
| Microsoft Revenue Drivers | | ~3k | | | | |

## Result summary

- What worked:
- What failed or is unclear:
- Did Custom and Chroma return the same relevant evidence? If not, what changed in rank/content?
- Were citation fields complete and traceable?
- Is the data snapshot approved for formal evaluation, or only for technical smoke testing?
- Follow-up owner and due date:
