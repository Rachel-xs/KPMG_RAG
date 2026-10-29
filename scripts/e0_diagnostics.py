"""E0 chunking diagnostics (Week 6 plan): measure Data-team chunks before changing anything.

Reports
  1. bge-small token length distribution and share of chunks over the 512-token limit (silently truncated)
  2. table quality: chunks carrying table rows, empty-cell ratio, table chunks missing a column header / unit line
  3. boundary damage: chunk boundaries that fall mid-word or inside a table
  4. Gold anchors: is every `contains` string inside ONE chunk (strict hit possible)? does that chunk also carry
     the column header (e.g. "Three Months Ended") needed to read the number?
  5. Exp1 misses (hybrid, filtered, recall@5 < 1) joined to the categories above

    python scripts/e0_diagnostics.py \
        --chunks ../kpmg-rag-retrieval/data/chunks/chunks.jsonl \
        --tokenizer ~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/<rev>/tokenizer.json \
        --gold eval/gold_v0_msft.jsonl --per-question eval/results/per_question_20261014-174752.csv
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import statistics
from pathlib import Path

LIMIT = 512
HEADER_RE = re.compile(r"(months|weeks|year|quarter)s?\s+ended|as of\b|^\W*(20\d\d|19\d\d)\W*$", re.I)
UNIT_RE = re.compile(r"\(\s*in (millions|thousands|billions)", re.I)


def is_table_line(line: str) -> bool:
    return line.count("|") >= 2


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("|")]


def has_col_header(lines: list[str]) -> bool:
    """A period/column header: 'Three Months Ended', 'As of', or a row whose non-empty cells are all years."""
    for ln in lines:
        if HEADER_RE.search(ln):
            return True
        if is_table_line(ln):
            ne = [c for c in cells(ln) if c]
            if ne and all(re.fullmatch(r"(19|20)\d\d", c) for c in ne):
                return True
    return False


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def stitch(chunks: list[dict]) -> tuple[str, int]:
    """Rebuild filing text from overlapping chunks using Data's char offsets. Returns (text, base_offset)."""
    base = min(c["offset_start"] for c in chunks)
    end = max(c["offset_start"] + len(c["text"]) for c in chunks)
    buf = [" "] * (end - base)
    for c in sorted(chunks, key=lambda c: c["offset_start"]):
        s = c["offset_start"] - base
        buf[s : s + len(c["text"])] = c["text"]
    return "".join(buf), base


def line_at(text: str, pos: int) -> str:
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a : b if b != -1 else len(text)]


