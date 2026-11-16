"""Cell-level citations for table chunks (#2, contract v1.3 draft). No model calls.

Mentor (10/29): "return the structured value and also the text that describes the table". KPMG wants a number in an
answer to point at the exact table cell it came from. Data's table <-> chunk links are not in the database yet, so
this module derives cells from RAG's own table chunks, which are clean markdown (rag/tables.py):

    caption lines / unit line "(In millions, except per share amounts)"
    | label | Three Months Ended March 31, 2026 | ... |      <- header (may be empty: then period rows below it)
    | --- | --- |
    | Revenue: |  |  |                                       <- group label (no values): becomes the row path
    | Product | $15,089 | ... |

    from rag.cells import parse_table, find_cells, cite_answer
    t = parse_table(chunk)                      # TableCells with rows x columns, each column with a period
    find_cells(chunks, 82_886_000_000, period_end="2026-03-31", months=3)   # ranked matching cells
    cite_answer(answer_block, chunks)           # adds "cell_citations" to an AnswerBlock

A cell citation:
    {"cell_key": "<table_id>|revenue > total revenue|3m@2026-03-31", "table_id", "chunk_id", "table_name",
     "row_label": "Total revenue", "row_path": ["Revenue", "Total revenue"], "column_header": "Three Months Ended
     March 31, 2026", "period_end": "2026-03-31", "period_months": 3 (0 = point in time), "value_text": "82,886",
     "value": 82886000000.0, "unit_scale": 1e6, "accession", "ticker", "form", "source_url", "period_match": bool}

cell_key = table_id | normalised row path | column period (or normalised header when no period parses). It is stable
across re-chunking because table_id comes from Data. When Data publishes its own (table_id, row key, column key),
only make_cell_key() changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?"
_DATE = re.compile(_MON + r"\s+(\d{1,2}),?\s*((?:19|20)\d\d)?", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d\d)\b")
_DUR = [(re.compile(r"\b(three|3)[- ]months?\b|\bquarter\b|\b13 weeks\b", re.I), 3),
        (re.compile(r"\b(six|6)[- ]months?\b|\b26 weeks\b", re.I), 6),
        (re.compile(r"\b(nine|9)[- ]months?\b|\b39 weeks\b", re.I), 9),
        (re.compile(r"\b(twelve|12)[- ]months?\b|\byears?\s+ended\b|\bfiscal\s+(?:year|(?:19|20)\d\d)\b|\b52 weeks\b|\b53 weeks\b|\bfor the years?\b", re.I), 12)]
_UNIT = re.compile(r"\((?:dollars\s+|\$\s*|amounts\s+)?in\s+(millions|thousands|billions)([^)]*)\)", re.I)
_SCALE = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}
_NUM = re.compile(r"^\$?\s*\(?\s*\$?\s*(-?\d[\d,]*(?:\.\d+)?)\s*\)?\s*(%)?$")
_DASH = re.compile(r"^[—–-]+$")


def _slug(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%&/ -]+", " ", s.lower())).strip()


def parse_number(text: str) -> tuple[float | None, bool]:
    """'$15,089' -> 15089.0; '(623)' -> -623.0; '—' -> 0.0; '12.5%' -> (12.5, True). Returns (value, is_percent)."""
    t = text.strip().replace(" ", "").replace(" ", " ")
    if not t:
        return None, False
    if _DASH.match(t):
        return 0.0, False
    m = _NUM.match(t)
    if not m:
        return None, False
    v = float(m.group(1).replace(",", ""))
    if "(" in t and ")" in t or t.startswith("-"):
        v = -abs(v)
    return v, bool(m.group(2))


@dataclass
class Column:
    header: str
    period_end: date | None = None
    months: int | None = None  # 0 = balance at a date; 3/6/9/12 = duration

    @property
    def key(self) -> str:
        if self.period_end:
            return f"{self.months if self.months is not None else '?'}m@{self.period_end.isoformat()}"
        return _slug(self.header) or "col"


@dataclass
class TableCells:
    chunk: dict
    caption: str
    unit_text: str
    scale: float
    per_share_exempt: bool
    columns: list[Column] = field(default_factory=list)
    rows: list[tuple[list[str], list[str]]] = field(default_factory=list)  # (row path, raw cell texts)
    unit_known: bool = True

    def cells(self):
        c = self.chunk
        for path, vals in self.rows:
            label = path[-1]
            per_share = self.per_share_exempt and re.search(
                r"per\s+(?:common\s+)?share|\beps\b|^(?:basic|diluted)\b|dividends?\s+(?:declared\s+)?per", " | ".join(path) + " | " + label,
                re.I | re.M) or (self.per_share_exempt and re.fullmatch(r"(?:basic|diluted)(?: earnings| net income)?", label.strip(), re.I))
            for j, raw in enumerate(vals):
                if j >= len(self.columns):
                    break
                v, pct = parse_number(raw)
                if v is None:
                    continue
                scale = 1.0 if (pct or per_share) else self.scale
                col = self.columns[j]
                yield {"cell_key": make_cell_key(c.get("table_id") or c.get("chunk_id"), path, col),
                       "table_id": c.get("table_id"), "chunk_id": c.get("chunk_id"), "table_name": c.get("table_name"),
                       "row_label": label, "row_path": path, "row_index": self.rows.index((path, vals)),
                       "column_header": col.header, "column_index": j,
                       "period_end": col.period_end.isoformat() if col.period_end else None,
                       "period_months": col.months, "value_text": raw.strip(), "value": v * scale,
                       "unit_scale": scale, "unit_known": self.unit_known, "is_percent": pct, "accession": c.get("accession_number") or c.get("accession"),
                       "ticker": c.get("ticker"), "form": c.get("form"), "source_url": c.get("source_url")}


def make_cell_key(table_id: str, path: list[str], col: Column) -> str:
    return f"{table_id}|{' > '.join(_slug(p) for p in path)}|{col.key}"


def _split_row(line: str) -> list[str]:
    return [x.strip() for x in line.strip().strip("|").split("|")]


def _period(text: str, context: str, fy_end: date | None) -> tuple[date | None, int | None]:
    """Period of one column from its header text, falling back to the table caption for the duration / month-day."""
    months = None
    for rx, m in _DUR:
        if rx.search(text):
            months = m
            break
    if months is None:
        for rx, m in _DUR:
            if rx.search(context):
                months = m
                break
    d = _DATE.search(text)
    years = _YEAR.findall(text)
    end = None
    if d:
        y = d.group(3) or (years[-1] if years else None)
        if y:
            end = date(int(y), _MONTHS[d.group(1).lower()[:3] if d.group(1).lower() != "sept" else "sep"], int(d.group(2)))
    elif years:
        y = int(years[-1])
        dc = _DATE.search(context)  # "Year Ended June 30," in the caption, years in the header
        if dc:
            end = date(y, _MONTHS[dc.group(1).lower()[:3] if dc.group(1).lower() != "sept" else "sep"], int(dc.group(2)))
        elif fy_end and (months in (None, 12)):
            end = date(y, fy_end.month, min(fy_end.day, 28 if fy_end.month == 2 else fy_end.day))
            months = 12 if months is None else months
    if end and months is None:
        # a bare date with no duration word anywhere: a balance-sheet style "as of" column
        months = 0
    return end, months


def parse_table(chunk: dict, fy_end: date | None = None) -> TableCells | None:
    """Parse one table chunk. fy_end (any year) lets "2026 | 2025" headers resolve to the fiscal year end."""
    if not chunk.get("is_table"):
        return None
    lines = chunk["text"].split("\n")
    sep = next((i for i, x in enumerate(lines) if re.match(r"^\|\s*-{3}", x.strip())), None)
    if sep is None or sep == 0:
        return None
    pre = " ".join(lines[:sep - 1])
    um = _UNIT.search(pre) or _UNIT.search(chunk.get("table_name") or "")
    scale = _SCALE[um.group(1).lower()] if um else 1.0  # unknown: find_cells tries 1, 1e3 and 1e6
    exempt = bool(um and re.search(r"per\s+share|share\s+data|share\s+amounts", um.group(2), re.I)) or not um
    header = _split_row(lines[sep - 1])
    body = [_split_row(x) for x in lines[sep + 1:] if x.strip().startswith("|")]
    ncol = max((len(r) for r in body), default=len(header)) - 1
    head_cells = (header[1:] + [""] * ncol)[:ncol]
    context = " ".join([pre, chunk.get("table_name") or "", header[0] if header else ""])
    # Data's caption form "Columns: For the year ended | 2026 | 2025 | 2024" (header row itself empty); when each
    # period has a value and a % column, repeat each period over its group of columns
    colline = next((x for x in lines[:sep] if x.strip().lower().startswith("columns:")), None)
    if colline and not any(head_cells):
        parts = [x.strip() for x in colline.split(":", 1)[1].split("|")]
        lead, periods = parts[0], [x for x in parts[1:] if x]
        context += " " + lead
        garbled = bool(_YEAR.fullmatch(lead) or _DATE.fullmatch(lead))  # a period swallowed into the lead: header cut
        if periods and ncol % len(periods) == 0 and not garbled:
            rep_ = ncol // len(periods)
            head_cells = [periods[j // rep_] for j in range(ncol)]
    # leading period rows when the header is empty or year-only: "| Three Months Ended March 31, | 2026 | 2025 |"
    i = 0
    while i < len(body) and i < 3:
        vals = body[i][1:]
        nonempty = [v for v in vals if v]
        if nonempty and all(_YEAR.fullmatch(v) or _DATE.search(v) or any(rx.search(v) for rx, _ in _DUR) for v in nonempty):
            context += " " + body[i][0]
            head_cells = [(h + " " + (vals[j] if j < len(vals) else "")).strip() for j, h in enumerate(head_cells)]
            i += 1
        elif not nonempty and any(rx.search(body[i][0]) for rx, _ in _DUR) or (not nonempty and _DATE.search(body[i][0] or "")):
            context += " " + body[i][0]
            i += 1
        else:
            break
    cols = [Column(h, *_period(h, context, fy_end)) for h in head_cells]
    # a flow statement (income / cash flow) whose header names only dates: the duration is the filing's own period
    labels = " ".join(r[0] for r in body).lower()
    if re.search(r"net sales|revenue|net income|operating income|cash provided|cash used", labels):
        for col in cols:
            if col.months == 0:
                col.months = 12 if chunk.get("form") == "10-K" else None
    rows, group = [], []
    for r in body[i:]:
        label, vals = r[0], r[1:]
        if not label and not any(vals):
            continue
        if label and not any(v for v in vals):
            group = [label.rstrip(":")]  # "Revenue:" heads the rows below it
            continue
        path = (group + [label]) if group and label else [label or "(unlabelled)"]
        rows.append((path, (vals + [""] * ncol)[:ncol]))
        if label.lower().startswith("total"):
            group = []  # "Total cost of revenue" closes its group; "Gross margin" stands alone
    return TableCells(chunk, " ".join(lines[:sep - 1])[:300], um.group(0) if um else "", scale, exempt, cols, rows,
                      unit_known=bool(um))


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= max(abs(b) * rel, 0.5)


def find_cells(chunks: list[dict], value: float, period_end: str | None = None, months: int | None = None,
               fy_ends: dict | None = None, rel_tol: float = 0.0005, tolerance_days: int = 7) -> list[dict]:
    """Cells in these chunks whose value matches `value` (in base units, e.g. USD), best first: period match, then
    chunk order. A value written in millions matches to the displayed precision (rel_tol 0.05%)."""
    want_end = date.fromisoformat(period_end) if period_end else None
    out = []
    for order, c in enumerate(chunks):
        t = parse_table(c, (fy_ends or {}).get(c.get("ticker")))
        if not t:
            continue
        for cell in t.cells():
            if cell["value"] == 0 and value != 0:
                continue
            hit = _close(cell["value"], value, rel_tol) or _close(abs(cell["value"]), abs(value), rel_tol)
            if not hit and cell["is_percent"]:  # 20% vs a fraction 0.2
                hit = _close(cell["value"] / 100, value, rel_tol)
            if not hit and not cell["unit_known"] and not cell["is_percent"] and cell["value"] != 0:
                # no unit line in this chunk: try thousands / millions, keeping every displayed digit
                for sc in (1e3, 1e6):
                    v = cell["value"] * sc
                    if abs(value) >= sc * 100 and (abs(v - value) <= sc * 0.5 or abs(abs(v) - abs(value)) <= sc * 0.5):
                        cell = {**cell, "value": v, "unit_scale": sc, "unit_inferred": True}
                        hit = True
                        break
            if not hit:
                continue
            pm = None
            if want_end and cell["period_end"]:
                pm = abs((date.fromisoformat(cell["period_end"]) - want_end).days) <= tolerance_days and \
                     (months is None or cell["period_months"] in (None, months))
            cell["period_match"] = pm
            cell["_order"] = order
            out.append(cell)
    out.sort(key=lambda x: (x["period_match"] is not True, x["period_match"] is None, x["_order"]))
    for x in out:
        x.pop("_order", None)
    return out


def cite_answer(block: dict, chunks: list[dict], period_months: int | None = None, fy_ends: dict | None = None,
                values: list[float] | None = None) -> dict:
    """Add `cell_citations` to an AnswerBlock: for the answer's value (or each of `values`, e.g. a derived answer's
    inputs), the best matching cell in the cited / retrieved chunks. Unmatched values get None."""
    vals = values if values is not None else ([block["value"]] if block.get("value") is not None else [])
    cites = []
    for v in vals:
        hits = find_cells(chunks, float(v), block.get("period_end"), period_months, fy_ends)
        cites.append(hits[0] if hits else None)
    return {**block, "cell_citations": cites}
