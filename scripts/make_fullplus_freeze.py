"""Freeze list for the extended full index needed by XBRL set C (decided 11/24): the 233 core filings
(eval/full_filings_legacy.csv, unchanged) plus every non-core filing in the saved metric pull that set C draws from
(exports/metric_rows.json, 11/16, sha 7c7bb541...). Read-only database access.

    python scripts/make_fullplus_freeze.py
    -> eval/fullplus_filings.csv   (same columns as eval/full_filings.csv; core rows first)
       eval/fullplus_fye.txt       (TICKER=MMDD,... for rds_to_chunks --fye; from each company's 10-K period ends)

Version rule, same as the core 233 (make_legacy_freeze.py): newest PASSED legacy set, else the passed source set.
Fiscal-year end: the month-day of the company's latest 10-K reporting_period_end in the pull or in finance.filing;
52/53-week filers are fine (fiscal_label allows a 10-day tolerance); no 10-K anywhere -> 1231, listed in the output.
"""
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import connect  # noqa: E402

CORE = {"AAPL", "CASY", "MCK", "MDT", "MSFT", "MU", "NKE", "NTAP", "PH", "TTWO"}
CORE_FYE = "AAPL=0927,CASY=0430,MCK=0331,MDT=0424,MSFT=0630,MU=0903,NKE=0531,NTAP=0424,PH=0630,TTWO=0331"
COLS = ["ticker", "accession_number", "form", "filing_date", "reporting_period_end", "filing_id",
        "processing_family", "processing_set_id", "validation_status", "coverage", "selection_reason"]

rows = json.load(open(ROOT / "exports/metric_rows.json"))
accs = sorted({r["accession_number"] for r in rows if r["ticker"] not in CORE})
tickers = sorted({r["ticker"] for r in rows if r["ticker"] not in CORE and r["ticker"]})
print(f"metric pull: {len(accs)} non-core filings, {len(tickers)} non-core tickers", flush=True)

conn = connect()
conn.set_session(readonly=True, autocommit=True)
with conn.cursor() as cur:
    cur.execute("SET statement_timeout = 120000")
    cur.execute("""SELECT ticker, accession_number, form, filing_date::text, reporting_period_end::text, filing_id::text
                   FROM finance.filing WHERE accession_number = ANY(%s)""", (accs,))
    filings = {r[1]: dict(zip(["ticker", "accession_number", "form", "filing_date", "reporting_period_end", "filing_id"], r))
               for r in cur.fetchall()}
    cur.execute("""SELECT filing_id::text, processing_family, processing_set_id::text, validation_status, created_at
                   FROM finance.filing_version WHERE filing_id = ANY(%s::uuid[])""",
                ([f["filing_id"] for f in filings.values()],))
    vers = defaultdict(list)
    for fid, fam, ps, st, ts in cur.fetchall():
        vers[fid].append({"family": fam, "set": ps, "status": st, "created": str(ts)})
    cur.execute("""SELECT ticker, max(reporting_period_end)::text FROM finance.filing
                   WHERE form = '10-K' AND ticker = ANY(%s) GROUP BY ticker""", (tickers,))
    db_10k = dict(cur.fetchall())
conn.close()

out, why, missing = [], Counter(), []
for acc in accs:
    f = filings.get(acc)
    if not f:
        missing.append(acc); continue
    vs = vers.get(f["filing_id"], [])
    leg = sorted((v for v in vs if v["family"] == "legacy" and v["status"] == "passed"), key=lambda v: v["created"])
    src = [v for v in vs if v["family"] == "source" and v["status"] == "passed"]
    pick, reason = (leg[-1], "newest_passed_legacy") if leg else ((src[-1], "no_passed_legacy_use_source") if src else (None, "no_passed_version"))
    why[reason] += 1
    if pick is None:
        missing.append(acc); continue
    out.append({**f, "processing_family": pick["family"], "processing_set_id": pick["set"], "validation_status": "passed",
                "coverage": "", "selection_reason": reason})

core = list(csv.DictReader(open(ROOT / "eval/full_filings_legacy.csv")))
with open(ROOT / "eval/fullplus_filings.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
    w.writeheader(); w.writerows(core); w.writerows(out)

fye = dict(x.split("=") for x in CORE_FYE.split(","))
pull_10k = defaultdict(str)
for r in rows:
    if r["ticker"] not in CORE and r["form"] == "10-K" and r.get("reporting_period_end"):
        pull_10k[r["ticker"]] = max(pull_10k[r["ticker"]], r["reporting_period_end"][:10])
no_10k = []
for t in tickers:
    d = pull_10k.get(t) or db_10k.get(t)
    if d:
        fye[t] = d[5:7] + d[8:10]
    else:
        no_10k.append(t)
(ROOT / "eval/fullplus_fye.txt").write_text(",".join(f"{k}={v}" for k, v in sorted(fye.items())))

print(f"non-core filings kept: {len(out)} {dict(why)}")
print(f"not found / no passed version: {len(missing)} {missing[:10]}")
print(f"fiscal-year ends: {len(fye)} tickers; no 10-K found (default 1231): {no_10k}")
print(f"wrote eval/fullplus_filings.csv ({len(core)} core + {len(out)} non-core) and eval/fullplus_fye.txt")
