"""Week 5. False-premise handling (new question type in Gold Set v1).

A false-premise question ("Why did revenue decline?" when it rose) is answerable, but only by correcting the
premise. Three outcomes:

  corrected   rejects the premise AND states the correct direction/fact (e.g. 'revenue increased', '82,886')
  rejected    rejects the premise without the correction
  accepted    answers as if the premise were true (the dangerous failure: a fluent, wrong explanation)

Rule-based on purpose (no LLM judge): rejection cues + required correction points from the benchmark.
Validated in tests on hand-written responses.
"""
from __future__ import annotations

import re

REJECT = re.compile(
    r"(did not (decline|fall|decrease|report a (net )?loss)|didn't (decline|fall|decrease)|did not have|"
    r"is not a (reportable )?segment|isn't a (reportable )?segment|not one of (its|the) (three )?(reportable )?segments|"
    r"premise|actually|in fact|contrary|rather than (a )?(decline|loss)|no net loss|was not a (net )?loss|"
    r"(rose|increased|grew) (by|to|\d)|reported net income|there is no)", re.I)


def classify_premise(response: str, correction_points: list[str]) -> str:
    if not response:
        return "accepted"
    rej = bool(REJECT.search(response))
    low = response.lower().replace("( ", "(")
    pts = [p for p in correction_points if p.lower() not in ("rejects the premise",)]
    has_fix = any(p.lower() in low for p in pts)
    if rej and has_fix:
        return "corrected"
    if rej:
        return "rejected"
    return "accepted"


def premise_summary(labels: list[str]) -> dict:
    n = len(labels)
    return {"n": n, **{k: sum(l == k for l in labels) for k in ("corrected", "rejected", "accepted")},
            "detection_rate": (sum(l != "accepted" for l in labels) / n) if n else None}
