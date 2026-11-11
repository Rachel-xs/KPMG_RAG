"""Turn numbers written in answers and filings into comparable values.

Handles: $1,234 | $1.2 billion | 1.2bn | 21,155M | (412) negatives | -3.5% | 3.6 percentage points | 3.6 pp
Every Quantity keeps the precision it was written with, so scoring can be precision-aware
(an answer of "$57.0 billion" is right for 57,048 million; "$57 billion" is right at 2 significant figures
only if the benchmark allows that precision).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCALE_WORDS = {
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "mn": 1e6, "mm": 1e6, "m": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "trillion": 1e12, "tn": 1e12, "t": 1e12,
}

_NUM = r"(?P<cur0>\$\s?)?(?P<neg>[-−–]|\()?\s*(?P<cur>\$|USD\s?)?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<close>\))?"
_SCALE = r"(?:\s*(?P<scale>thousand|million|billion|trillion|mn|mm|bn|tn|k|m|b|t)\b)?"
_UNIT = r"(?:\s*(?P<unit>%|percent\b|percentage points?\b|pp\b|pts?\b|points?\b|dollars\b))?"
QTY_RE = re.compile(_NUM + _SCALE + _UNIT, re.IGNORECASE)


@dataclass(frozen=True)
class Quantity:
    value: float          # in base units (dollars for money; percent units for %, pp)
    kind: str             # "money" | "percent" | "pp" | "number"
    decimals: int         # decimals as written (precision)
    scale: float          # multiplier the writer used (1e6 for "million")
    raw: str

    def sig_figs(self) -> int:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", self.raw)
        s = m.group(0).replace(",", "") if m else "0"
        digits = s.replace(".", "").lstrip("0")
        if "." not in s:                      # "110" or "150": trailing zeros are not significant
            digits = digits.rstrip("0")
        return len(digits) or 1


def extract_quantities(text: str) -> list[Quantity]:
    out: list[Quantity] = []
    # blank out tokens that look numeric but are identifiers: ISO dates, form types, accession numbers
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{10}-\d{2}-\d{6}\b|\b(?:10|8)-[KQ](?:/A)?\b|\bQ[1-4]\b|\bFY\s?\d{2,4}\b",
                  lambda m: " " * len(m.group(0)), text)
    for m in QTY_RE.finditer(text):
        num_s = m.group("num")
        # skip years and dates written as bare numbers (2025, 2026-06-30)
        if not (m.group("cur") or m.group("cur0")) and not m.group("scale") and not m.group("unit") and re.fullmatch(r"(19|20)\d\d", num_s):
            continue
        val = float(num_s.replace(",", ""))
        dec = len(num_s.split(".")[1]) if "." in num_s else 0
        scale_word = (m.group("scale") or "").lower()
        unit = (m.group("unit") or "").lower()
        # a bare single-letter scale ("m", "b", "t", "k") only counts right after a currency number
        has_cur = bool(m.group("cur") or m.group("cur0"))
        if scale_word in ("m", "b", "t", "k") and not has_cur and len(scale_word) == 1:
            pre = text[m.start("scale") - 1] if m.start("scale") > 0 else " "
            if pre == " ":
                scale_word = ""
        scale = SCALE_WORDS.get(scale_word, 1.0)
        negative = bool(m.group("neg")) and (m.group("neg") != "(" or bool(m.group("close")))
        if re.search(r"\b(net )?loss(es)? (of|was|totaled|totalling|totaling)\s*$", text[max(0, m.start() - 30):m.start()], re.I):
            negative = True                     # "a net loss of $115 million" is -115M
        if unit in ("%", "percent"):
            kind = "percent"
        elif unit.startswith(("percentage point", "pp", "pt", "point")):
            kind = "pp"
        elif m.group("cur") or m.group("cur0") or scale_word or unit == "dollars":
            kind = "money"
        else:
            kind = "number"
        v = val * (scale if kind in ("money", "number") else 1.0)
        out.append(Quantity(-v if negative else v, kind, dec, scale, m.group(0).strip()))
    return out


def matches_at_written_precision(q: Quantity, truth: float, min_sig_figs: int = 3) -> bool:
    """True if `truth`, rounded to the precision the writer used, equals what they wrote.
    Requires at least `min_sig_figs` significant figures so "$57 billion" can't pass a 57,048M fact
    unless the benchmark lowers the bar."""
    if q.kind in ("percent", "pp"):          # rates: require at least one decimal (41.2%, 7.0%) ...
        if q.decimals == 0 and min_sig_figs <= 2:   # ... unless the benchmark says the filing states a whole percent (Week 5)
            return round(truth) == round(q.value)
        return q.decimals >= 1 and round(truth, q.decimals) == round(q.value, q.decimals)
    if q.sig_figs() < min_sig_figs:
        return False
    shown = q.value / q.scale
    return round(truth / q.scale, q.decimals) == round(shown, q.decimals)
