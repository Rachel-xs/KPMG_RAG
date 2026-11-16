# Holdout set request (RAG → Evaluation), 2026-11-16

**Why.** Mentor, 11/12: the 0.935 numeric accuracy was tuned on the same 155 questions we report it on (prompt v2,
top_k 15, `retrieve_multi` were all chosen on Gold Set v2). The final report needs a *pure holdout*: questions no
tuning decision has ever seen.

**What RAG has done.** The system under test is frozen as `configs/final_v1.yaml` (index `7a7ad9801f86`, hybrid
RRF 60, top_k 15, `retrieve_multi`, gpt-6.1-terra, prompt v2), tagged `final_v1` in git when the week-10 PR merges. It will not change before
the holdout run. The 155 Gold v2 questions become the *dev* set: any later tuning (e.g. narrative fixes) is done on
dev only and reported as such.

## What we ask for (by Thu 11/20)

30–40 new questions in the Gold Set v2 JSONL format (same fields as `eval/round1/benchmark_v2_1.jsonl`, including
`filters`, `answer`, `gold.evidence` and `rag_evidence` anchors), written by someone on Eval, **not shown to anyone on
RAG before the run**.

| Slice | Share | Notes |
|---|---|---|
| Companies | mostly the 9 non-MSFT companies | Gold v2 is 84/127 MSFT; the holdout should not be |
| Exact numeric | ~45% | income statement, balance sheet, cash flow, segment, per-share |
| Narrative / explanatory | ~40% | MD&A explanations, risk factors, accounting policies; with required points |
| Unanswerable | ~5 questions | not disclosed, future period, company not in corpus |
| **Stress questions** (overlaps the above) | ~1/3 | see below: mentor asked for "harder questions that could break RAG" |

Stress types (one or two each):
1. **Misspelled or informal company names**: "Mircon", "Caseys", "Take Two" (your finding: 98% → 19% scope accuracy)
2. **Analyst wording**: "top line", "opex", "FCF", "comps" instead of the filing's words
3. **Multi-step arithmetic**: a figure derived from 2–3 table cells (like the cash-flow reconciliation GSv0-MSFT-023)
4. **Relative periods**: "last quarter", "the most recent fiscal year", "same quarter a year ago"
5. **Cross-filing**: needs a 10-K and a 10-Q together (derived Q4) or two companies
6. **Narrative spread over sections**: the answer needs MD&A *and* a financial-statement note

## How the run works

1. Eval commits the holdout file to the Eval repo **after** RAG confirms the `final_v1` tag exists.
2. RAG runs once, unchanged:
   `python scripts/run_round1_reader.py --preset final_v1 --gold <holdout.jsonl> --out eval/results/holdout`
   plus `scripts/run_round1_eval.py` for retrieval, and hands the AnswerBlocks to Eval for official scoring.
3. We report dev and holdout side by side, with 95% confidence intervals, and the cost and latency per question.
   A gap is a finding, not something to tune away: any change made after seeing the holdout is a new preset
   (`final_v2`) and is reported as tuned-after-holdout.

Target: run 11/21–11/24 (before Thanksgiving), results in the 11/26 notes and the final report.
