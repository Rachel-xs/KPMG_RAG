# Holdout set request (RAG → Evaluation), 2026-11-16

**Why.** Mentor, 11/12: the 0.935 numeric accuracy was tuned on the same 155 questions we report it on (prompt v2,
top_k 15, `retrieve_multi` were all chosen on Gold Set v2). The final report needs a *pure holdout*: questions no
tuning decision has ever seen.

**What RAG has done.** The system under test is frozen as `configs/final_v1.yaml` (index `7a7ad9801f86`, hybrid
RRF 60, top_k 15, `retrieve_multi`, gpt-6.1-terra, prompt v2), tagged `final_v1` in git when the week-10 PR merges. It will not change before
the holdout run. The 155 Gold v2 questions become the *dev* set: any later tuning (e.g. narrative fixes) is done on
dev only and reported as such.

## What we ask for

About 70 new questions in the Gold Set v2 JSONL format (same fields as `eval/round1/benchmark_v2_1.jsonl`, including
`filters`, `answer`, `gold.evidence` and `rag_evidence` anchors), written by someone on Eval, **not shown to anyone on
RAG before the run**, delivered as **two separate files**:

| Batch | Size | Due | Tests | Contents |
|---|---|---|---|---|
| **A** | ~40 | Thu 11/20 | `final_v1` (numbers, refusals, pre-check) | ~30 exact numeric, ~5 narrative, ~5 unanswerable |
| **B** | ~30 | Mon 11/24, kept sealed until RAG freezes `final_v2` (~11/27) | the narrative fixes tuned on dev after 11/16 | ~20 narrative / explanatory, ~5 exact numeric, ~5 unanswerable |

Why these sizes: with 18 numeric questions, 16/18 correct still has a 95% interval of 0.67–0.97, too wide to say
anything. About 35 numeric questions in total narrows it to roughly 0.75–0.96. Why two batches: RAG keeps tuning
narrative retrieval on dev after the freeze; a single holdout already used for `final_v1` could not validate those
changes honestly.

| Slice (both batches) | Share | Notes |
|---|---|---|
| Companies | mostly the 9 non-MSFT companies, but ~25% MSFT | Gold v2 is 84/127 MSFT; the MSFT share lets us separate "harder companies" from overfitting |
| **Stress questions** (overlaps the above) | ~1/3 | see below: mentor asked for "harder questions that could break RAG" |
| Labels | `stress_type` field on each stress question | so results can be reported stress vs normal |

Stress types (one or two each):
1. **Misspelled or informal company names**: "Mircon", "Caseys", "Take Two" (your finding: 98% → 19% scope accuracy)
2. **Analyst wording**: "top line", "opex", "FCF", "comps" instead of the filing's words
3. **Multi-step arithmetic**: a figure derived from 2–3 table cells (like the cash-flow reconciliation GSv0-MSFT-023)
4. **Relative periods**: "last quarter", "the most recent fiscal year", "same quarter a year ago"
5. **Cross-filing**: needs a 10-K and a 10-Q together (derived Q4) or two companies
6. **Narrative spread over sections**: the answer needs MD&A *and* a financial-statement note

## How the run works

1. Eval commits batch A to the Eval repo **after** RAG confirms the `final_v1` tag exists.
2. RAG runs once, unchanged:
   `python scripts/run_round1_reader.py --preset final_v1 --gold <holdout_A.jsonl> --out eval/results/holdout_A`
   plus `scripts/run_round1_eval.py` for retrieval and `scripts/run_precheck_replay.py --gold <holdout_A.jsonl>` for the
   pre-check, and hands the AnswerBlocks to Eval for official scoring.
3. Batch B is released only after RAG tags `final_v2`; same procedure with `--preset final_v2`.
4. We report dev and holdout side by side, sliced by company (MSFT / other) and stress vs normal,, with 95% confidence intervals and the cost and latency per question.
   A gap is a finding, not something to tune away: any change made after seeing the holdout is a new preset
   (`final_v2`) and is reported as tuned-after-holdout.

Target: batch A run 11/21–11/24 (before Thanksgiving); batch B run 11/28–11/29, before the 11/30 code freeze.
