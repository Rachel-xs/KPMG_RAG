"""Extended retrieval evaluation for RAG Team.

Adds three capabilities on top of the existing evaluation workflow:

1. Section Recall@K
2. Paraphrased-query evaluation
3. Failure logging for error analysis

This file does NOT modify rag/evaluate.py.

Gold questions may optionally contain:

    "paraphrases": [
        "alternative wording 1",
        "alternative wording 2"
    ]

If no paraphrases are provided, only the original question is evaluated.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from rag.evaluate import load_gold, evidence_hits, is_relevant, _meta_match
from rag.retrieve import make_retriever


# ---------------------------------------------------------------------------
# Query variants
# ---------------------------------------------------------------------------

def query_variants(q: dict) -> list[tuple[str, str]]:
    """Return the original question plus optional manually reviewed paraphrases."""

    variants = [("original", q["question"])]

    for i, text in enumerate(q.get("paraphrases", []), start=1):
        if isinstance(text, str) and text.strip():
            variants.append(
                (f"paraphrase_{i}", text.strip())
            )

    return variants


# ---------------------------------------------------------------------------
# Section-level evaluation
# ---------------------------------------------------------------------------

def _normalize_section(section: str | None) -> str:
    """Normalize section labels for section-level comparison."""

    if not section:
        return ""

    return " ".join(
        str(section).upper().split()
    )


def _section_matches(
    retrieved_section: str | None,
    gold_section: str | None,
) -> bool:
    """Return True when two section labels represent the same section region."""

    retrieved = _normalize_section(retrieved_section)
    gold = _normalize_section(gold_section)

    if not retrieved or not gold:
        return False

    return (
        retrieved == gold
        or retrieved.startswith(gold + " ")
        or gold.startswith(retrieved + " ")
    )


def section_recall_at_k(
    q: dict,
    results: list[dict],
    k: int,
) -> float | None:
    """Share of gold evidence sections found in the top-k results.

    Returns None if the question does not contain section labels.
    """

    gold_sections = []

    for evidence in q.get("gold", {}).get("evidence", []):
        section = evidence.get("section")

        if section:
            normalized = _normalize_section(section)

            if normalized not in gold_sections:
                gold_sections.append(normalized)

    if not gold_sections:
        return None

    top_k_sections = [
        r.get("section")
        for r in results[:k]
        if r.get("section")
    ]

    hits = 0

    for gold_section in gold_sections:
        if any(
            _section_matches(retrieved, gold_section)
            for retrieved in top_k_sections
        ):
            hits += 1

    return hits / len(gold_sections)


# ---------------------------------------------------------------------------
# Extended scoring
# ---------------------------------------------------------------------------

def score_question_extended(
    q: dict,
    results: list[dict],
    ks: tuple[int, ...],
) -> dict:
    """Score one question using retrieval and section-level metrics."""

    gold = q["gold"]

    relevance = [
        is_relevant(gold, r)
        for r in results
    ]

    out = {}

    # MRR
    first_relevant_rank = next(
        (
            i
            for i, relevant in enumerate(relevance, start=1)
            if relevant
        ),
        None,
    )

    out["mrr"] = (
        1.0 / first_relevant_rank
        if first_relevant_rank
        else 0.0
    )

    evidence_items = list(
        gold.get("evidence", [])
    )

    evidence_items += [
        {"chunk_id": chunk_id}
        for chunk_id in gold.get("chunk_ids", [])
    ]

    for k in ks:
        top = results[:k]

        # ---------------------------------------------------------------
        # Evidence Recall@K
        # ---------------------------------------------------------------

        satisfied = 0

        for item in evidence_items:

            if "chunk_id" in item:

                if any(
                    r["chunk_id"] == item["chunk_id"]
                    for r in top
                ):
                    satisfied += 1

            else:

                if any(
                    evidence_hits(item, r)
                    for r in top
                ):
                    satisfied += 1

        out[f"evidence_recall@{k}"] = (
            satisfied / len(evidence_items)
            if evidence_items
            else 0.0
        )

        # ---------------------------------------------------------------
        # Hit@K
        # ---------------------------------------------------------------

        out[f"hit@{k}"] = float(
            any(relevance[:k])
        )

        # ---------------------------------------------------------------
        # Provenance@K / metadata accuracy
        # ---------------------------------------------------------------

        expected = q.get("expected")

        if expected and top:

            out[f"provenance@{k}"] = (
                sum(
                    _meta_match(expected, r)
                    for r in top
                )
                / len(top)
            )

        # ---------------------------------------------------------------
        # Section Recall@K
        # ---------------------------------------------------------------

        section_score = section_recall_at_k(
            q,
            results,
            k,
        )

        if section_score is not None:
            out[f"section_recall@{k}"] = section_score

    return out


# ---------------------------------------------------------------------------
# Failure analysis
# ---------------------------------------------------------------------------

def classify_failure(
    scores: dict,
    results: list[dict],
    k: int = 5,
) -> str:
    """Assign a simple diagnostic label to a retrieval failure."""

    evidence_recall = scores.get(
        f"evidence_recall@{k}",
        0.0,
    )

    section_recall = scores.get(
        f"section_recall@{k}"
    )

    if evidence_recall >= 1.0:
        return "none"

    if section_recall == 1.0:
        return "correct_section_wrong_chunk_or_ranking"

    if section_recall == 0.0:
        return "wrong_section"

    if not results:
        return "no_results"

    return "evidence_not_found"


def build_failure_record(
    q: dict,
    query_type: str,
    query_text: str,
    method: str,
    filter_mode: str,
    scores: dict,
    results: list[dict],
) -> dict:
    """Create an inspectable error-analysis record."""

    top5 = results[:5]

    return {
        "qid": q["qid"],
        "tier": q.get("tier", "?"),
        "query_type": query_type,
        "query": query_text,
        "method": method,
        "filters": filter_mode,
        "failure_type": classify_failure(
            scores,
            results,
            k=5,
        ),
        "evidence_recall@5": scores.get(
            "evidence_recall@5"
        ),
        "section_recall@5": scores.get(
            "section_recall@5"
        ),
        "hit@5": scores.get(
            "hit@5"
        ),
        "gold": q.get("gold", {}),
        "retrieved_top5": [
            {
                "rank": r.get("rank"),
                "chunk_id": r.get("chunk_id"),
                "score": r.get("score"),
                "section": r.get("section"),
                "ticker": r.get("ticker"),
                "form": r.get("form"),
            }
            for r in top5
        ],
    }


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------

def run_extended_eval(
    index_dir: Path,
    gold_path: Path,
    out_dir: Path,
    methods=("bm25", "dense", "hybrid"),
    ks=(5, 10),
    filter_modes=("filtered", "unfiltered"),
    backend: str = "custom",
    collection_name: str = "sec_filing_chunks",
    include_drafts: bool = False,
) -> list[dict]:
    """Run extended retrieval evaluation."""

    retriever = make_retriever(
        backend=backend,
        index_dir=index_dir,
        log_dir=None,
        collection_name=collection_name,
    )

    gold = load_gold(
        gold_path,
        include_drafts=include_drafts,
    )

    if not gold:
        raise SystemExit(
            "No usable gold questions found. "
            "Use labeled/reviewed questions or pass --include-drafts."
        )

    kmax = max(ks)

    per_question = []
    failures = []

    aggregate = defaultdict(
        lambda: defaultdict(list)
    )

    for filter_mode in filter_modes:

        for method in methods:

            for q in gold:

                filters = (
                    q.get("filters")
                    if filter_mode == "filtered"
                    else None
                )

                for query_type, query_text in query_variants(q):

                    response = retriever.search(
                        query=query_text,
                        filters=filters,
                        top_k=kmax,
                        method=method,
                    )

                    results = response["results"]

                    scores = score_question_extended(
                        q,
                        results,
                        ks,
                    )

                    row = {
                        "qid": q["qid"],
                        "tier": q.get("tier", "?"),
                        "query_type": query_type,
                        "query": query_text,
                        "method": method,
                        "filters": filter_mode,
                        "latency_ms": response["latency_ms"],
                        **scores,
                    }

                    per_question.append(row)

                    # ---------------------------------------------------
                    # Failure logging
                    # ---------------------------------------------------

                    if scores.get(
                        "evidence_recall@5",
                        0.0,
                    ) < 1.0:

                        failures.append(
                            build_failure_record(
                                q=q,
                                query_type=query_type,
                                query_text=query_text,
                                method=method,
                                filter_mode=filter_mode,
                                scores=scores,
                                results=results,
                            )
                        )

                    # ---------------------------------------------------
                    # Aggregate metrics
                    # ---------------------------------------------------

                    for tier in (
                        row["tier"],
                        "ALL",
                    ):

                        key = (
                            filter_mode,
                            method,
                            query_type,
                            tier,
                        )

                        for metric, value in scores.items():

                            if value is not None:
                                aggregate[key][metric].append(
                                    value
                                )

                        aggregate[key][
                            "latency_ms"
                        ].append(
                            response["latency_ms"]
                        )

    # -------------------------------------------------------------------
    # Build summary
    # -------------------------------------------------------------------

    summary = []

    for (
        filter_mode,
        method,
        query_type,
        tier,
    ), metrics in sorted(
        aggregate.items()
    ):

        row = {
            "filters": filter_mode,
            "method": method,
            "query_type": query_type,
            "tier": tier,
        }

        n_values = metrics.get(
            "mrr",
            [],
        )

        row["n"] = len(n_values)

        for metric, values in metrics.items():

            if values:
                row[metric] = round(
                    sum(values) / len(values),
                    4,
                )

        summary.append(row)

    # -------------------------------------------------------------------
    # Save outputs
    # -------------------------------------------------------------------

    out_dir = Path(out_dir)
    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    run_summary = {
        "timestamp": stamp,
        "backend": backend,
        "index": retriever.meta,
        "gold_file": str(gold_path),
        "n_questions": len(gold),
        "include_drafts": include_drafts,
        "summary": summary,
    }

    summary_path = (
        out_dir
        / f"extended_run_{stamp}.json"
    )

    summary_path.write_text(
        json.dumps(
            run_summary,
            indent=2,
        )
    )

    # Per-question CSV
    per_question_path = (
        out_dir
        / f"extended_per_question_{stamp}.csv"
    )

    if per_question:

        columns = sorted(
            {
                key
                for row in per_question
                for key in row
            },
            key=lambda c: (
                c not in (
                    "qid",
                    "tier",
                    "query_type",
                    "query",
                    "method",
                    "filters",
                ),
                c,
            ),
        )

        with open(
            per_question_path,
            "w",
            newline="",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=columns,
            )

            writer.writeheader()
            writer.writerows(
                per_question
            )

    # Failure log
    failure_path = (
        out_dir
        / f"failures_{stamp}.json"
    )

    failure_path.write_text(
        json.dumps(
            failures,
            indent=2,
        )
    )

    print(
        f"[extended-eval] questions: {len(gold)}"
    )

    print(
        f"[extended-eval] failures: {len(failures)}"
    )

    print(
        f"[extended-eval] summary: {summary_path}"
    )

    print(
        f"[extended-eval] per-question: {per_question_path}"
    )

    print(
        f"[extended-eval] failures: {failure_path}"
    )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extended retrieval evaluation with "
            "section recall, paraphrase testing, "
            "and failure analysis."
        )
    )

    parser.add_argument(
        "--index-dir",
        required=True,
        type=Path,
        help="Path to the retrieval index.",
    )

    parser.add_argument(
        "--gold",
        required=True,
        type=Path,
        help="Path to Gold Set JSONL.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("eval/results"),
    )

    parser.add_argument(
        "--backend",
        choices=[
            "custom",
            "chroma",
        ],
        default="custom",
    )

    parser.add_argument(
        "--include-drafts",
        action="store_true",
    )

    args = parser.parse_args()

    run_extended_eval(
        index_dir=args.index_dir,
        gold_path=args.gold,
        out_dir=args.out_dir,
        backend=args.backend,
        include_drafts=args.include_drafts,
    )


if __name__ == "__main__":
    main()
