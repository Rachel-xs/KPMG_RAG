"""For each filing in eval/full_filings.csv, list the other processing versions Data keeps (finance.filing_version),
to see whether a passed legacy version exists for all 233 (the family our frozen index was built from). Read-only.

    python scripts/check_legacy_versions.py      # prints a summary, writes eval/full_filings_versions.csv
"""
import csv, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import connect  # noqa: E402

SQL = """SELECT filing_id::text, processing_family, processing_set_id::text, set_key, validation_status,
       is_preferred, created_at FROM finance.filing_version WHERE filing_id = ANY(%s::uuid[])"""

want = list(csv.DictReader(open(ROOT / "eval/full_filings.csv")))
fid = {r["filing_id"]: r for r in want}
conn = connect()
conn.set_session(readonly=True, autocommit=True)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = 120000")
    cur.execute(SQL, (list(fid),))
    rows = cur.fetchall()
conn.close()
out = ROOT / "eval/full_filings_versions.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ticker", "form", "accession_number", "reporting_period_end", "processing_family", "processing_set_id",
                "set_key", "validation_status", "is_preferred", "created_at"])
    for r in rows:
        x = fid[r[0]]
        w.writerow([x["ticker"], x["form"], x["accession_number"], x["reporting_period_end"]] + list(r[1:]))
print(f"{len(rows)} versions for {len({r[0] for r in rows})}/{len(fid)} filings")
print("by family x status:", dict(Counter((r[1], r[4]) for r in rows)))
legacy_ok = {r[0] for r in rows if r[1] == "legacy" and r[4] == "passed"}
print(f"filings with a PASSED legacy version: {len(legacy_ok)}/{len(fid)}")
missing = Counter(fid[f]["ticker"] for f in fid if f not in legacy_ok)
print("without a passed legacy version, by company:", dict(missing) or "none")
print(f"wrote {out}")
