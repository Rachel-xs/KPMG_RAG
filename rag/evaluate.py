"""Retrieval evaluation harness (Experiment 1: BM25 vs dense vs hybrid, with/without filters).

Gold format (one JSON object per line) — see eval/README.md:
  {"qid": "B01", "tier": "basic", "question": "...", "filters": {...},
   "gold": {"chunk_ids": [...], "evidence": [{"ticker": "JPM", "form": "10-K", "contains": ["..."]}]},
   "expected": {"ticker": ["JPM"]}, "quantitative": true, "status": "labeled"}

A retrieved chunk satisfies an evidence item if every metadata key in the item matches and the
chunk text contains ALL `contains` strings (case-insensitive). Labelling by evidence instead of
chunk_id keeps the gold set valid when chunking changes.

Metrics per question (averaged by tier and overall):
  evidence_recall@k  share of evidence items satisfied by >= 1 of the top-k chunks
  hit@k              1 if any top-k chunk is relevant
  mrr                1 / rank of the first relevant chunk (0 if none in top max(k))
  provenance@k       share of top-k chunks whose company/period match `expected`
"""
from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from .retrieve import Retriever

META_KEYS = ("ticker", "form", "fiscal_year", "fiscal_period", "section", "accession", "accession_number", "is_table")
_ALIASES = {"accession": "accession_number"}


def _field(chunk: dict, key: str):
    """Value of `key` in a RetrievedChunk (top-level field first, then metadata)."""
    key = _ALIASES.get(key, key)
    if key in chunk:
        return chunk[key]
    return chunk.get("metadata", {}).get(key)


def load_gold(path: Path, include_drafts: bool = False) -> list[dict]:
    """Questions with status 'labeled' or 'reviewed' (plus 'draft' if include_drafts) that have gold."""
    rows = [json.loads(l) for l in open(path) if l.strip() and not l.lstrip().startswith("//")]
    ok = {"labeled", "reviewed"} | ({"draft"} if include_drafts else set())
    return [
        r for r in rows
        if r.get("status", "labeled") in ok and (r.get("gold", {}).get("chunk_ids") or r.get("gold", {}).get("evidence"))
    ]


def _meta_match(spec: dict, chunk: dict) -> bool:
    for key in META_KEYS:
        if key in spec:
            want = spec[key] if isinstance(spec[key], list) else [spec[key]]
            if str(_field(chunk, key)).upper() not in {str(w).upper() for w in want}:
                return False
    return True


def evidence_hits(item: dict, chunk: dict) -> bool:
    """An evidence item may list acceptable `chunk_ids` (any-of) and/or metadata + `contains`."""
    if chunk["chunk_id"] in set(item.get("chunk_ids", [])):
        return True
    if item.get("chunk_ids") and not item.get("contains") and not any(k in item for k in META_KEYS):
        return False
    if not _meta_match(item, chunk):
        return False
    text = chunk["text"].lower()
    return all(s.lower() in text for s in item.get("contains", []))


def is_relevant(gold: dict, chunk: dict) -> bool:
    if chunk["chunk_id"] in set(gold.get("chunk_ids", [])):
        return True
    return any(evidence_hits(e, chunk) for e in gold.get("evidence", []))


def score_question(q: dict, results: list[dict], ks: tuple[int, ...]) -> dict:
    gold = q["gold"]
    rel = [is_relevant(gold, r) for r in results]
    out = {}
    first = next((i for i, x in enumerate(rel, 1) if x), None)
    out["mrr"] = 1.0 / first if first else 0.0
    items = list(gold.get("evidence", [])) + [{"chunk_id": cid} for cid in gold.get("chunk_ids", [])]
    for k in ks:
        top = results[:k]
        sat = 0
        for it in items:
            if "chunk_id" in it:
                sat += any(r["chunk_id"] == it["chunk_id"] for r in top)
            else:
                sat += any(evidence_hits(it, r) for r in top)
        out[f"evidence_recall@{k}"] = sat / len(items) if items else 0.0
        out[f"hit@{k}"] = float(any(rel[:k]))
        exp = q.get("expected")
        if exp and top:
            out[f"provenance@{k}"] = sum(_meta_match(exp, r) for r in top) / len(top)
    return out


def run_eval(
    index_dir: Path,
    gold_path: Path,
    out_dir: Path,
    methods=("bm25", "dense", "hybrid"),
    ks=(5, 10),
    filter_modes=("filtered", "unfiltered"),
    log_dir: Path | None = None,
    include_drafts: bool = False,
) -> list[dict]:
    retr = Retriever(index_dir, log_dir=log_dir)
    gold = load_gold(gold_path, include_drafts)
    if not gold:
        raise SystemExit(
            f"No labeled questions in {gold_path}. Verify the evidence of each question against the filings and set "
            f'"status": "labeled" — or pass --include-drafts to try the draft set anyway.'
        )
    kmax = max(ks)
    per_q, agg = [], defaultdict(lambda: defaultdict(list))
    for fm in filter_modes:
        for method in methods:
            for q in gold:
                filters = q.get("filters") if fm == "filtered" else None
                resp = retr.search(q["question"], filters=filters, top_k=kmax, method=method)
                s = score_question(q, resp["results"], ks)
                row = {"qid": q["qid"], "tier": q.get("tier", "?"), "method": method, "filters": fm, "latency_ms": resp["latency_ms"], **s}
                per_q.append(row)
                for tier in (row["tier"], "ALL"):
                    for m, v in s.items():
                        agg[(fm, method, tier)][m].append(v)
                    agg[(fm, method, tier)]["latency_ms"].append(resp["latency_ms"])

    summary = []
    for (fm, method, tier), metrics in sorted(agg.items()):
        summary.append(
            {"filters": fm, "method": method, "tier": tier, "n": len(metrics["mrr"]),
             **{m: round(sum(v) / len(v), 4) for m, v in metrics.items()}}
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run = {"timestamp": stamp, "index": retr.meta, "gold_file": str(gold_path), "n_questions": len(gold),
           "include_drafts": include_drafts, "summary": summary}
    (out_dir / f"run_{stamp}.json").write_text(json.dumps(run, indent=2))
    with open(out_dir / f"per_question_{stamp}.csv", "w", newline="") as f:
        cols = sorted({k for r in per_q for k in r}, key=lambda c: (c not in ("qid", "tier", "method", "filters"), c))
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(per_q)
    _print_table(summary, ks)
    print(f"\n[eval] saved {out_dir / f'run_{stamp}.json'}")
    return summary


def _print_table(summary: list[dict], ks) -> None:
    cols = ["filters", "method", "tier", "n", "mrr"] + [f"evidence_recall@{k}" for k in ks] + [f"provenance@{max(ks)}", "latency_ms"]
    print("\n" + "  ".join(f"{c:>18s}" if i > 2 else f"{c:<10s}" for i, c in enumerate(cols)))
    for r in summary:
        vals = []
        for i, c in enumerate(cols):
            v = r.get(c, "")
            vals.append(f"{v:<10}" if i <= 2 else (f"{v:>18.3f}" if isinstance(v, float) else f"{v!s:>18}"))
        print("  ".join(vals))
