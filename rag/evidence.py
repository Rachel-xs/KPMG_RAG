"""Contract v1.1: a structural "is this evidence weak?" check attached to every search response.

Round 1 (Gold Set v2) showed that RRF scores do not separate hits, misses and unanswerable questions
(median top-1 ~0.032 and top-1/top-2 margin ~0.0007 in all three groups), so this check uses no score
threshold. Validated on Round 1 (scripts/run_round1_diag.py): it flags 2/105 hits, 7/19 misses,
3/10 unanswerable and 5/11 Exhibit 21 questions. It is an input to the Agent's evidence-sufficiency
check, not a replacement for it.

    evidence_status  "ok" | "weak" | "empty"
    weak_reasons     subset of: filter_no_match, no_results, multi_target, entity_missing, methods_disagree
"""
from __future__ import annotations

from .contract import FILTER_NORMALIZERS

OVERLAP_WINDOW = 10      # compare BM25 and dense top 10
MAX_WEAK_OVERLAP = 0     # methods_disagree when they share <= this many chunks (0: 1% of hits flagged)
MULTI_KEYS = ("ticker", "form", "fiscal_year", "fiscal_period")
ENTITY_KEYS = ("ticker", "fiscal_year", "fiscal_period")


def methods_overlap(bm25_order: list, dense_order: list, window: int = OVERLAP_WINDOW) -> int:
    return len(set(bm25_order[:window]) & set(dense_order[:window]))


def _result_value(r: dict, key: str):
    v = r.get(key)
    if v is None:
        v = (r.get("metadata") or {}).get(key)
    if v is None:
        return None
    try:
        return FILTER_NORMALIZERS[key](v)
    except ValueError:
        return None


def assess(nf: dict[str, set], results: list[dict], n_candidates: int, overlap: int | None) -> dict:
    """nf = normalize_filters(filters); overlap = BM25/dense top-10 overlap (hybrid only, else None)."""
    checks = {"bm25_dense_overlap@10": overlap}
    if n_candidates == 0:
        return {"evidence_status": "empty", "weak_reasons": ["filter_no_match"], "evidence_checks": checks}
    if not results:
        return {"evidence_status": "empty", "weak_reasons": ["no_results"], "evidence_checks": checks}
    reasons = []
    if any(len(nf.get(k, ())) > 1 for k in MULTI_KEYS):
        reasons.append("multi_target")
    for k in ENTITY_KEYS:
        if k in nf and not nf[k] <= {_result_value(r, k) for r in results}:
            reasons.append("entity_missing")
            break
    if overlap is not None and overlap <= MAX_WEAK_OVERLAP:
        reasons.append("methods_disagree")
    return {"evidence_status": "weak" if reasons else "ok", "weak_reasons": reasons, "evidence_checks": checks}
