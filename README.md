# KPMG × Columbia practicum: Retrieval & RAG

Retrieval over SEC 10-K and 10-Q filings for the KPMG practicum. The repo builds a hybrid index (BM25 plus dense retrieval with `BAAI/bge-small-en-v1.5`, fused with reciprocal rank fusion) over Data Engineering's chunks. It serves the index through `retrieve()` to the Agent team, and it scores the frozen system on Eval's question sets.

| | |
|---|---|
| Frozen systems | `final_v1` (`configs/final_v1.yaml`) and `final_v2` (`configs/final_v2.yaml`, longer narrative answers) |
| Serving backend | Chroma (`rag/chroma_backend.py`); the custom NumPy/BM25 backend is kept as the Experiment 1 baseline |
| Interface | [`docs/retrieval_api.md`](docs/retrieval_api.md) (contract v1–v1.2; v1.3 draft in review) |
| Pre-registered evaluation | [`docs/preregistration_objective_eval.md`](docs/preregistration_objective_eval.md), including the run record of every independent test |
| Data contract | [`docs/data_rag_schema_lock_v1.md`](docs/data_rag_schema_lock_v1.md) |

## Quick start: reproduce the frozen system on a new Mac

These steps were checked from a fresh clone and a fresh environment on 2026-11-26 (main @ `76d653b`, Apple silicon). They take about 20 minutes, most of it the PyTorch download.

**1. Environment** (Miniforge; Python 3.13):

```bash
git clone https://github.com/Rachel-xs/KPMG_RAG.git && cd KPMG_RAG
conda create -n kpmg python=3.13 -y && conda activate kpmg
pip install -r requirements.txt          # or requirements-lock.txt for the exact versions we ran
python -m pytest -q                      # expected: 193 passed, 1 skipped
```

The first retrieval downloads the embedding model `BAAI/bge-small-en-v1.5` (about 130 MB) from Hugging Face.

**2. Frozen index.** The index is not in Git: it holds filing text, which stays off public repositories. Ask the RAG team for `round1_frozen_7a7ad9801f86_full.zip` (43 MB; SHA-256 `1903a19f4145dd25eb0e9d3b39d8572de1f0195f2163b4ee4a578aaf81d7fc3a`) and unzip it inside `data/`:

```bash
cd data && unzip round1_frozen_7a7ad9801f86_full.zip && cd ..
# -> data/round1/index_C1 (chunks, BM25, embeddings, meta) and data/round1/chroma_C1 (Chroma store)
```

The older package `chroma_C1_persisted_7a7ad9801f86.zip` contains only `chroma_C1`. That is enough for serving, but the evaluation scripts below also need `index_C1`.

**3. Keys.** Copy `.env.example` to `.env`, then fill in `SEC_USER_AGENT` and `OPENAI_API_KEY`. The key is needed only for answer generation, not for retrieval. Never commit `.env` or send it over Slack.

**4. Check the index and reproduce the dev numbers:**

```bash
python scripts/repersist_chroma.py data/round1/chroma_C1 --check
# expected: "n_vectors": 3736, "in_saved_graph": 3736, ... "fully_persisted": true

python scripts/run_round1_eval.py --gold eval/round1/benchmark_v2_1.jsonl --backend chroma --multi --out eval/results/repro
# expected line:  | hybrid | 10 | 0.850 (n=127) | 0.892 (n=93) | 0.892 (n=93) | 0.735 (n=34) |
# and "Hybrid without filters ... @10 0.764"

python scripts/run_round1_reader.py --preset final_v1 --backend chroma --limit 3 --out eval/results/repro_reader
# expected: "searching data/round1/chroma_C1 (index_version 7a7ad9801f86)" and 3/3 correct (about $0.02)
```

If all three match, you have the system that produced the reported results. Retrieval is deterministic for a given index; the reader model can vary by about one question in 93 between runs, because the model does not accept `temperature=0`.

## Indexes

| Index | `index_version` | Contents | Used for |
|---|---|---|---|
| Frozen | `7a7ad9801f86` | 20 filings, 10 companies, 3,736 chunks | Every official score (dev, holdout A/B, XBRL A); the joint test with Agents |
| Full, 10 companies | `3abed1490b13` | 233 filings, the same 10 companies, FY2021–2027, 37,957 chunks | The demo (any year for the 10 companies); given to Agents |
| Full plus | `37c4eb2f1628` | 645 filings, 261 companies, 102,760 chunks | XBRL B and C, and the scale analysis only; not for the demo |

