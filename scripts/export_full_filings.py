"""Pull the freeze list for the full-corpus index (10 core companies) from Data's RDS. Read-only, SELECT only.

    python scripts/export_full_filings.py                    # -> eval/full_filings.csv
    python scripts/export_full_filings.py --out other.csv

Source: finance.filing (one row per filing, with the processing set Data currently serves and its validation_status).
Output has the same columns as eval/round1_filings.csv, so the round-1 export/check scripts can be reused.
Prints counts by validation_status and by company; Data says the passed count should be 233.
Not tracked in git until after holdout B (keeps the tracked tree clean).
"""
import argparse, csv, json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import connect  # noqa: E402  (same .env / read-only account)

TICKERS = ["AAPL", "CASY", "MCK", "MDT", "MSFT", "MU", "NKE", "NTAP", "PH", "TTWO"]
COLS = ["ticker", "accession_number", "form", "filing_date", "reporting_period_end", "filing_id",
        "processing_family", "processing_set_id", "validation_status", "coverage", "selection_reason"]
SQL = f"""
SELECT ticker, accession_number, form, filing_date, reporting_period_end, filing_id,
       processing_family, processing_set_id, validation_status, coverage, selection_reason
FROM finance.filing
WHERE ticker = ANY(%s) AND form IN ('10-K', '10-Q')
ORDER BY ticker, reporting_period_end, form
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval" / "full_filings.csv"))
    args = ap.parse_args()
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(SQL, (TICKERS,))
        rows = cur.fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(zip(COLS, r))
        d["coverage"] = json.dumps(d["coverage"]) if d["coverage"] is not None else ""
        out.append({k: ("" if v is None else str(v)) for k, v in d.items()})
    passed = [d for d in out if d["validation_status"] == "passed"]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(passed)

    print(f"finance.filing rows for the 10 companies (10-K/10-Q): {len(out)}")
    print("by validation_status:", dict(Counter(d["validation_status"] for d in out)))
    print("\npassed, by company and form:")
    by = Counter((d["ticker"], d["form"]) for d in passed)
    for t in TICKERS:
        print(f"  {t:5} 10-K={by.get((t, '10-K'), 0):3}  10-Q={by.get((t, '10-Q'), 0):3}")
    dup = [a for a, n in Counter(d["accession_number"] for d in passed).items() if n > 1]
    print(f"\npassed total: {len(passed)} (Data says 233)  duplicate accessions: {dup or 'none'}")
    frozen = {r["accession_number"] for r in csv.DictReader(open(ROOT / "eval" / "round1_filings.csv"))}
    missing = sorted(frozen - {d["accession_number"] for d in passed})
    print(f"round-1 frozen filings included: {len(frozen) - len(missing)}/{len(frozen)}"
          + (f"  missing: {missing}" if missing else ""))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
