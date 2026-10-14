# Gold set & evaluation

`gold_v0.jsonl` is a **draft** of 12 pilot questions (6 basic / 4 comparative / 2 deep).
Every question starts as `"status": "draft"`; drafts are ignored by `make exp1` unless you pass
`--include-drafts`. Target for v0: 30 questions (12 / 10 / 8, ~1/3 quantitative), reviewed with the
Business Use Case and Evaluation teams.

## Labelling workflow (Member D + one reviewer)

1. Build the pilot index (`make pilot`).
2. For each question, search for the evidence:
   `python -m rag.cli search "CET1 ratio" --ticker JPM --form 10-K --k 10`
3. Edit the question's `gold.evidence`: one item per **distinct piece of evidence** the answer needs
   (a comparative question over 3 companies needs 3 items). Make `contains` specific enough that it
   matches only the right chunks (a number, a distinctive phrase). Optionally add exact `chunk_ids`.
4. Have a second person check it, then set `"status": "labeled"` (or `"reviewed"`).

## Format

```json
{"qid": "C01", "tier": "comparative",
 "question": "Compare the CET1 ratios of JPM, BAC and C ...",
 "filters": {"ticker": ["JPM","BAC","C"], "form": "10-K"},
 "gold": {"chunk_ids": [],
          "evidence": [{"ticker": "JPM", "fiscal_year": 2025, "contains": ["CET1", "15.7%"]}, ...]},
 "expected": {"ticker": ["JPM","BAC","C"]},
 "quantitative": true, "status": "labeled", "notes": ""}
```

Evidence keys may use any of: `ticker, form, fiscal_year, fiscal_period, section, accession, is_table`
plus `contains` (all strings must appear, case-insensitive). An item may also list
`chunk_ids` — acceptable chunks for that one evidence region (any-of; Retrieval API v0 §10). Labelling by evidence rather than by
chunk_id keeps the gold set valid when we change chunking.

## Metrics (`rag/evaluate.py`)

| Metric | Meaning |
|---|---|
| `evidence_recall@k` | share of the question's evidence items found in the top-k |
| `hit@k` | any relevant chunk in the top-k |
| `mrr` | 1 / rank of the first relevant chunk |
| `provenance@k` | share of top-k chunks from the expected company (and period, if given) |
| `latency_ms` | retrieval latency |

Each run writes `eval/results/run_<timestamp>.json` (summary + index version + gold file) and
`per_question_<timestamp>.csv` (for error analysis).
