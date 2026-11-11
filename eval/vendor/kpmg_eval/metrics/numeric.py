"""Metric A: Numerical Answer Accuracy (NAA) with an automatic error taxonomy.

Precedents: FinQA (execution accuracy), TAT-QA (scale-aware EM/F1), FinanceBench (correct / incorrect / refusal).
Every wrong answer gets exactly one label, checked in this order, so a dashboard can show *why* the
system is wrong, not just how often:

  false_refusal     answerable question, system declined
  wrong_period      value equals the same concept in another period (quarter vs year-to-date, prior year)
  wrong_concept     value equals a sibling concept for the same period (e.g. ProfitLoss vs NetIncomeLoss)
  wrong_sign        right magnitude, wrong sign
  wrong_scale       off by a factor of 1,000 or 1,000,000 (thousands / millions / billions confusion)
  too_imprecise     consistent with the truth but written with fewer significant figures than required
  wrong_value       anything else

Input is either the structured AnswerBlock the Agent team returns (preferred: see answer_schema.py) or free text.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..normalize import Quantity, extract_quantities, matches_at_written_precision
from .refusal import classify_response

LABELS = ["correct", "false_refusal", "wrong_period", "wrong_dimension", "wrong_concept", "wrong_cell", "wrong_sign",
          "wrong_scale", "too_imprecise", "wrong_value", "no_value"]   # wrong_dimension / wrong_cell: Week 5, see diagnose.py


@dataclass
class NumericResult:
    qid: str
    passed: bool
    label: str
    answered_value: float | None = None
    gold_value: float | None = None
    detail: str = ""


def _q_from_block(block: dict) -> Quantity | None:
    """Prefer the value as the agent displayed it (keeps precision); fall back to the raw float."""
    if block.get("value_text"):
        qs = [q for q in extract_quantities(block["value_text"]) if q.kind != "number" or len(extract_quantities(block["value_text"])) == 1]
        if qs:
            return qs[0]
    if block.get("value") is not None:
        v = float(block["value"])
        kind = {"%": "percent", "pp": "pp"}.get(block.get("unit", ""), "money" if block.get("unit") == "USD" else "number")
        dec = int(block.get("decimals", 6))
        return Quantity(v, kind, dec, 1.0, repr(v))
    return None


def _close(a: float, b: float, rel: float = 5e-4) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1.0)


def _same(q: Quantity, truth: float, min_sf: int) -> bool:
    if q.raw.replace(".", "", 1).lstrip("-").isdigit() or q.decimals >= 6:   # raw float from a block
        return _close(q.value, truth)
    return matches_at_written_precision(q, truth, min_sf)


def score_numeric(item: dict, answer: dict | str) -> NumericResult:
    gold = item["gold"]
    qid = item["qid"]
    truth = float(gold["value"])
    min_sf = int(gold.get("min_sig_figs", 3))

    if isinstance(answer, dict):
        if not answer.get("answered", True):
            return NumericResult(qid, False, "false_refusal", None, truth)
        q = _q_from_block(answer)
        candidates = [q] if q else []
    else:
        if classify_response(answer) == "refused":
            return NumericResult(qid, False, "false_refusal", None, truth)
        candidates = extract_quantities(answer)
        want_kind = gold.get("kind", "money")
        candidates = [c for c in candidates if c.kind == want_kind] or candidates

    if not candidates:
        return NumericResult(qid, False, "no_value", None, truth)

    if truth == 0:  # Week 5 fix: a zero answer to a zero truth was labelled wrong_sign (-0 == 0)
        if any(abs(c.value) < 0.5 * (10 ** -c.decimals) * c.scale for c in candidates):
            return NumericResult(qid, True, "correct", 0.0, truth)
        return NumericResult(qid, False, "wrong_value", candidates[0].value, truth)

    # Free text: pass if any stated number is the truth (answers often quote the comparison period too).
    # Structured blocks have exactly one candidate, so this is strict where it matters.
    distractors = gold.get("distractors", [])
    for q in candidates:
        if _same(q, truth, min_sf):
            return NumericResult(qid, True, "correct", q.value, truth)

    q = candidates[0]

    def near(target: float) -> bool:
        """Equal to `target` at the precision the answer was written with (no sig-fig floor)."""
        return _same(q, target, 1) or _close(q.value, target, 5e-3)

    # Week 5 fix: take the CLOSEST matching distractor, not the first one within tolerance. Two facts can sit
    # within 0.5% of each other (long-term debt 40,262 vs prior-period non-current 40,152).
    near_ds = [d for d in distractors if near(float(d["value"]))]
    if near_ds:
        d = min(near_ds, key=lambda d: abs(q.value - float(d["value"])))
        return NumericResult(qid, False, d["label"], q.value, truth, d.get("note", ""))
    if near(-truth):
        return NumericResult(qid, False, "wrong_sign", q.value, truth)
    for f in (1e3, 1e-3, 1e6, 1e-6):
        if near(truth * f):
            return NumericResult(qid, False, "wrong_scale", q.value, truth, f"off by x{f:g}")
    if q.sig_figs() < min_sf and _close(q.value, truth, 10 ** (-(q.sig_figs() - 1)) / 2 + 1e-9):
        return NumericResult(qid, False, "too_imprecise", q.value, truth)
    return NumericResult(qid, False, "wrong_value", q.value, truth)


def score_numeric_diagnosed(item: dict, answer: dict | str, index) -> NumericResult:
    """Week 5: score_numeric, then explain any 'wrong_value' with the filing's own facts (metrics/diagnose.py)."""
    from .diagnose import diagnose
    r = score_numeric(item, answer)
    if r.label == "wrong_value" and r.answered_value is not None and item["gold"].get("evidence"):
        d = diagnose(r.answered_value, item["gold"]["evidence"][0], index)
        if d:
            r.label = d["label"]
            r.detail = f"{d['matched_concept'].split(':')[-1]} {d['matched_period']} {list(d['matched_dims'].values())}"
    return r


def naa_summary(results: list[NumericResult]) -> dict:
    n = len(results)
    by_label = {lab: sum(r.label == lab for r in results) for lab in LABELS}
    return {"n": n, "naa": (sum(r.passed for r in results) / n) if n else None, "by_label": by_label}
