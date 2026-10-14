"""Turn an EDGAR filing (HTML / inline XBRL) into an ordered list of text and table blocks.

Output: [{"type": "text", "text": "..."}, {"type": "table", "text": "<markdown>"}, ...]

Design notes
* Hidden inline-XBRL content (<ix:header>, display:none) is removed.
* Real data tables (>= 2 rows with >= 2 non-empty cells) become Markdown and stay whole (D3).
* Layout tables (e.g. a one-row table holding "Item 1A." | "Risk Factors") are flattened to a
  text line, so Item headings inside tables are still detected by the chunker.
* SEC tables split "$", "1,234" and ")" into separate cells; these are merged back.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString

_BLOCK_TAGS = ["p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"]
_MARK = "TABLE{}"
_MARK_RE = re.compile("^TABLE(\\d+)$")
_WS_RE = re.compile(r"[ \t\r\f\v    ​]+")
_JUNK_LINE_RE = re.compile(r"^(\d{1,3}|table of contents|index|page)$", re.I)


def _cell_text(cell) -> str:
    return _WS_RE.sub(" ", cell.get_text(" ")).strip()


def _table_rows(table) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_cell_text(c) for c in tr.find_all(["td", "th"])]
        merged: list[str] = []
        for c in cells:
            if c == "":
                continue
            if c in (")", "%", ")%", "%)") and merged:
                merged[-1] += c
            elif merged and merged[-1] in ("$", "(", "$(", "($"):
                merged[-1] += c
            else:
                merged.append(c)
        if merged:
            rows.append(merged)
    return rows


_NO_LETTERS_RE = re.compile(r"^[^A-Za-z]*$")


def _to_markdown(rows: list[list[str]]) -> str:
    """Rows were compacted (empty cells dropped), so re-align short rows: a row that starts with a
    number/year (typically the column-header row, missing the label column) is padded on the LEFT;
    other rows (a label with some values missing) are padded on the right."""
    width = max(len(r) for r in rows)
    rows = [([""] * (width - len(r)) + r) if _NO_LETTERS_RE.match(r[0]) else (r + [""] * (width - len(r))) for r in rows]
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    lines = ["| " + " | ".join(esc(c) for c in rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def html_to_blocks(html: str | bytes) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    for tag in soup.find_all(["ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()

    tables: list[str] = []
    # reversed document order -> inner tables are handled before the tables containing them
    for table in reversed(soup.find_all("table")):
        rows = _table_rows(table)
        data_rows = [r for r in rows if len(r) >= 2]
        if len(data_rows) >= 2:
            table.replace_with(NavigableString("\n" + _MARK.format(len(tables)) + "\n"))
            tables.append(_to_markdown(rows))
        else:  # layout table -> plain text line(s)
            text = "\n".join(" ".join(r) for r in rows)
            table.replace_with(NavigableString("\n" + text + "\n"))

    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after(NavigableString("\n"))

    blocks: list[dict] = []
    for raw in soup.get_text("").split("\n"):
        line = _WS_RE.sub(" ", raw).strip()
        if not line or _JUNK_LINE_RE.match(line):
            continue
        m = _MARK_RE.match(line)
        if m:
            blocks.append({"type": "table", "text": tables[int(m.group(1))]})
        else:
            blocks.append({"type": "text", "text": line})
    return blocks
