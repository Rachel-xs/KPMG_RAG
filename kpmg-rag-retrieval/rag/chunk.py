"""Section-aware chunking of SEC filings (Decision D3).

1. Detect "PART I/II" and "Item N." headings.
2. The table of contents repeats every heading. For each Item we ignore "dense" occurrences
   (headings within 3 blocks of another heading, i.e. TOC lines) when a non-dense one exists,
   and keep the longest remaining occurrence (all dense -> the last one, i.e. the body).
3. Text not covered by a detected Item is kept as section "Unlabeled" (nothing is dropped).
   Some bank 10-Ks are laid out as an annual report with a Form 10-K cross-reference index,
   so Item coverage can be low for them — check `section_coverage` in the build report.
4. Inside a section, paragraphs are packed into ~target_tokens chunks (hard cap max_tokens);
   each table is its own chunk (prefixed with its caption line), split by rows only if huge.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .parse import html_to_blocks
from .text_utils import n_tokens

# Stamped on every chunk (Retrieval API v0 `chunking_version` / `extraction_version`).
# Bump when chunk boundaries or parsed text change, so eval results stay traceable.
CHUNKER_NAME = "item-aware-v0"
EXTRACTION_VERSION = "rag.parse-v0"

ITEM_RE = re.compile(r"^item\s*(\d{1,2}[a-c]?)\s*[\.:\-–—]?\s*(.{0,150})$", re.I)
PART_RE = re.compile(r"^part\s+(iv|iii|ii|i)\b", re.I)
_MAX_HEADING_CHARS = 160
_MIN_GAP_CHARS = 400  # uncovered text shorter than this (e.g. a TOC fragment) is ignored


def _headings(blocks: list[dict], form: str) -> list[tuple[int, str, str, int]]:
    heads, part = [], None
    is_10q = form.upper().startswith("10-Q")
    for i, b in enumerate(blocks):
        if b["type"] != "text" or len(b["text"]) > _MAX_HEADING_CHARS:
            continue
        text = b["text"]
        pm = PART_RE.match(text)
        if pm:
            part = pm.group(1).upper()
            text = PART_RE.sub("", text).strip(" .:-–—")  # "PART I — Item 1. Business"
        m = ITEM_RE.match(text)
        if not m:
            continue
        num = m.group(1).upper()
        title = m.group(2).strip(" .:-–—")
        body_start = i + 1
        if not title and i + 1 < len(blocks) and blocks[i + 1]["type"] == "text":
            nxt = blocks[i + 1]["text"]
            if len(nxt) < 120 and not ITEM_RE.match(nxt):
                title, body_start = nxt, i + 2
        key = f"Part {part or '?'} Item {num}" if is_10q else f"Item {num}"
        heads.append((i, key, title, body_start))
    return heads


def split_sections(blocks: list[dict], form: str) -> tuple[list[dict], float]:
    """Return ([{section, section_title, blocks}], item_coverage_fraction)."""
    heads = _headings(blocks, form)
    # A heading within 3 blocks of another heading is "dense" (typical of a table of contents).
    cands: dict[str, list[tuple[int, int, str, int, bool]]] = {}
    for j, (i, key, title, body_start) in enumerate(heads):
        end = heads[j + 1][0] if j + 1 < len(heads) else len(blocks)
        size = sum(len(b["text"]) for b in blocks[body_start:end])
        dense = (j > 0 and i - heads[j - 1][0] <= 3) or (j + 1 < len(heads) and heads[j + 1][0] - i <= 3)
        cands.setdefault(key, []).append((i, end, title, size, dense, body_start))
    best: dict[str, tuple] = {}
    for key, occ in cands.items():
        sparse = [o for o in occ if not o[4]]
        pick = max(sparse, key=lambda o: o[3]) if sparse else occ[-1]  # all dense -> last one
        best[key] = (pick[0], pick[1], pick[2], pick[5])

    spans = sorted((s, e, k, t, bs) for k, (s, e, t, bs) in best.items())
    sections, cursor, covered = [], 0, 0
    total = sum(len(b["text"]) for b in blocks) or 1

    def add_gap(a: int, b: int) -> None:
        gap = blocks[a:b]
        if sum(len(x["text"]) for x in gap) >= _MIN_GAP_CHARS:
            sections.append({"section": "Unlabeled", "section_title": "", "blocks": gap})

    for start, end, key, title, body_start in spans:
        if start < cursor:  # guard against overlaps
            start = body_start = cursor
        if start >= end:
            continue
        add_gap(cursor, start)
        # drop bare "PART II ..." lines that sit at the end of the previous section
        body = [b for b in blocks[body_start:end] if not (b["type"] == "text" and len(b["text"]) < _MAX_HEADING_CHARS and PART_RE.match(b["text"]))]
        covered += sum(len(x["text"]) for x in body)
        sections.append({"section": key, "section_title": title, "blocks": body})
        cursor = end
    add_gap(cursor, len(blocks))
    return sections, covered / total


def _split_long_text(text: str, max_tokens: int, target: int | None = None) -> list[str]:
    """Split an over-long paragraph at sentence boundaries into roughly EQUAL pieces
    (avoids a tiny leftover tail chunk)."""
    import math

    target = target or max_tokens
    total = n_tokens(text)
    budget = min(max_tokens, math.ceil(total / math.ceil(total / target)))
    sents = re.split(r"(?<=[.!?;])\s+", text)
    out, buf = [], ""
    for s in sents:
        if buf and n_tokens(buf + " " + s) > budget:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    # a single "sentence" can still be too long (e.g. a giant list): hard-split by words
    final = []
    for piece in out:
        if n_tokens(piece) > max_tokens:
            words = piece.split()
            step = max(1, int(budget / 1.4))
            final += [" ".join(words[k : k + step]) for k in range(0, len(words), step)]
        else:
            final.append(piece)
    return final


def _split_table(md: str, caption: str, max_tokens: int) -> list[str]:
    head = f"{caption}\n\n" if caption else ""
    if n_tokens(head + md) <= max_tokens:
        return [head + md]
    lines = md.split("\n")
    header, rows = lines[:2], lines[2:]
    pieces, buf = [], []
    for r in rows:
        if buf and n_tokens(head + "\n".join(header + buf + [r])) > max_tokens:
            pieces.append(head + "\n".join(header + buf))
            buf = []
        buf.append(r)
    if buf:
        pieces.append(head + "\n".join(header + buf))
    return pieces


def chunk_blocks(blocks: list[dict], target: int, max_tokens: int, min_tokens: int = 50) -> list[tuple[str, bool]]:
    # pre-split over-long paragraphs so their pieces are packed like normal paragraphs
    expanded: list[dict] = []
    for b in blocks:
        if b["type"] == "text" and n_tokens(b["text"]) > max_tokens:
            expanded += [{"type": "text", "text": t} for t in _split_long_text(b["text"], max_tokens, target)]
        else:
            expanded.append(b)

    chunks: list[tuple[str, bool]] = []
    buf: list[str] = []
    count = 0
    last_text = ""

    def flush():
        nonlocal buf, count
        if buf:
            text = "\n".join(buf)
            # merge a tiny tail into the previous prose chunk if it fits
            if count < min_tokens and chunks and not chunks[-1][1] and n_tokens(chunks[-1][0]) + count <= max_tokens:
                chunks[-1] = (chunks[-1][0] + "\n" + text, False)
            else:
                chunks.append((text, False))
        buf, count = [], 0

    for b in expanded:
        if b["type"] == "table":
            caption = last_text if 0 < len(last_text) <= 200 else ""
            if caption and buf and buf[-1] == caption:  # move caption line into the table chunk
                buf.pop()
                count -= n_tokens(caption)
            flush()
            chunks += [(t, True) for t in _split_table(b["text"], caption, max_tokens)]
            last_text = ""
            continue
        text = b["text"]
        last_text = text
        t = n_tokens(text)
        if buf and count + t > max_tokens:
            flush()
        buf.append(text)
        count += t
        if count >= target:
            flush()
    flush()
    return chunks


def chunk_filing(meta: dict, html: str | bytes, target: int = 600, max_tokens: int = 800) -> tuple[list[dict], dict]:
    """Chunk one filing. `meta` is a manifest row (see rag.ingest)."""
    blocks = html_to_blocks(html)
    sections, coverage = split_sections(blocks, meta["form"])
    records, seq = [], 0
    for sec in sections:
        for text, is_table in chunk_blocks(sec["blocks"], target, max_tokens):
            records.append(
                {
                    "chunk_id": f"{meta['ticker']}-{meta['accession']}-{seq:04d}",
                    "ticker": meta["ticker"],
                    "cik": meta["cik"],
                    "company": meta["company"],
                    "form": meta["form"],
                    "fiscal_year": meta["fiscal_year"],
                    "fiscal_period": meta["fiscal_period"],
                    "period_of_report": meta["period_of_report"],
                    "filing_date": meta["filing_date"],
                    "accession": meta["accession"],
                    "section": sec["section"],
                    "section_title": sec["section_title"],
                    "is_table": is_table,
                    "seq": seq,
                    "n_tokens": n_tokens(text),
                    "source_url": meta["source_url"],
                    "chunking_version": f"{CHUNKER_NAME}-t{target}-m{max_tokens}",
                    "extraction_version": EXTRACTION_VERSION,
                    "text": text,
                }
            )
            seq += 1
    report = {
        "ticker": meta["ticker"],
        "form": meta["form"],
        "period": f"{meta['fiscal_year']}{meta['fiscal_period']}",
        "n_chunks": len(records),
        "n_tables": sum(r["is_table"] for r in records),
        "sections": sorted({s["section"] for s in sections}),
        "section_coverage": round(coverage, 3),
    }
    return records, report


def chunk_corpus(raw_dir: Path, out_path: Path, target: int = 600, max_tokens: int = 800) -> list[dict]:
    raw_dir, out_path = Path(raw_dir), Path(out_path)
    manifest = [json.loads(l) for l in open(raw_dir / "manifest.jsonl")]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    reports = []
    with open(out_path, "w") as f:
        for meta in manifest:
            html = (raw_dir / meta["local_path"]).read_bytes()
            records, report = chunk_filing(meta, html, target, max_tokens)
            for r in records:
                f.write(json.dumps(r) + "\n")
            reports.append(report)
            flag = "  <-- LOW ITEM COVERAGE, inspect" if report["section_coverage"] < 0.5 else ""
            print(
                f"[chunk] {report['ticker']:5s} {report['form']:5s} {report['period']:7s} "
                f"chunks={report['n_chunks']:4d} tables={report['n_tables']:3d} "
                f"coverage={report['section_coverage']:.2f}{flag}"
            )
    (out_path.parent / "chunk_report.json").write_text(json.dumps(reports, indent=2))
    return reports
