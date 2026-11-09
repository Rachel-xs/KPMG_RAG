"""Export the 21 frozen Round 1 filings straight from Data's RDS (no DBeaver needed).

    pip install psycopg2-binary
    python scripts/export_round1_rds.py                 # -> exports/round1_21.csv
    python scripts/export_round1_rds.py --check-only    # only print chunk counts per filing

Connection settings come from environment variables, or from a .env file in the repo root:
    RDS_HOST=<Data's RDS endpoint>
    RDS_PORT=5432
    RDS_DB=sec_filings
    RDS_USER=<your read-only account>
    RDS_PASSWORD=<password>
    RDS_SSLROOTCERT=/path/to/us-east-1-bundle.pem   # optional; without it SSL is required but not verified

Runs scripts/export_round1_21.sql. If the read-only account cannot read sec.filing_processing_sets
(permission denied), it falls back to the same 21 filings selected through sec.chunk_catalog.
The CSV has the same columns as the DBeaver export, so build_round1.sh works unchanged.
"""
import argparse, csv, os, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NTAP_10Q_SET = "3a047a1c-f436-4623-aead-3a104cc1099b"  # review_required in the freeze list

LEGACY_SETS = """
    '5e2bbc3a-3dcb-4098-b8a7-e9e8ea7922e4','8ba87c04-3452-4aa8-baee-006e9f05c868',
    '2cad9283-dc98-49fb-968d-54f1767bfec5','52d64e69-7083-4f76-8f8c-8e5dc91f6fbc',
    'dd2aa6d6-8dde-4850-87b4-3c82aa8993b1','d50d66d9-96a6-4279-b501-4374c0095ba2',
    '530f3c45-dfa7-43f5-a4e3-6a53adef370f','f9308d50-f40e-4728-b2d2-3a697433258a',
    '3716f46d-b588-4f15-86e0-db8def5871ee','b141f956-436d-42ce-8f5a-80e5f3196ef4',
    '7f7614ef-8e07-4d49-ba49-404730ef85ff','34b7d537-34f4-43e0-98ef-6a83d34bdc09',
    '2e5c71a8-46b7-422d-bb64-6577ba4bc0c8','b2141339-4c5e-4735-ad95-02544923e19f',
    '7c7d931b-5f2d-40c3-a257-c5bdda25acde','30b73b43-9aeb-488c-a909-bfa8c8b23c35',
    '5da99929-e34d-40cd-97b0-10608923b675','a575330a-da5b-455a-9eba-5bbab9e8091c',
    'aa4b57de-7cac-43ea-aa89-22402bef503a'"""
SOURCE_SETS = "'53aa8e89-d013-4040-ad3a-4892206b66ec','3a047a1c-f436-4623-aead-3a104cc1099b'"

COLUMNS = """cc.chunk_id, cc.accession_number, cc.form, cc.filing_date, cc.reporting_period_end,
       cc.cik, cc.company_name, cc.ticker, cc.chunk_index, ch.section_id, rs.section_type, rs.original_title,
       cc.chunking_version, cc.extraction_version, cc.source_url, cc.sha256, cc.offset_start, cc.offset_end,
       sel.processing_set_id, sel.set_key, cc.filing_id, cc.report_id, cc.text"""


def sel_cte(legacy_from):
    if legacy_from == "processing_sets":
        legacy = f"""SELECT p.id AS processing_set_id, p.set_key, p.report_id, p.chunking_version
  FROM sec.filing_processing_sets p WHERE p.id IN ({LEGACY_SETS})"""
    else:  # fallback for read-only accounts without access to sec.filing_processing_sets
        legacy = f"""SELECT DISTINCT p.processing_set_id, p.set_key, p.report_id, p.chunking_version
  FROM sec.chunk_catalog p WHERE p.processing_set_id IN ({LEGACY_SETS})"""
    return f"""WITH sel AS (
  {legacy}
  UNION ALL
  SELECT rc.processing_set_id, rc.set_key, rc.report_id, rc.chunking_version
  FROM sec.source_report_catalog rc
  WHERE rc.is_primary AND rc.processing_set_id IN ({SOURCE_SETS})
)"""


