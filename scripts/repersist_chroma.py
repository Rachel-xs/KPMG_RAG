"""Make an existing Chroma index deterministic: copy the collection (same ids, vectors, documents, metadata, same
index_version) into a new directory with every vector persisted in the saved HNSW graph. No re-embedding.

    python scripts/repersist_chroma.py --check data/round1/chroma_C1                 # report only
    python scripts/repersist_chroma.py data/round1/chroma_C1 data/round1/chroma_C1_persisted

Why: Chroma keeps the last (n mod sync_threshold) vectors only in its write-ahead log and re-inserts them into the
HNSW graph, multi-threaded, every time a process opens the collection, so the approximate dense top-100 differs
between runs (index 7a7ad9801f86: 736 of 3,736 vectors). See rag/chroma_backend.py HNSW_PERSIST.
"""
from __future__ import annotations

import argparse, json, shutil, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.chroma_backend import DEFAULT_COLLECTION, HNSW_PERSIST, _chromadb, persistence_report  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--check", action="store_true", help="only report how many vectors are persisted")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    a = ap.parse_args()
    src = Path(a.src)
    print("source:", json.dumps(persistence_report(src)))
    if a.check or not a.dst:
        return
    dst = Path(a.dst)
    if dst.exists():
        raise SystemExit(f"{dst} exists; choose a new directory")
    tmp = dst.with_name(dst.name + ".srccopy")  # read from a copy: opening a Chroma dir writes to it
    shutil.copytree(src, tmp)
    try:
        s = _chromadb().PersistentClient(path=str(tmp)).get_collection(a.collection)
        got = s.get(include=["embeddings", "documents", "metadatas"])
        meta = {k: v for k, v in (s.metadata or {}).items() if not k.startswith("hnsw:") or k == "hnsw:space"}
        c = _chromadb().PersistentClient(path=str(dst)).create_collection(a.collection, metadata={**meta, **HNSW_PERSIST})
        for i in range(0, len(got["ids"]), 1000):
            c.add(ids=got["ids"][i:i + 1000], embeddings=got["embeddings"][i:i + 1000],
                  documents=got["documents"][i:i + 1000], metadatas=got["metadatas"][i:i + 1000])
        new = c.get(include=["embeddings"])
        a = dict(zip(got["ids"], np.asarray(got["embeddings"])))
        b = dict(zip(new["ids"], np.asarray(new["embeddings"])))
        same = a.keys() == b.keys() and all(np.allclose(a[k], b[k], atol=1e-6) for k in a)  # cosine re-normalises: ~3e-8
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = json.loads((src / "meta.json").read_text())
    m.update({"hnsw_persisted": True, "repersisted_from": str(src)})
    (dst / "meta.json").write_text(json.dumps(m, indent=2))
    for extra in ("embedder.pkl",):
        if (src / extra).exists():
            shutil.copy2(src / extra, dst / extra)
    rep = persistence_report(dst)
    print("new:   ", json.dumps(rep), "| same ids, same vectors (to 1e-6):", same)
    if not (same and rep["fully_persisted"]):
        raise SystemExit("check failed")


if __name__ == "__main__":
    main()
