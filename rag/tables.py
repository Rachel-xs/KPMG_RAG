"""Table-aware parsing of SEC filing section text (Week 6 chunking plan, variant B).

Data's `paragraph-v1` text keeps one table row per line with "|" cell separators, but
  * ~60% of cells are empty layout cells,
  * "$" and ")" sit in their own cells:      "Product | | $ | 15,089 | |"   "(623 | )"
  * header cells wrap across lines:          "(In millions) | | Three Months Ended\n\nMarch 31, | | ..."
  * ~1,500-char windows cut tables mid-row, so many row chunks lose their column header and unit line.

This module rebuilds whole tables from a *stitched* section text and renders them as clean markdown
(or as one line per row, "linear"), keeping caption, unit line, composed column headers and footnotes,
and splits only over-long tables by rows (repeating the header in every piece).

    blocks = parse_section(text)                   # [{"type": "text"|"table", ...}] in reading order
    pieces = split_table(tbl, count_tokens, 460)   # list[str], header repeated in every piece
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

UNIT_RE = re.compile(r"\(\s*(?:dollars\s+|\$\s*)?in\s+(?:millions|thousands|billions)[^)]*\)(?:\s*\(\s*unaudited\s*\))?", re.I)
NUM_RE = re.compile(
    r"^(?:[$€£]?\(?-?[$€£]?\d[\d,]*(?:\.\d+)?\)?%?|\(?\d+(?:\.\d+)?\)?\s?%|[—–-]+|\*+|n/?m|\$?—)$", re.I
)
YEAR_RE = re.compile(r"^(?:19|20)\d\d$")
PAGE_NOISE_RE = re.compile(r"^(?:\d{1,3}|PART\s+I{1,3}V?|Item\s+\d{1,2}[A-C]?\.?|Table of Contents)$", re.I)
FOOTNOTE_MARK_RE = re.compile(r"^\((?:[a-z]|\d{1,2})\)(?:\s|$)")
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
PERIOD_LABEL_RE = re.compile(
    rf"^(?:{_MONTH}\s+\d{{1,2}},?(?:\s*(?:19|20)\d\d)?|(?:19|20)\d\d|.*\b(?:months|weeks|years?|quarters?)\s+ended\b.*|as of .*)$", re.I)
# running page footer rendered as a table row, e.g. "Apple Inc. | Q3 2026 Form 10-Q | 20 |"
FORM_FOOTER_RE = re.compile(r"^[^|]{2,80}\|\s*(?:Q\d\s+)?(?:19|20)\d\d\s+Form\s+10-[KQ]\s*\|\s*\d{1,3}\s*\|?$", re.I)
_CONT_MAX = 80  # a pipe-less line this short, right after an unterminated row, is a wrapped header cell


@dataclass
class Table:
    caption: list[str] = field(default_factory=list)
    unit: str = ""
    header_rows: list[list[str]] = field(default_factory=list)
    columns: list[str] | None = None  # composed column names, when the header could be aligned
    rows: list[tuple[str, list[str]]] = field(default_factory=list)  # (label, values)
    footnotes: list[str] = field(default_factory=list)
    start: int = 0  # char span inside the section text
    end: int = 0

    @property
    def ncols(self) -> int:
        lens = [len(v) for _, v in self.rows if v]
        return Counter(lens).most_common(1)[0][0] if lens else 0

    @property
    def has_numbers(self) -> bool:
        return any(NUM_RE.match(x) and not YEAR_RE.match(x) for _, v in self.rows for x in v)


# ---------------------------------------------------------------------------------------------
# 1. lines -> logical items ("row" with its wrapped continuation lines, or "text")
# ---------------------------------------------------------------------------------------------
def logical_items(text: str) -> list[dict]:
    items, buf = [], None
    for m in re.finditer(r"[^\n]+", text):
        line, s, e = m.group(0).strip(), m.start(), m.end()
        if not line or FORM_FOOTER_RE.match(line):
            continue
        if buf is not None:
            if "|" in line or len(line) <= _CONT_MAX:
                buf["text"] += " " + line
                buf["end"] = e
                if line.endswith("|"):
                    items.append(buf)
                    buf = None
                continue
            items.append(buf)
            buf = None
        if line.count("|") >= 2:
            item = {"type": "row", "text": line, "start": s, "end": e}
            if line.endswith("|"):
                items.append(item)
            else:
                buf = item
        else:
            items.append({"type": "text", "text": line, "start": s, "end": e})
    if buf is not None:
        items.append(buf)
    return items


# ---------------------------------------------------------------------------------------------
# 2. cells
# ---------------------------------------------------------------------------------------------
def merge_cells(raw: str) -> list[str]:
    """Drop empty layout cells; glue "$" to the next value and ")" / "%" / ")%" to the previous one."""
    out, pending = [], ""
    for c in raw.split("|"):
        c = re.sub(r"\s+", " ", c).strip()
        if not c:
            continue
        if c in ("$", "€", "£"):
            pending = c
            continue
        if out and re.fullmatch(r"\)?\s?%?", c):
            out[-1] += c.replace(" ", "")
            continue
        if pending:
            c, pending = pending + c, ""
        out.append(c)
    return out


def _is_value(x: str) -> bool:
    return bool(NUM_RE.match(x))


def split_row(raw: str) -> tuple[str, list[str], str]:
    """-> (label, values, unit). The first cell is the label unless it is itself a value."""
    cells = merge_cells(raw)
    if not cells:
        return "", [], ""
    label, values = ("", cells) if _is_value(cells[0]) else (cells[0], cells[1:])
    # a year used as a row label ("2027 | 5,910 | 6,786"), as opposed to a header row of years
    if not label and len(cells) > 1 and YEAR_RE.match(cells[0]) and any(_is_value(v) and not YEAR_RE.match(v) for v in cells[1:]):
        label, values = cells[0], cells[1:]
    unit = ""
    m = UNIT_RE.search(label)
    if m:
        unit = m.group(0)
        label = (label[: m.start()] + label[m.end() :]).strip(" ,;")
    # a header row whose first cell is itself a period ("March 31, 2026 | June 30, 2025")
    if label and values and PERIOD_LABEL_RE.match(label) and all(not _is_value(v) or YEAR_RE.match(v) for v in values):
        label, values = "", [label] + values
    return label, values, unit


# ---------------------------------------------------------------------------------------------
# 3. column header composition
# ---------------------------------------------------------------------------------------------
def _pct_cols(rows: list[tuple[str, list[str]]], ncols: int) -> set[int]:
    full = [v for _, v in rows if len(v) == ncols]
    if not full:
        return set()
    return {j for j in range(ncols) if sum(v[j].endswith("%") for v in full) > len(full) / 2}


def compose_columns(header_rows: list[list[str]], rows: list[tuple[str, list[str]]], ncols: int) -> list[str] | None:
    """Align stacked header rows ("Three Months Ended March 31," over "2026 | 2025") to the value columns.
    Handles spans (2 periods over 4 year columns) and "Percentage Change" columns. None if not alignable."""
    if not header_rows or ncols == 0:
        return None
    pct = _pct_cols(rows, ncols)
    # segments: runs of non-% columns, and each % column on its own
    segs, cur = [], []
    for j in range(ncols):
        if j in pct:
            if cur:
                segs.append(cur)
                cur = []
            segs.append([j])
        else:
            cur.append(j)
    if cur:
        segs.append(cur)
    nonpct = [j for j in range(ncols) if j not in pct]

    cols = [""] * ncols
    for hr in header_rows:
        k = len(hr)
        parts = [""] * ncols
        if k == ncols:
            parts = list(hr)
        elif k == ncols + 1 and not YEAR_RE.match(hr[0]):  # "Year Ended June 30, | 2026 | 2025"
            parts = [f"{hr[0]} {v}" for v in hr[1:]]
        elif pct and k == len(nonpct) and all(YEAR_RE.match(v) for v in hr):  # years label value columns only
            for v, j in zip(hr, nonpct):
                parts[j] = v
        elif pct and k == len(segs):  # periods span value runs; "Percentage Change" sits over each % column
            for v, seg in zip(hr, segs):
                for j in seg:
                    parts[j] = v
        elif pct and k == len(nonpct):
            for v, j in zip(hr, nonpct):
                parts[j] = v
        elif k and ncols % k == 0:
            parts = [v for v in hr for _ in range(ncols // k)]
        else:
            return None
        cols = [f"{a} {b}".strip() for a, b in zip(cols, parts)]
    return [re.sub(r"\s+", " ", c).replace(" ,", ",").strip() for c in cols]


# ---------------------------------------------------------------------------------------------
# 4. section text -> blocks
# ---------------------------------------------------------------------------------------------
def _build_table(rows_raw: list[dict], caption: list[str]) -> Table:
    """Rows before the first row carrying a (non-year) number are header candidates: they become header rows
    when they have values or are a period heading ("Three Months Ended"); group labels ("Revenue:") stay rows."""
    t = Table(caption=caption, start=rows_raw[0]["start"], end=rows_raw[-1]["end"])
    parsed = []
    for it in rows_raw:
        label, values, unit = split_row(it["text"])
        if unit and not t.unit:
            t.unit = unit
        if label or values:
            parsed.append((label, values))
    first_num = next((i for i, (_, v) in enumerate(parsed) if any(_is_value(x) and not YEAR_RE.match(x) for x in v)), None)
    if first_num is None:  # text-only table (e.g. a definitions table): no header inference
        t.rows = parsed
    else:
        for label, values in parsed[:first_num]:
            if values and all(not _is_value(v) or YEAR_RE.match(v) for v in values):
                t.header_rows.append(([label] if label else []) + values)
            elif not values and PERIOD_LABEL_RE.match(label):
                t.header_rows.append([label])
            else:
                t.rows.append((label, values))
        t.rows += parsed[first_num:]
    t.columns = compose_columns(t.header_rows, t.rows, t.ncols)
    return t


def parse_section(text: str, drop_page_noise: bool = True) -> list[dict]:
    """Section text -> ordered blocks:
       {"type": "text", "text", "start", "end"}  one paragraph
       {"type": "table", "table": Table, "start", "end"}"""
    items = logical_items(text)
    blocks: list[dict] = []
    i = 0
    while i < len(items):
        it = items[i]
        if it["type"] == "text":
            if not (drop_page_noise and PAGE_NOISE_RE.match(it["text"])):
                blocks.append({"type": "text", "text": it["text"], "start": it["start"], "end": it["end"]})
            i += 1
            continue
        # collect a run of rows; page-noise lines (page number, "PART I", "Item 1") do not end a table
        rows, j = [], i
        while j < len(items) and (items[j]["type"] == "row" or PAGE_NOISE_RE.match(items[j]["text"])):
            if items[j]["type"] == "row":
                rows.append(items[j])
            j += 1
        caption = []
        for b in reversed(blocks[-2:]):
            # a caption is a short heading ("INCOME STATEMENTS", "... was as follows:"), not a sentence
            if b["type"] != "text" or len(b["text"]) > 200 or b["text"].rstrip().endswith("."):
                break
            caption.insert(0, b["text"])
        tbl = _build_table(rows, caption)
        # footnotes: "(a)" marker lines (+ the explanation that follows) right after the table
        k = j
        while k < len(items) and items[k]["type"] == "text" and FOOTNOTE_MARK_RE.match(items[k]["text"]):
            note = items[k]["text"]
            if len(note) <= 5 and k + 1 < len(items) and items[k + 1]["type"] == "text":
                note = f"{note} {items[k + 1]['text']}"
                k += 1
            tbl.footnotes.append(note)
            k += 1
        blocks.append({"type": "table", "table": tbl, "start": tbl.start, "end": tbl.end})
        i = j  # footnote lines stay in the text stream too
    return blocks


# ---------------------------------------------------------------------------------------------
# 5. rendering + splitting
# ---------------------------------------------------------------------------------------------
def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def header_lines(t: Table, fmt: str = "markdown") -> list[str]:
    out = list(t.caption)
    if t.unit:
        out.append(t.unit)
    n = t.ncols
    if fmt == "markdown":
        if t.columns:
            out += [_md_row([""] + t.columns), _md_row(["---"] * (n + 1))]
        else:
            out += [f"Columns: {' | '.join(h)}" for h in t.header_rows]
            if n:
                out += [_md_row([""] * (n + 1)), _md_row(["---"] * (n + 1))]
    elif not t.columns:
        out += [f"Columns: {' | '.join(h)}" for h in t.header_rows]
    return out


def row_line(t: Table, label: str, values: list[str], fmt: str = "markdown") -> str:
    if fmt == "linear":
        if not values:
            return f"{label}:" if label and not label.endswith(":") else label
        if t.columns and len(values) == len(t.columns):
            return f"{label}: " + "; ".join(f"{c} = {v}" for c, v in zip(t.columns, values))
        return f"{label}: " + "; ".join(values)
    n = t.ncols
    vals = values + [""] * (n - len(values)) if len(values) < n else values
    return _md_row([label] + vals)


def render(t: Table, fmt: str = "markdown") -> str:
    body = [row_line(t, l, v, fmt) for l, v in t.rows]
    return "\n".join(header_lines(t, fmt) + body + t.footnotes)


def split_table(t: Table, count_tokens: Callable[[str], int], max_tokens: int, fmt: str = "markdown") -> list[str]:
    """Whole table if it fits, else row groups; every piece repeats caption + unit + column header, and a
    piece that starts inside a row group ("Revenue:", "Cost of revenue:") repeats that group label."""
    whole = render(t, fmt)
    if count_tokens(whole) <= max_tokens:
        return [whole]
    head = header_lines(t, fmt)
    pieces, buf, group = [], [], None
    budget = max_tokens - count_tokens("\n".join(head)) - 4
    for label, values in t.rows:
        line = row_line(t, label, values, fmt)
        if buf and count_tokens("\n".join(buf + [line])) > budget:
            pieces.append("\n".join(head + buf))
            buf = [row_line(t, f"{group} (cont.)", [], fmt)] if group else []
        buf.append(line)
        if not values:
            group = label.rstrip(":") if label else None
    tail = buf + t.footnotes
    if tail:
        if pieces and count_tokens("\n".join(head + tail)) > max_tokens and t.footnotes:
            pieces.append("\n".join(head + buf))
            pieces.append("\n".join(head + t.footnotes))
        else:
            pieces.append("\n".join(head + tail))
    return pieces
