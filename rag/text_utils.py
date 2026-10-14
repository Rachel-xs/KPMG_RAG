"""Small shared helpers: token counting and tokenization for BM25."""
from __future__ import annotations

import re

try:  # optional, more accurate token counts
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover
    _ENC = None


def n_tokens(text: str) -> int:
    if _ENC is not None:
        return len(_ENC.encode(text, disallowed_special=()))
    return int(len(text.split()) * 1.33) + 1  # rough English approximation


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,\-&][a-z0-9]+)*")
_STOP = set(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "will with we our us which what who how when where does did do".split()
)


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("\u2019", "'").replace("'s ", " ")
    return [t for t in _TOKEN_RE.findall(text) if t not in _STOP]
