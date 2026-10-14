"""Convert a DBeaver CSV export of sec.chunk_catalog into this repo's chunks.jsonl (Retrieval API v0 fields).

    python scripts/rds_to_chunks.py exports/chunks.csv data/chunks/chunks.jsonl --fye MSFT=0630,AAPL=0927

fiscal_year / fiscal_period are not stored in RDS; they are derived from reporting_period_end and the
company's fiscal-year-end MMDD (default 1231) with the same rule as rag.ingest.fiscal_label.
chunk_id keeps Data's UUID so citations join back to sec.chunk_citations.
"""
import argparse, csv, json, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.ingest import fiscal_label  # noqa: E402
from rag.text_utils import n_tokens  # noqa: E402

csv.field_size_limit(10**9)
TABLE_HINT = re.compile(r"(\n[^\n]*\d[\d,]{2,}[^\n]*){3,}")  # >=3 lines carrying numbers ~ a table


def section_key(row):
    """'Part I Item 2' style key when the title has an Item number, else Data's section_type."""
    title = (row.get("original_title") or "").strip()
    m = re.search(r"item\s*(\d{1,2}[a-c]?)", title, re.I)
    if m:
        part = re.search(r"part\s+(iv|iii|ii|i)\b", title, re.I)
        num = m.group(1).upper()
        return (f"Part {part.group(1).upper()} Item {num}" if part and row["form"].startswith("10-Q") else f"Item {num}")
    return row.get("section_type") or "Unlabeled"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("out")
    ap.add_argument("--fye", default="MSFT=0630", help="TICKER=MMDD,... fiscal year ends (default 1231)")
    a = ap.parse_args()
    fye = dict(x.split("=") for x in a.fye.split(",") if x)

    rows = list(csv.DictReader(open(a.csv, encoding="utf-8-sig")))
    seen, out = set(), []
    for r in rows:
        if r["chunk_id"] in seen:
            continue
        seen.add(r["chunk_id"])
        por = (r.get("reporting_period_end") or r["filing_date"])[:10]
        fy, fp = fiscal_label(por, fye.get(r["ticker"], "1231"), r["form"])
        text = r["text"]
        out.append({
            "chunk_id": r["chunk_id"],
            "ticker": r["ticker"] or f"CIK{r['cik']}",
            "cik": int(r["cik"]),
            "company": r["company_name"],
            "form": r["form"],
            "fiscal_year": fy,
            "fiscal_period": fp,
            "period_of_report": por,
            "filing_date": r["filing_date"][:10],
            "accession": r["accession_number"],
            "section": section_key(r),
            "section_title": r.get("original_title") or "",
            "section_type": r.get("section_type") or None,
            "section_id": r.get("section_id") or None,
            "is_table": bool(TABLE_HINT.search(text)),
            "seq": int(r["chunk_index"]),
            "n_tokens": n_tokens(text),
            "source_url": r.get("source_url") or "",
            "source_sha256": r.get("sha256") or None,
            "offset_start": int(r["offset_start"]),
            "offset_end": int(r["offset_end"]),
            "chunking_version": r.get("chunking_version") or "",
            "extraction_version": r.get("extraction_version") or "",
            "text": text,
        })
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for c in out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    by = Counter((c["ticker"], c["form"], f"{c['fiscal_period']}FY{c['fiscal_year']}") for c in out)
    print(f"[rds] {len(out)} chunks from {len(rows)} rows -> {a.out}")
    for k, n in sorted(by.items()):
        print(f"   {k[0]:6s} {k[1]:5s} {k[2]:9s} {n:5d} chunks")


if __name__ == "__main__":
    main()
