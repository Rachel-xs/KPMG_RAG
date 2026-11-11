"""Metric G: Refusal & Abstention Appropriateness (RAA). Precedents: SQuAD 2.0, FinanceBench.

Revisions agreed in review (10/7):
  * A hedged answer that still states a specific value counts as ANSWERED
    ("not disclosed, but likely ~$120B" is an unsupported answer, not a refusal).
  * Report both group rates and balanced RAA, which does not depend on the answerable/unanswerable mix.
  * Errors / empty responses score 0 and stay in the denominators.
"""
from __future__ import annotations

import re

from ..normalize import extract_quantities

REFUSAL_RE = re.compile(
    r"(not (disclosed|reported|available|provided|contain)|does not (disclose|report|contain|include|break out)|"
    r"doesn't (disclose|report|contain|break out)|cannot (be )?(determine|answer|find)|can't (determine|answer|give)|"
    r"insufficient (evidence|information)|no (information|data) (on|about|for))", re.I)


def classify_response(answer: dict | str | None) -> str:
    """-> 'answered' | 'refused' | 'error'"""
    if answer is None or answer == "" or (isinstance(answer, dict) and answer.get("error")):
        return "error"
    if isinstance(answer, dict):
        if answer.get("answered") is False and answer.get("value") is None:
            return "refused"
        return "answered"
    states_value = any(q.kind in ("money", "percent", "pp") or q.value >= 1000 for q in extract_quantities(answer))
    if REFUSAL_RE.search(answer) and not states_value:
        return "refused"
    if REFUSAL_RE.search(answer) and states_value:
        # refusal phrase plus a number: answered if the number is asserted as the answer
        unit_claim = re.search(r"\b(likely|about|around|roughly|approximately|estimate[ds]?|~)\b", answer, re.I)
        return "answered" if unit_claim else "refused"
    return "answered"


def score_raa(cases: list[tuple[bool, dict | str | None]]) -> dict:
    """cases: [(answerable, response)]"""
    n_ans = n_unans = ok_ans = ok_unans = unnecessary = unsupported = errors = 0
    for answerable, resp in cases:
        c = classify_response(resp)
        errors += c == "error"
        if answerable:
            n_ans += 1
            ok_ans += c == "answered"
            unnecessary += c == "refused"
        else:
            n_unans += 1
            ok_unans += c == "refused"
            unsupported += c == "answered"
    rate = lambda a, b: a / b if b else None  # noqa: E731
    appr, unnec = rate(ok_unans, n_unans), rate(unnecessary, n_ans)
    return {
        "n_answerable": n_ans, "n_unanswerable": n_unans, "errors": errors,
        "raa": rate(ok_ans + ok_unans, n_ans + n_unans),
        "appropriate_refusal_rate": appr,
        "unnecessary_refusal_rate": unnec,
        "balanced_raa": (appr + (1 - unnec)) / 2 if appr is not None and unnec is not None else None,
        "critical_flags": unsupported,
    }
