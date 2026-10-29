"""Build a chunking variant from Data's chunks (Week 6 chunking plan).

Data's `paragraph-v1` chunks overlap by ~150 chars and carry filing-level char offsets, so each section's
full text can be stitched back exactly; variants then re-chunk that text inside the section
(Data still owns the Part/Item split, section_id and offsets).

  A          Data's chunks unchanged (baseline; copied with bge token counts)
  B          tables -> whole cleaned markdown (split by rows only if > --max-tokens, header repeated);
             text   -> paragraph packing like paragraph-v1 (~1,500 chars, 150-char overlap, word boundaries)
  B-linear   as B, but every table row rendered as "label: column = value; ..." (one line per row)
  C1         B tables; text -> fixed windows of --max-tokens bge tokens, ~10% overlap, cut anywhere
  C2         B tables; text -> recursive: paragraph > sentence > words, <= --max-tokens, ~10% overlap

    python scripts/build_chunk_variant.py --variant B --in data/chunks_A/chunks.jsonl \
        --out data/chunks_B/chunks.jsonl --tokenizer <bge-small tokenizer.json>

--max-tokens is the BODY budget; rag.index prepends a ~20-40 token header ("Microsoft Corporation (MSFT) 10-Q
Q3FY2026 | Part I Item 1 ..."), so 460 keeps the embedded text under bge-small's 512 limit.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.tables import parse_section, render, split_table  # noqa: E402

META_KEYS = ("ticker", "cik", "company", "form", "fiscal_year", "fiscal_period", "period_of_report", "filing_date",
             "accession", "section", "section_title", "section_type", "section_id", "source_url", "source_sha256",
             "extraction_version")
# a sub-heading inside an Item: short, starts upper-case, no sentence punctuation ("Liquidity and Capital Resources")
HEADING_RE = re.compile(r"^(?:Note \d+\s*[–—-]\s*)?[A-Z][^.:;|]{2,90}$")
SENT_RE = re.compile(r"(?<=[.!?;:])\s+(?=[\"“(A-Z0-9$])")


class Tok:
    def __init__(self, path: str):
        from tokenizers import Tokenizer

        self.t = Tokenizer.from_file(str(Path(path).expanduser()))
        self.t.no_truncation()

    def n(self, s: str) -> int:
        return len(self.t.encode(s, add_special_tokens=False).ids)

    def offsets(self, s: str) -> list[tuple[int, int]]:
        return self.t.encode(s, add_special_tokens=False).offsets


def stitch(cs: list[dict]) -> tuple[str, int]:
    cs = sorted(cs, key=lambda c: c["offset_start"])
    base = cs[0]["offset_start"]
    end = max(c["offset_start"] + len(c["text"]) for c in cs)
    buf = ["\n"] * (end - base)
    for c in cs:
        s = c["offset_start"] - base
        buf[s : s + len(c["text"])] = c["text"]
    return "".join(buf), base


# ------------------------------------------------------------------------------------------------
# text splitters: input = list of (paragraph, start, end) in section coordinates
# output = list of (text, start, end)
# ------------------------------------------------------------------------------------------------
def pack_paragraphs(paras, max_chars=1500, overlap_chars=150):
    """Emulates Data's paragraph-v1 (char budget + char overlap), but starts the overlap on a word boundary."""
    out, buf = [], []
    for p in paras:
        if buf and sum(len(x[0]) + 2 for x in buf) + len(p[0]) > max_chars:
            out.append(buf)
            tail = "\n\n".join(x[0] for x in buf)[-overlap_chars:]
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            buf = [(tail, buf[-1][2] - len(tail), buf[-1][2])] if tail else []
        buf.append(p)
    if buf:
        out.append(buf)
    return [("\n\n".join(x[0] for x in g), g[0][1], g[-1][2]) for g in out]


def fixed_windows(paras, tok: Tok, max_tokens: int, overlap: float = 0.1):
    """Token windows over the concatenated text, cut anywhere (C1 control)."""
    if not paras:
        return []
    text = "\n\n".join(p[0] for p in paras)
    offs = tok.offsets(text)
    step = max(1, int(max_tokens * (1 - overlap)))
    out, i = [], 0
    s0 = paras[0][1]
    while i < len(offs):
        j = min(len(offs), i + max_tokens)
        a, b = offs[i][0], offs[j - 1][1]
        out.append((text[a:b], s0 + a, s0 + b))  # offsets approximate (paragraph joins)
        if j == len(offs):
            break
        i += step
    return out


def _units(p, tok: Tok, max_tokens: int):
    """Paragraph -> pieces that each fit: the paragraph, else its sentences, else word windows."""
    text, s, e = p
    if tok.n(text) <= max_tokens:
        return [p]
    out, pos = [], 0
    for sent in SENT_RE.split(text):
        st = text.find(sent, pos)
        pos = st + len(sent)
        if tok.n(sent) <= max_tokens:
            out.append((sent, s + st, s + pos))
        else:
            words = sent.split(" ")
            step = max(1, int(max_tokens / 1.6))
            for k in range(0, len(words), step):
                w = " ".join(words[k : k + step])
                out.append((w, s + st, s + pos))
    return out


