"""Parent context for small-to-big retrieval (contract v1 `parent_id` / `parent_text`).

A child chunk is what retrieval ranks and what citations point at. Its parent is what the reader gets as
context: for a table piece, the whole rendered table (if it fits the cap); for a text chunk, the previous +
itself + next text chunk of the same section, shrunk until it fits. On Gold v1 this took recall from
0.852 (C1@460 child, k=8) to 0.890 (C2@300 + parent, k=5) at the same ~2.6k tokens.
"""
from __future__ import annotations

import collections
from typing import Callable

PARENT_CAP = 1500  # max tokens of one parent handed to the Agent


def parent_map(chunks: list[dict], tables: dict[str, str], n_tokens: Callable[[str], int],
               cap: int = PARENT_CAP) -> dict[str, tuple[str, str]]:
    """chunk_id -> (parent_id, parent_text)."""
    out: dict[str, tuple[str, str]] = {}
    by_sec = collections.defaultdict(list)
    for c in chunks:
        if c.get("is_table") and c.get("table_id") in tables:
            whole = tables[c["table_id"]]
            out[c["chunk_id"]] = (c["table_id"], whole) if n_tokens(whole) <= cap else (c["chunk_id"], c["text"])
        else:
            by_sec[(c.get("accession"), c.get("section_id"))].append(c)
    for cs in by_sec.values():
        cs.sort(key=lambda c: c["seq"])
        for i, c in enumerate(cs):
            for lo, hi in ((i - 1, i + 2), (i, i + 2), (i, i + 1)):
                win = cs[max(0, lo): hi]
                text = "\n\n".join(x["text"] for x in win)
                if n_tokens(text) <= cap or hi - lo == 1:
                    out[c["chunk_id"]] = ("win:" + "|".join(x["chunk_id"] for x in win), text)
                    break
    return out


def attach_parents(chunks: list[dict], tables: dict[str, str], n_tokens: Callable[[str], int],
                   cap: int = PARENT_CAP) -> list[dict]:
    """Write `parent_id` and `parent_text` onto each chunk record (in place) and return the list."""
    pm = parent_map(chunks, tables, n_tokens, cap)
    for c in chunks:
        pid, ptext = pm.get(c["chunk_id"], (c["chunk_id"], c["text"]))
        c["parent_id"], c["parent_text"] = pid, ptext
    return chunks