def export_sql(legacy_from):
    return f"""{sel_cte(legacy_from)}
SELECT {COLUMNS}
FROM sel
JOIN sec.chunk_citations cc ON cc.report_id = sel.report_id AND cc.chunking_version = sel.chunking_version
JOIN sec.chunks ch ON ch.id = cc.chunk_id
LEFT JOIN sec.report_sections rs ON rs.id = ch.section_id
ORDER BY cc.ticker, cc.filing_date, cc.chunk_index"""


def count_sql(legacy_from):
    return f"""{sel_cte(legacy_from)}
SELECT cc.ticker, cc.form, cc.accession_number, count(*) AS chunks
FROM sel
JOIN sec.chunk_citations cc ON cc.report_id = sel.report_id AND cc.chunking_version = sel.chunking_version
GROUP BY 1, 2, 3 ORDER BY 1, 2"""


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2).strip("'\"")


def connect():
    try:
        import psycopg2
    except ImportError:
        sys.exit("psycopg2 is missing: pip install psycopg2-binary")
    load_env()
    missing = [k for k in ("RDS_HOST", "RDS_USER", "RDS_PASSWORD") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Set {', '.join(missing)} (environment or .env), see the docstring.")
    cert = os.environ.get("RDS_SSLROOTCERT")
    return psycopg2.connect(
        host=os.environ["RDS_HOST"], port=int(os.environ.get("RDS_PORT", 5432)),
        dbname=os.environ.get("RDS_DB", "sec_filings"),
        user=os.environ["RDS_USER"], password=os.environ["RDS_PASSWORD"],
        sslmode="verify-full" if cert else "require", sslrootcert=cert, connect_timeout=20)


def run(conn, make_sql, handle):
    """Run with the processing-sets query; on permission denied, retry with the chunk_catalog fallback."""
    from psycopg2 import errors
    for legacy_from in ("processing_sets", "chunk_catalog"):
        try:
            with conn.cursor(name=f"round1_{legacy_from}") as cur:  # server-side cursor: streams rows
                cur.itersize = 2000
                cur.execute(make_sql(legacy_from))
                return handle(cur, legacy_from)
        except (errors.InsufficientPrivilege, errors.UndefinedTable) as e:
            conn.rollback()
            if legacy_from == "chunk_catalog":
                raise
            print(f"[info] {e.pgerror.strip().splitlines()[0]} -> using the chunk_catalog fallback")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "exports" / "round1_21.csv"))
    ap.add_argument("--check-only", action="store_true", help="print chunk counts per filing, write nothing")
    ap.add_argument("--drop-ntap-10q", action="store_true",
                    help="leave out NTAP 10-Q (review_required) if Data does not clear it; "
                         "also delete its row from eval/round1_filings.csv")
    a = ap.parse_args()
    conn = connect()
    conn.set_session(readonly=True)

    if a.check_only:
        def show(cur, src):
            rows = list(cur)
            for t, f, acc, n in rows:
                print(f"{t:5} {f:5} {acc}  chunks={n}")
            print(f"\n{len(rows)} filings (expect 21), {sum(r[3] for r in rows)} chunks, via {src}")
        run(conn, count_sql, show)
        return

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def write(cur, src):
        per, n = Counter(), 0
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = None
            for row in cur:
                if w is None:
                    w = csv.writer(fh)
                    w.writerow([d[0] for d in cur.description])
                    ps_idx = [d[0] for d in cur.description].index("processing_set_id")
                    tk_idx = [d[0] for d in cur.description].index("ticker")
                    fm_idx = [d[0] for d in cur.description].index("form")
                    ac_idx = [d[0] for d in cur.description].index("accession_number")
                if a.drop_ntap_10q and str(row[ps_idx]) == NTAP_10Q_SET:
                    continue
                w.writerow(["" if v is None else v for v in row])
                per[(row[tk_idx], row[fm_idx], row[ac_idx])] += 1
                n += 1
        print(f"Wrote {n} chunks from {len(per)} filings (expect {20 if a.drop_ntap_10q else 21}) to {out} (via {src})")
        for (t, f, acc), k in sorted(per.items()):
            print(f"  {t:5} {f:5} {acc}  chunks={k}")
        print("Next: PY=.venv/bin/python bash scripts/build_round1.sh " + os.path.relpath(out, ROOT))

    run(conn, export_sql, write)
    conn.close()


if __name__ == "__main__":
    main()
