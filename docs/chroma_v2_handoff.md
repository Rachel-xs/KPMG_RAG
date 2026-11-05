# Chroma v2 parity and Agent handoff

This procedure completes Week 8 task P0-2. It compares Custom and Chroma on the same C1 chunks and Gold v1 questions, then produces the files Agent needs to select Chroma without changing its retrieval call.

## Inputs

- The named `chunks_C1` snapshot used to build both indexes.
- The same embedding model for both backends. The current controlled comparison uses `st:BAAI/bge-small-en-v1.5`.
- `eval/gold_v1.jsonl`. Until Evaluation signs off, include draft questions and label the result preliminary.

Do not compare a previously built Custom index with a Chroma index made from a different export. The parity script checks index version, embedder, and chunk count before accepting the result.

## Build both indexes from the same file

Place the approved snapshot at `data/chunks_C1/chunks.jsonl`. Derived index directories remain local and are not committed to GitHub.

```bash
python - <<'PY'
from pathlib import Path
from rag.index import build_index
from rag.chroma_backend import build_chroma_index

chunks = Path("data/chunks_C1/chunks.jsonl")
build_index(chunks, Path("data/index_C1"), "st:BAAI/bge-small-en-v1.5", Path("data/cache"))
build_chroma_index(chunks, Path("data/chroma_C1"), "st:BAAI/bge-small-en-v1.5", Path("data/cache"))
PY
```

## Run the controlled comparison

```bash
python scripts/chroma_parity.py \
  --custom-dir data/index_C1 \
  --chroma-dir data/chroma_C1 \
  --gold eval/gold_v1.jsonl \
  --include-drafts \
  --top-k 8 \
  --max-recall-delta 0.02
```

The acceptance check passes only when:

- both indexes have the same `index_version`, embedder, and chunk count; and
- the absolute difference in Gold v1 evidence recall is at most 0.02.

The command writes a summary report, per-question comparison, and `handoff_manifest.json` under `eval/results/chroma_parity/`. The manifest records the chunks checksum, both index metadata blocks, Git commit, and Agent environment variables.

## Agent configuration

Copy or share the derived `data/chroma_C1` directory through the team-approved artifact location. Do not commit the Chroma database to GitHub.

```bash
export RAG_BACKEND=chroma
export RAG_CHROMA_DIR=/absolute/path/to/chroma_C1
```

Agent continues to call the existing interface:

```python
retrieve(query, filters, top_k)
```

For the integration record, save the query, filters, `top_k`, returned chunk IDs, citation metadata, latency, index version, and trace ID when contract v1 is merged.
