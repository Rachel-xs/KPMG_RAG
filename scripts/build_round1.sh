#!/bin/bash
# Round 1 corpus build: DBeaver CSV of the 21 frozen filings -> chunks (A) -> C1@460 -> custom + Chroma -> parity.
#   bash scripts/build_round1.sh exports/round1_21.csv
# Needs: the repo venv (PY=...), the bge-small tokenizer in the HF cache, chromadb.
set -euo pipefail
CSV="${1:?usage: build_round1.sh <round1 export csv>}"
PY="${PY:-python}"
TOK="${TOK:-$(ls ~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/*/tokenizer.json | head -1)}"
EMB="st:BAAI/bge-small-en-v1.5"
OUT=data/round1
# Fiscal-year ends (MMDD) of the 10 companies; 52/53-week filers use the nominal date (fiscal_label has a 10-day tolerance).
FYE="AAPL=0927,CASY=0430,MCK=0331,MDT=0424,MSFT=0630,MU=0903,NKE=0531,NTAP=0424,PH=0630,TTWO=0331"

echo "== 1/5 CSV -> chunks_A"
"$PY" scripts/rds_to_chunks.py "$CSV" "$OUT/chunks_A/chunks.jsonl" --fye "$FYE"
echo "== 2/5 check against freeze list"
"$PY" scripts/check_round1_export.py "$OUT/chunks_A/chunks.jsonl" eval/round1_filings.csv
echo "== 3/5 C1@460 (with parents)"
"$PY" scripts/build_chunk_variant.py --variant C1 --max-tokens 460 --with-parents \
  --in "$OUT/chunks_A/chunks.jsonl" --out "$OUT/chunks_C1/chunks.jsonl" --tokenizer "$TOK"
echo "== 4/5 custom + Chroma indexes from the same file"
"$PY" - "$OUT" "$EMB" <<'PY'
import sys
from pathlib import Path
from rag.index import build_index
from rag.chroma_backend import build_chroma_index
out, emb = Path(sys.argv[1]), sys.argv[2]
chunks = out / "chunks_C1" / "chunks.jsonl"
build_index(chunks, out / "index_C1", emb, Path("data/cache"))
build_chroma_index(chunks, out / "chroma_C1", emb, Path("data/cache"))
PY
echo "== 5/5 parity (Gold v1 until Gold v2 lands; preliminary)"
"$PY" scripts/chroma_parity.py --custom-dir "$OUT/index_C1" --chroma-dir "$OUT/chroma_C1" \
  --gold eval/gold_v1.jsonl --include-drafts --top-k 8 --max-recall-delta 0.02 \
  --out-dir eval/results/chroma_parity_round1 || echo "parity check did not pass, see report"
echo "Done. Agent: export RAG_BACKEND=chroma RAG_CHROMA_DIR=$(pwd)/$OUT/chroma_C1"