def recursive_split(paras, tok: Tok, max_tokens: int, overlap: float = 0.1):
    """C2: pack paragraphs; split long ones by sentence, then words; carry trailing sentences as overlap."""
    units = [u for p in paras for u in _units(p, tok, max_tokens)]
    ov_budget = int(max_tokens * overlap)
    out, buf, n = [], [], 0
    for u in units:
        t = tok.n(u[0]) + 2
        if buf and n + t > max_tokens:
            out.append(buf)
            carry, cn = [], 0
            for x in reversed(buf):  # whole trailing sentences up to the overlap budget
                for sent in reversed(SENT_RE.split(x[0])):
                    k = tok.n(sent) + 1
                    if cn + k > ov_budget:
                        break
                    carry.insert(0, (sent, x[2] - len(sent), x[2]))
                    cn += k
                break
            buf, n = carry, cn
        buf.append(u)
        n += t
    if buf:
        out.append(buf)
    return [("\n\n".join(x[0] for x in g), g[0][1], g[-1][2]) for g in out]


# ------------------------------------------------------------------------------------------------
# running page headers that look like headings but carry no topic
BOILERPLATE_RE = re.compile(r"\(continued\)|^form 10-[kq]$|^united states$|^table of contents$|^securities and exchange commission|^exhibit$", re.I)


def _is_heading(text: str) -> bool:
    return bool(HEADING_RE.match(text)) and not BOILERPLATE_RE.search(text) and len(text.split()) <= 12 and not re.search(r"\d[\d,]{3,}", text)


def build(chunks: list[dict], variant: str, tok: Tok, max_tokens: int, parents: dict | None = None) -> list[dict]:
    """variant = base ("B", "B-linear", "C1", "C2") optionally + "+L" (tables rendered one line per row,
    "label: column = value; ...") and/or "+E" (context header = nearest sub-heading), e.g. "C1+L+E".
    If `parents` is a dict it is filled with {table_id: whole rendered table} for parent-child retrieval (F)."""
    if variant == "A":
        for c in chunks:
            c["n_tokens"] = tok.n(c["text"])
        return chunks
    base_variant, _, flags = variant.partition("+")
    flag_set = set(flags.split("+")) - {""}
    use_e = "E" in flag_set

    fmt = "linear" if base_variant == "B-linear" or "L" in flag_set else "markdown"
    version = f"rag-{variant}-v0" + (f"-m{max_tokens}" if base_variant in ("C1", "C2") else "")
    by_sec = collections.defaultdict(list)
    for c in chunks:
        by_sec[(c["accession"], c["section_id"])].append(c)
    # keep the original filing order of sections
    order = sorted(by_sec, key=lambda k: (k[0], min(c["offset_start"] for c in by_sec[k])))

    out, seq_by_filing = [], collections.Counter()
    for key in order:
        cs = by_sec[key]
        meta = {k: cs[0].get(k) for k in META_KEYS}
        text, base = stitch(cs)
        blocks = parse_section(text)
        paras = [(b["text"], b["start"], b["end"]) for b in blocks if b["type"] == "text"]
        tables = [b for b in blocks if b["type"] == "table"]

        headings = [(b["start"], b["text"]) for b in blocks if b["type"] == "text" and _is_heading(b["text"])]
        if base_variant in ("B", "B-linear"):
            texts = pack_paragraphs([u for p in paras for u in _units(p, tok, max_tokens)])
        elif base_variant == "C1":
            texts = fixed_windows(paras, tok, max_tokens)
        elif base_variant == "C2":
            texts = recursive_split(paras, tok, max_tokens)
        else:
            raise SystemExit(f"unknown variant {variant}")

        recs = []
        for t, s, e in texts:
            recs.append({"text": t, "is_table": False, "start": s, "end": e, "table_id": None})
        for ti, b in enumerate(tables):
            tid = f"{meta['section_id']}-t{ti:02d}"
            if parents is not None:
                parents[tid] = render(b["table"], fmt)
            for piece in split_table(b["table"], tok.n, max_tokens, fmt):
                recs.append({"text": piece, "is_table": True, "start": b["start"], "end": b["end"], "table_id": tid})
        recs.sort(key=lambda r: (r["start"], r["is_table"]))
        for r in recs:
            acc = meta["accession"]
            seq = seq_by_filing[acc]
            seq_by_filing[acc] += 1
            ctx = None
            if use_e:  # nearest sub-heading at or before the chunk start (skip a heading identical to the section title)
                prior = [h for st, h in headings if st <= r["start"] + 5]
                ctx = prior[-1] if prior and prior[-1].lower() != (meta.get("section_title") or "").lower() else None
            out.append({
                "chunk_id": f"{meta['section_id']}-{variant}-{seq:04d}",
                **meta,
                "is_table": r["is_table"],
                "table_id": r["table_id"],
                "parent_chunk_id": r["table_id"],  # schema v1 optional field; tables: the whole table is the parent (variant F)
                "seq": seq,
                "n_tokens": tok.n(r["text"]),
                "offset_start": base + r["start"],
                "offset_end": base + r["end"],
                "chunking_version": version,
                **({"context_header": ctx} if ctx else {}),
                "text": r["text"],
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, help="A, B, B-linear, C1, C2, optionally +L / +E (e.g. C1+L+E)")
    ap.add_argument("--in", dest="inp", required=True, help="Data's chunks.jsonl (variant A)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tokenizer", required=True, help="bge-small tokenizer.json")
    ap.add_argument("--max-tokens", type=int, default=460, help="body token budget per chunk")
    a = ap.parse_args()

    tok = Tok(a.tokenizer)
    chunks = [json.loads(l) for l in open(a.inp)]
    out = build(chunks, a.variant, tok, a.max_tokens)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = [r["n_tokens"] for r in out]
    nt = [r for r in out if r["is_table"]]
    print(f"[{a.variant}] {len(out)} chunks ({len(nt)} table) | tokens mean={sum(n)/len(n):.0f} max={max(n)} "
          f"over_{a.max_tokens}={sum(x > a.max_tokens for x in n)} -> {a.out}")


if __name__ == "__main__":
    main()
