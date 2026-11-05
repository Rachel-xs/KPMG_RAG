"""Compare Custom and Chroma on the same chunks, embedder, questions, and filters.

This is the Week 8 P0-2 acceptance check.  It intentionally evaluates both
backends in one process so the controls cannot drift between two CLI runs.

Example:

    python scripts/chroma_parity.py \
      --custom-dir data/index_C1 \
      --chroma-dir data/chroma_C1 \
      --gold eval/gold_v1.jsonl \
      --include-drafts --top-k 8 --max-recall-delta 0.02

The command writes a JSON report, a per-question CSV, and a handoff manifest.
It exits non-zero when the two indexes were not built from the same chunk file
or when the absolute evidence-recall difference exceeds the allowed threshold.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.evaluate import load_gold, score_question  # noqa: E402
from rag.retrieve import make_retriever  # noqa: E402


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _mean(rows: list[dict], key: str) -> float:
    vals = [float(r[key]) for r in rows]
    return sum(vals) / len(vals) if vals else 0.0


def compare(
    custom_dir: Path,
    chroma_dir: Path,
    gold_path: Path,
    out_dir: Path,
    top_k: int = 8,
    include_drafts: bool = False,
    max_recall_delta: float = 0.02,
) -> dict:
    custom_dir, chroma_dir = Path(custom_dir), Path(chroma_dir)
    custom = make_retriever("custom", custom_dir, log_dir=None, method="hybrid")
    chroma = make_retriever("chroma", chroma_dir, log_dir=None, method="hybrid")

    custom_iv = str(custom.meta["index_version"])
    chroma_iv = str(chroma.meta["index_version"])
    same_index_version = custom_iv == chroma_iv
    same_embedder = str(custom.meta.get("embedder")) == str(chroma.meta.get("embedder"))
    same_chunk_count = int(custom.meta.get("n_chunks", -1)) == int(chroma.meta.get("n_chunks", -2))

    gold = load_gold(gold_path, include_drafts=include_drafts)
    if not gold:
        raise SystemExit(
            "No scorable questions found. Use --include-drafts while Gold v1 is awaiting Eval sign-off."
        )

    rows: list[dict] = []
    for question in gold:
        filters = question.get("filters")
        left = custom.search(question["question"], filters=filters, top_k=top_k, method="hybrid")
        right = chroma.search(question["question"], filters=filters, top_k=top_k, method="hybrid")
        ls = score_question(question, left["results"], (top_k,))
        rs = score_question(question, right["results"], (top_k,))
        left_ids = [r["chunk_id"] for r in left["results"]]
        right_ids = [r["chunk_id"] for r in right["results"]]
        overlap_denominator = max(1, min(top_k, max(len(left_ids), len(right_ids))))
        overlap = len(set(left_ids) & set(right_ids)) / overlap_denominator
        rows.append(
            {
                "qid": question["qid"],
                "category": question.get("category", ""),
                "custom_recall": ls[f"evidence_recall@{top_k}"],
                "chroma_recall": rs[f"evidence_recall@{top_k}"],
                "recall_delta": rs[f"evidence_recall@{top_k}"] - ls[f"evidence_recall@{top_k}"],
                "custom_mrr": ls["mrr"],
                "chroma_mrr": rs["mrr"],
                "custom_latency_ms": left["latency_ms"],
                "chroma_latency_ms": right["latency_ms"],
                "top_k_id_overlap": overlap,
                "custom_chunk_ids": "|".join(left_ids),
                "chroma_chunk_ids": "|".join(right_ids),
            }
        )

    custom_recall = _mean(rows, "custom_recall")
    chroma_recall = _mean(rows, "chroma_recall")
    recall_delta = chroma_recall - custom_recall
    controls_pass = same_index_version and same_embedder and same_chunk_count
    recall_pass = abs(recall_delta) <= max_recall_delta
    passed = controls_pass and recall_pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks_file = custom_dir / "chunks.jsonl"
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "source_chunks": str(chunks_file),
        "source_chunks_sha256": _sha256(chunks_file) if chunks_file.exists() else None,
        "custom": custom.meta,
        "chroma": chroma.meta,
        "controls": {
            "same_index_version": same_index_version,
            "same_embedder": same_embedder,
            "same_chunk_count": same_chunk_count,
        },
        "agent_configuration": {
            "RAG_BACKEND": "chroma",
            "RAG_CHROMA_DIR": str(chroma_dir),
        },
    }
    report = {
        "status": "PASS" if passed else "FAIL",
        "acceptance_rule": f"same input controls and abs(recall_delta) <= {max_recall_delta}",
        "gold_file": str(gold_path),
        "n_questions": len(rows),
        "method": "hybrid",
        "filters": "question filters applied",
        "top_k": top_k,
        "custom": {
            "evidence_recall": round(custom_recall, 6),
            "mrr": round(_mean(rows, "custom_mrr"), 6),
            "mean_latency_ms": round(_mean(rows, "custom_latency_ms"), 2),
        },
        "chroma": {
            "evidence_recall": round(chroma_recall, 6),
            "mrr": round(_mean(rows, "chroma_mrr"), 6),
            "mean_latency_ms": round(_mean(rows, "chroma_latency_ms"), 2),
        },
        "recall_delta_chroma_minus_custom": round(recall_delta, 6),
        "mean_top_k_id_overlap": round(_mean(rows, "top_k_id_overlap"), 6),
        "controls": manifest["controls"],
    }

    (out_dir / "handoff_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out_dir / f"chroma_parity_{stamp}.json").write_text(json.dumps(report, indent=2) + "\n")
    with (out_dir / f"chroma_parity_per_question_{stamp}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps(report, indent=2))
    print(f"\nArtifacts: {out_dir}")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--custom-dir", type=Path, required=True)
    p.add_argument("--chroma-dir", type=Path, required=True)
    p.add_argument("--gold", type=Path, default=ROOT / "eval" / "gold_v1.jsonl")
    p.add_argument("--out-dir", type=Path, default=ROOT / "eval" / "results" / "chroma_parity")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--max-recall-delta", type=float, default=0.02)
    p.add_argument("--include-drafts", action="store_true")
    args = p.parse_args()
    report = compare(
        args.custom_dir,
        args.chroma_dir,
        args.gold,
        args.out_dir,
        args.top_k,
        args.include_drafts,
        args.max_recall_delta,
    )
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
