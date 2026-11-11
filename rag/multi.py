"""Contract v1.2: split a multi-target request into one search per target, then merge.

Round 1 showed two kinds of question a single search cannot serve, because the needed chunks are spread over
several filings and the strongest filing crowds the others out of the top k:
  * cross-company rankings (EV2-040/042/043): ten 10-Ks, most needed figures ranked below 50;
  * derived figures (EV1-037/038, EV2-045): a 10-K and a 10-Q, the 10-K half ranked 18-22.
v1.1 already flags these as `weak_reasons: ["multi_target"]`. This module answers them: one search per target,
each with its own top k, merged so that every target is represented.

Splitting (automatic when `subqueries` is not given): every key in SPLIT_KEYS whose filter lists more than one
value is split, one sub-search per combination (ticker x form x fiscal_year x fiscal_period). Other filter keys are
kept on every sub-search. Combinations that match no chunk (e.g. a 10-K with fiscal_period Q3) are dropped and
listed under `skipped`; they do not make the result weak.

Merging: round robin by rank (each target's #1, then each target's #2, ...), so the first results cover every
target. A chunk returned by two sub-searches is kept once, under the first. Every result carries
metadata.subquery (the label, e.g. "ticker=AAPL") and metadata.subquery_rank.
"""
from __future__ import annotations

import itertools
from typing import Callable

from .contract import normalize_filters, validate_query, validate_top_k, validate_trace_id

SPLIT_KEYS = ("ticker", "form", "fiscal_year", "fiscal_period")
MAX_SUBQUERIES = 20
DEFAULT_TOP_K_EACH_MANY = 5      # per-target depth when there are more than 3 targets (10 companies -> 50 chunks)


def split_filters(filters: dict | None) -> list[tuple[str, dict]]:
    """[(label, filters)] - one entry per target; a single ("all", filters) entry when nothing needs splitting."""
    nf = normalize_filters(filters)
    keys = [k for k in SPLIT_KEYS if len(nf.get(k, ())) > 1]
    if not keys:
        return [("all", dict(filters or {}))]
    base = {k: v for k, v in (filters or {}).items() if k not in keys}
    combos = list(itertools.product(*[sorted(nf[k], key=str) for k in keys]))
    if len(combos) > MAX_SUBQUERIES:
        raise ValueError(f"filters expand to {len(combos)} sub-searches (max {MAX_SUBQUERIES}); narrow them")
    out = []
    for combo in combos:
        f = dict(base)
        f.update(dict(zip(keys, combo)))
        out.append((",".join(f"{k}={v}" for k, v in zip(keys, combo)), f))
    return out


def default_top_k_each(n_targets: int, top_k: int) -> int:
    return top_k if n_targets <= 3 else min(top_k, DEFAULT_TOP_K_EACH_MANY)


def multi_search(search: Callable[..., dict], query: str, filters: dict | None = None, top_k: int = 10,
                 trace_id: str | None = None, subqueries: list[dict] | None = None,
                 top_k_each: int | None = None) -> dict:
    """`search(query, filters, top_k, trace_id=...)` is a backend's search() returning the v1.1 envelope.

    subqueries: optional explicit list of {"query": str, "filters": dict, "label": str (optional)};
                when given, no automatic splitting is done.
    Returns {results, subqueries, skipped, evidence_status, weak_reasons, warnings, trace_id}.
    """
    validate_trace_id(trace_id)
    if subqueries is None:
        validate_query(query)
        plan = [(label, query, f) for label, f in split_filters(filters)]
    else:
        if not subqueries:
            raise ValueError("subqueries must not be empty")
        plan = []
        for i, sq in enumerate(subqueries, 1):
            validate_query(sq["query"])
            normalize_filters(sq.get("filters"))
            plan.append((sq.get("label") or f"sub{i}", sq["query"], sq.get("filters") or {}))
    k_each = top_k_each or default_top_k_each(len(plan), top_k)
    validate_top_k(k_each)

    envs, subs, skipped = [], [], []
    for label, q, f in plan:
        env = search(q, f, k_each, trace_id=trace_id)
        info = {"label": label, "query": q, "filters": f, "n_results": len(env["results"]),
                "evidence_status": env.get("evidence_status"),
                "weak_reasons": [r for r in env.get("weak_reasons") or [] if r != "multi_target"],
                "request_id": env.get("request_id")}
        if len(plan) > 1 and "filter_no_match" in (env.get("weak_reasons") or []):
            skipped.append(info)
            continue
        subs.append(info)
        envs.append((label, env))

    results, seen = [], set()
    for depth in range(k_each):
        for label, env in envs:
            if depth < len(env["results"]):
                r = dict(env["results"][depth])
                if r["chunk_id"] in seen:
                    continue
                seen.add(r["chunk_id"])
                r["metadata"] = {**(r.get("metadata") or {}), "subquery": label, "subquery_rank": depth + 1}
                results.append(r)
    for rank, r in enumerate(results, 1):
        r["rank"] = rank

    reasons = [f"{s['label']}:{w}" for s in subs for w in s["weak_reasons"]]
    if not results:
        status = "empty"
        reasons = reasons or ["filter_no_match"]
    elif any(s["evidence_status"] != "ok" for s in subs):
        status = "weak"
    else:
        status = "ok"
    warnings = [f"{len(skipped)} sub-search(es) matched no filing: " + ", ".join(s["label"] for s in skipped)] \
        if skipped else []
    return {"results": results, "subqueries": subs, "skipped": skipped, "evidence_status": status,
            "weak_reasons": reasons, "warnings": warnings, "trace_id": trace_id, "top_k_each": k_each}