The 10 companies are AAPL, CASY, MCK, MDT, MSFT, MU, NKE, NTAP, PH and TTWO. Indexes come as zip packages from the RAG team (`share/` on the RAG lead's machine), never through GitHub. Indexes over about 33,000 chunks need the paged Chroma read (PR #37, main `6a7b001` or later).

## Serving `retrieve()` (Agent team)

Point the code at one index:

```bash
export RAG_BACKEND=chroma
export RAG_CHROMA_DIR=/absolute/path/to/data/round1/chroma_C1     # or the 233-filing index for the demo
# Leave RAG_INDEX_DIR and RAG_COVERAGE_MANIFEST unset: the pre-check then reads the retriever's own chunks,
# so the pre-check and retrieval always cover the same filings.
```

```python
from rag.retrieve import retrieve, retrieve_with_status, retrieve_multi
from rag.coverage import check_coverage, extract_request

retrieve_with_status("Microsoft total revenue Q3 FY2026",
                     filters={"ticker": "MSFT", "form": "10-Q", "fiscal_year": 2026, "fiscal_period": "Q3"},
                     top_k=15)
```

- `retrieve_with_status()` returns the chunks plus `evidence_status` (`ok` / `weak` / `empty`); `retrieve_multi()` runs one sub-search per company or filing for comparisons. The frozen systems read the top 15.
- `check_coverage()` is the deterministic pre-check. It answers "is this company and period in the corpus?" before any retrieval; see contract §19 and the v1.3 draft for the statuses and the routing rules.
- LangChain users: `rag.langchain_tool.make_sec_retrieval_tool()` wraps the same call as a `StructuredTool`.

Chunk `text` is the exact stored text and must be quoted as is. Anything derived (extracted values, inferred periods) belongs in a separate field. Calculations go through a deterministic tool, not the language model.

## Reproducing the evaluations

| What | Command (from the repo root) | Notes |
|---|---|---|
| Dev reader, `final_v1` | `python scripts/run_round1_reader.py --preset final_v1 --backend chroma` | Gold Set v2.1; scored with Eval's grader (`eval/vendor/kpmg_eval`) |
| Sealed holdout or XBRL set | `python scripts/run_round1_reader.py --preset final_v1 --backend chroma --gold <set.jsonl> --filters gold` (then once more with `--filters precheck`) | Check the file's SHA-256 against Eval's manifest before opening it. Run each configuration once, and return the answers before any analysis |
| Same, on the 645-filing index | add `--chroma-dir data/fullplus/chroma_C1 --expect-index-version 37c4eb2f1628` | The guard stops the run before any API call if the index differs; `summary.json` records the index actually searched (`searched_index`) |
| Retrieval only (no model calls) | `python scripts/run_round1_eval.py --gold <set.jsonl> --backend chroma --multi --out <dir>` | Strict evidence recall at k = 5, 8 and 10, by company and question type |
| Pre-check replay | `python scripts/run_precheck_replay.py --gold <set.jsonl> --out <dir>` | Companies resolved, unanswerable questions caught, misspelled names |
| Narrative judge | `python scripts/run_eval_judge.py` (dev) and `scripts/run_eval_judge_holdout.py` (holdout) | Runs Eval's Week 8 judge unchanged; needs Eval's repo next to this one |
| Human labels | `python scripts/holdout_hand_labels.py` | Merges blind rater sheets, agreement, adjudication, Eval's format |
| Query-rewriting study | `scripts/qr_extract_filters.py`, `qr_run_arm.py`, `qr_compare.py`, `qr_judge.py` | Exploratory; uses the Agents repo at `d89208c` |

Every independent run, with its commit, index and cost, is recorded in the run record at the end of the pre-registration.

## Building an index from Data's database

This needs read access to Data Engineering's RDS (credentials from the Data team, in `.env`; the scripts never print them).

```bash
python scripts/export_full_rds.py                                   # freeze list -> exports/full233.csv
bash scripts/build_full.sh exports/full233.csv                      # chunks -> C1 @ 460 tokens -> BM25, embeddings, Chroma
python scripts/repersist_chroma.py <new>/chroma_C1 --check          # must report every vector persisted
```

- `build_full.sh` explains its options at the top: the freeze list, the output folders, and the fiscal-year ends; for the 645-filing index, use `FYE="$(cat eval/fullplus_fye.txt)"`. Freeze lists (`eval/*_filings*.csv`) carry Data's internal IDs, so they are shared with the index packages, not in Git.
- Every build rebuilds the 20 frozen filings and compares them with `7a7ad9801f86` (3,736 of 3,736 chunk IDs and texts must match).
- The frozen index itself (`data/round1/`) is never rebuilt or touched.

## Repository layout

```
rag/        retrieval library: parsing, chunking, tables, BM25 + dense + RRF, Chroma backend, pre-check, contract
scripts/    exports, index builds, evaluation runners, judge and label tools
configs/    frozen presets (final_v1, final_v2) and the round-1 coverage manifest
eval/       gold sets and small public lookup files; results/ is not in Git
docs/       contract, data schema, pre-registration, decisions
tests/      unit and contract tests (also run against the mock in mock/)
mock/       stand-alone mock retriever with the same contract, for other teams
```

## Known limitations

- The frozen corpus is small: 20 filings. The 233- and 645-filing indexes rank slightly lower with filters (dev 0.835 against 0.850 at k = 10) and much lower without them (0.354), so the pre-check's filters are required at scale.
- On larger corpora, company-name matching needs an alias table: on the 645-filing index, "Amazon" does not resolve and "Cardinal Health" also matches Carnival.
- Period words with typos are not read, and compound questions are not split into sub-searches.
- Exhibits (Exhibit 21) and note tables are not indexed; relationship questions go to GraphRAG.
- In the 645-filing index, 10 filings from six companies (CAH, CL, ILMN, INTC, JPM, USB) have most of their text under section `unknown`, because Data's section split failed for them. Retrieval still works; the section labels are missing.

Full results, limitations and future work are in the final report.
