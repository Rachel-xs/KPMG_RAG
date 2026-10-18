#!/usr/bin/env bash
# Experiment 1 on RDS chunks. Usage: bash scripts/run_exp1.sh exports/chunks.csv
set -euo pipefail
cd "$(dirname "$0")/.."
CSV="${1:-exports/chunks.csv}"
python scripts/rds_to_chunks.py "$CSV" data/chunks/chunks.jsonl --fye MSFT=0630,AAPL=0927,NVDA=0126
# re-anchor the gold evidence on the RDS chunk text (prints #matching chunks per evidence region)
python scripts/convert_gold.py eval/gold_set_v0.md data/chunks/chunks.jsonl eval/gold_v0_msft.jsonl
python -m rag.cli index --backend custom --embedder st:BAAI/bge-small-en-v1.5
python -m rag.cli eval --backend custom --gold eval/gold_v0_msft.jsonl --include-drafts --filters filtered,unfiltered
