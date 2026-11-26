#!/bin/bash
# Full-corpus build (233 filings) plus the 21 round-1 filings of the same version.
#   bash scripts/build_full.sh exports/full233.csv                                   # source sets (11/23)
#   FULL=data/full233_legacy SUB=data/leg21 FREEZE=eval/full_filings_legacy.csv \
#     bash scripts/build_full.sh exports/full233_legacy.csv                            # legacy sets (11/24)
# Writes data/full233/ and data/src21/ only. data/round1/ (the frozen index 7a7ad9801f86) is never touched.
# Same steps and settings as build_round1.sh: C1 @ 460 tokens with parents, bge-small, custom + Chroma.
set -euo pipefail
CSV="${1:?usage: build_full.sh <full export csv>}"
PY="${PY:-python}"
TOK="${TOK:-$(ls ~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/*/tokenizer.json | head -1)}"
EMB="st:BAAI/bge-small-en-v1.5"
FULL="${FULL:-data/full233}"
SUB="${SUB:-data/src21}"
FREEZE="${FREEZE:-eval/full_filings.csv}"
# Same fiscal-year ends as round 1; 52/53-week filers use the nominal date (fiscal_label has a 10-day tolerance).
FYE="${FYE:-AAPL=0927,CASY=0430,MCK=0331,MDT=0424,MSFT=0630,MU=0903,NKE=0531,NTAP=0424,PH=0630,TTWO=0331}"  # override for the extended index: FYE="$(cat eval/fullplus_fye.txt)"

echo "== 1/6 CSV -> chunks_A"
"$PY" scripts/rds_to_chunks.py "$CSV" "$FULL/chunks_A/chunks.jsonl" --fye "$FYE"
echo "== 2/6 check against freeze list ($FREEZE)"
"$PY" scripts/check_round1_export.py "$FULL/chunks_A/chunks.jsonl" "$FREEZE" | tail -3
echo "== 3/6 C1@460 (with parents)"
"$PY" scripts/build_chunk_variant.py --variant C1 --max-tokens 460 --with-parents \
  --in "$FULL/chunks_A/chunks.jsonl" --out "$FULL/chunks_C1/chunks.jsonl" --tokenizer "$TOK"
echo "== 4/6 subset: the 21 round-1 filings, new version"
"$PY" - "$FULL/chunks_C1/chunks.jsonl" "$SUB/chunks_C1/chunks.jsonl" <<'PY'
import csv, json, sys
from pathlib import Path
keep = {r["accession_number"] for r in csv.DictReader(open("eval/round1_filings.csv"))}
src, dst = Path(sys.argv[1]), Path(sys.argv[2]); dst.parent.mkdir(parents=True, exist_ok=True)
n = accs = 0; seen = set()
with open(src) as f, open(dst, "w") as g:
    for line in f:
        c = json.loads(line)
        if c["accession"] in keep:
            g.write(line); n += 1; seen.add(c["accession"])
print(f"subset: {n} chunks from {len(seen)}/{len(keep)} filings")
PY
echo "== 4b regression: SUB vs frozen data/round1/chunks_C1 (same filings, chunk ids and text)"
"$PY" - "$SUB/chunks_C1/chunks.jsonl" data/round1/chunks_C1/chunks.jsonl <<'PY'
import json, sys
new = {json.loads(l)["chunk_id"]: json.loads(l) for l in open(sys.argv[1])}
old = {json.loads(l)["chunk_id"]: json.loads(l) for l in open(sys.argv[2])}
accs = {c["accession"] for c in old.values()}
newf = {k: v for k, v in new.items() if v["accession"] in accs}
same = sum(1 for k, v in old.items() if k in newf and newf[k]["text"] == v["text"])
print(f"frozen filings: {len(accs)}; frozen chunks {len(old)}, rebuilt {len(newf)}, identical id+text {same}")
print("REGRESSION OK" if same == len(old) == len(newf) else "REGRESSION DIFFERS (expected only for a source-set build)")
PY
echo "== 5/6 custom + Chroma indexes ($FULL and $SUB)"
"$PY" - "$EMB" "$FULL" "$SUB" <<'PY'
import sys
from pathlib import Path
from rag.index import build_index
from rag.chroma_backend import build_chroma_index
emb = sys.argv[1]
for out in map(Path, sys.argv[2:]):
    chunks = out / "chunks_C1" / "chunks.jsonl"
    print(f"-- {out}")
    build_index(chunks, out / "index_C1", emb, Path("data/cache"))
    build_chroma_index(chunks, out / "chroma_C1", emb, Path("data/cache"))
PY
echo "== 6/6 persistence check and index versions"
for d in "$FULL" "$SUB"; do
  "$PY" scripts/repersist_chroma.py --check "$d/chroma_C1"
  "$PY" -c "import json,sys;m=json.load(open(sys.argv[1]));print(sys.argv[1], 'index_version', m['index_version'], 'n_chunks', m['n_chunks'], 'hnsw_persisted', m.get('hnsw_persisted'))" "$d/chroma_C1/meta.json"
done
echo "Done. Frozen index untouched: data/round1/chroma_C1 (7a7ad9801f86)."