def neighbour_lines(text: str, pos: int) -> tuple[str, str]:
    """Nearest non-empty line before and after pos."""
    before = [l for l in text[max(0, pos - 2000) : pos].split("\n") if l.strip()]
    after = [l for l in text[pos : pos + 2000].split("\n") if l.strip()]
    return (before[-1] if before else ""), (after[0] if after else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--tokenizer", required=True, help="bge-small tokenizer.json")
    ap.add_argument("--gold", default="eval/gold_v0_msft.jsonl")
    ap.add_argument("--per-question", default=None, help="Exp1 per-question csv (optional)")
    ap.add_argument("--out", default="eval/results/e0_diagnostics")
    a = ap.parse_args()

    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(Path(a.tokenizer).expanduser()))
    tok.no_truncation()

    C = [json.loads(l) for l in open(a.chunks)]
    by_filing: dict[str, list[dict]] = collections.defaultdict(list)
    for c in C:
        by_filing[c["accession"]].append(c)

    # ---- 1 + 2: per-chunk stats ------------------------------------------------------------
    lens = [len(e.ids) for e in tok.encode_batch([c["text"] for c in C])]
    for c, n in zip(C, lens):
        lines = [l for l in c["text"].split("\n") if l.strip()]
        tl = [l for l in lines if is_table_line(l)]
        cs = [x for l in tl for x in cells(l)]
        c["_bge"] = n
        c["_table_lines"] = len(tl)
        c["_has_table"] = len(tl) >= 2
        c["_cells"] = len(cs)
        c["_empty_cells"] = sum(1 for x in cs if not x)
        c["_has_header"] = has_col_header(lines)
        c["_has_unit"] = bool(UNIT_RE.search(c["text"]))
        c["_numeric_rows"] = sum(1 for l in tl if re.search(r"\d[\d,]{2,}", l))

    def dist(xs):
        xs = sorted(xs)
        q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
        return {"n": len(xs), "mean": round(statistics.mean(xs), 1), "p50": q(0.5), "p90": q(0.9), "p99": q(0.99), "max": xs[-1],
                "over_512": sum(x > LIMIT for x in xs), "over_512_pct": pct(sum(x > LIMIT for x in xs), len(xs))}

    tab = [c for c in C if c["_has_table"]]
    num_tab = [c for c in tab if c["_numeric_rows"] >= 2]
    report = {
        "corpus": {"n_chunks": len(C), "n_filings": len(by_filing), "chunking_version": sorted({c["chunking_version"] for c in C}),
                   "filings": {k: f"{v[0]['ticker']} {v[0]['form']} {v[0]['period_of_report']} ({len(v)} chunks)" for k, v in by_filing.items()}},
        "tokens_bge_all": dist(lens),
        "tokens_bge_table_chunks": dist([c["_bge"] for c in tab]) if tab else None,
        "tokens_bge_text_chunks": dist([c["_bge"] for c in C if not c["_has_table"]]),
        "tables": {
            "chunks_with_table_rows": len(tab), "chunks_with_table_rows_pct": pct(len(tab), len(C)),
            "flagged_is_table_by_pipeline": sum(bool(c.get("is_table")) for c in C),
            "empty_cell_ratio": round(sum(c["_empty_cells"] for c in tab) / max(1, sum(c["_cells"] for c in tab)), 3),
            "numeric_table_chunks": len(num_tab),
            "numeric_table_chunks_without_col_header": sum(not c["_has_header"] for c in num_tab),
            "numeric_table_chunks_without_col_header_pct": pct(sum(not c["_has_header"] for c in num_tab), len(num_tab)),
            "numeric_table_chunks_without_unit_line": sum(not c["_has_unit"] for c in num_tab),
            "numeric_table_chunks_without_unit_line_pct": pct(sum(not c["_has_unit"] for c in num_tab), len(num_tab)),
        },
    }

    # ---- 3: boundary damage (needs stitched filing text) -------------------------------------
    texts = {}
    mid_word = mid_table = boundaries = 0
    overlaps = []
    for acc, cs in by_filing.items():
        text, base = stitch(cs)
        texts[acc] = (text, base)
        cs = sorted(cs, key=lambda c: c["offset_start"])
        for prev, c in zip(cs, cs[1:]):
            boundaries += 1
            overlaps.append(prev["offset_start"] + len(prev["text"]) - c["offset_start"])
            p = c["offset_start"] - base
            if 0 < p < len(text) and text[p - 1].isalnum() and text[p].isalnum():
                mid_word += 1
            b, f = neighbour_lines(text, p)
            if is_table_line(b) and is_table_line(f) and is_table_line(line_at(text, p) or b):
                mid_table += 1
    report["boundaries"] = {
        "n_boundaries": boundaries,
        "overlap_chars_median": statistics.median(overlaps) if overlaps else None,
        "start_mid_word": mid_word, "start_mid_word_pct": pct(mid_word, boundaries),
        "inside_table": mid_table, "inside_table_pct": pct(mid_table, boundaries),
    }

    # ---- 4: Gold anchors ---------------------------------------------------------------------
    gold = [json.loads(l) for l in open(a.gold)]
    ev_rows = []
    for q in gold:
        for i, e in enumerate(q["gold"].get("evidence", [])):
            subs = [s.lower() for s in e.get("contains", [])]
            acc = e.get("accession")
            if not subs or acc not in by_filing:
                ev_rows.append({"qid": q["qid"], "ev": i, "status": "no_anchor_or_filing_not_in_corpus"})
                continue
            holders = [c for c in by_filing[acc] if all(s in c["text"].lower() for s in subs)]
            text = texts[acc][0].lower()
            in_filing = all(s in text for s in subs)
            if holders:
                status = "single_chunk"
            elif in_filing:
                status = "split_across_chunks"
            else:
                status = "not_found_in_filing"
            in_table = False
            if in_filing:
                pos = text.find(subs[0])
                in_table = is_table_line(line_at(text, pos))
            ev_rows.append({
                "qid": q["qid"], "tier": q.get("tier"), "ev": i, "region": e.get("region"), "contains": e.get("contains"),
                "status": status, "n_holder_chunks": len(holders), "anchor_in_table": in_table,
                "holder_has_col_header": any(c["_has_header"] for c in holders),
                "holder_has_unit": any(c["_has_unit"] for c in holders),
                "holder_over_512": any(c["_bge"] > LIMIT for c in holders),
                # number sits beyond token 512 of every chunk that holds it -> invisible to dense retrieval
                "anchor_truncated_in_all_holders": bool(holders) and all(
                    len(tok.encode(c["text"][: c["text"].lower().find(subs[0])]).ids) >= LIMIT for c in holders),
            })
    st = collections.Counter(r["status"] for r in ev_rows)
    single = [r for r in ev_rows if r["status"] == "single_chunk"]
    report["gold_anchors"] = {
        "n_questions": len(gold), "n_evidence": len(ev_rows), "status": dict(st),
        "anchor_in_table": sum(r.get("anchor_in_table", False) for r in ev_rows),
        "single_chunk_but_no_col_header": sum(not r["holder_has_col_header"] for r in single),
        "single_chunk_but_no_unit": sum(not r["holder_has_unit"] for r in single),
        "anchor_beyond_token_512_in_all_holders": sum(r["anchor_truncated_in_all_holders"] for r in single),
    }

    # ---- 5: Exp1 misses ----------------------------------------------------------------------
    if a.per_question and Path(a.per_question).exists():
        rows = [r for r in csv.DictReader(open(a.per_question)) if r["filters"] == "filtered" and r["method"] == "hybrid"]
        evq = collections.defaultdict(list)
        for r in ev_rows:
            evq[r["qid"]].append(r)
        misses = []
        for r in rows:
            if float(r["evidence_recall@5"]) < 1:
                es = evq.get(r["qid"], [])
                misses.append({"qid": r["qid"], "tier": r["tier"], "recall@5": float(r["evidence_recall@5"]),
                               "recall@10": float(r["evidence_recall@10"]),
                               "evidence_status": [e["status"] for e in es],
                               "anchor_in_table": [e.get("anchor_in_table") for e in es],
                               "holder_has_col_header": [e.get("holder_has_col_header") for e in es]})
        report["exp1_hybrid_filtered_misses"] = {
            "n_questions": len(rows), "n_missed_at_5": len(misses),
            "missed_with_split_anchor": sum("split_across_chunks" in m["evidence_status"] for m in misses),
            "missed_with_table_anchor": sum(any(m["anchor_in_table"]) for m in misses),
            "by_tier": dict(collections.Counter(m["tier"] for m in misses)),
            "questions": misses,
        }

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report["evidence_detail"] = ev_rows
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k not in ("evidence_detail",)}, indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
