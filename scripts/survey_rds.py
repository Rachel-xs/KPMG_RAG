"""Read-only survey of Data's RDS: which filings and which XBRL facts exist (for the objective question generator).

    python scripts/survey_rds.py                 # prints a report and writes exports/rds_survey.json

Uses the same .env / read-only account as scripts/export_round1_rds.py. Runs only SELECTs on information_schema and
small GROUP BY counts; every query is wrapped so a permission error on one table does not stop the survey.

Reports
  1. every schema / table the account can read, with an estimated row count
  2. tables that look like XBRL fact tables (columns like concept / tag, value, period / start / end / instant, unit)
     and, for each, the distinct concepts, companies, periods and a few sample rows
  3. filings in the chunk tables: ticker x form x period end, with chunk counts
Nothing is written to the database.
"""
from __future__ import annotations

import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import connect  # noqa: E402

FACT_HINTS = {"concept", "tag", "xbrl_tag", "element", "metric", "line_item", "us_gaap"}
VALUE_HINTS = {"value", "val", "amount", "numeric_value", "value_num"}
PERIOD_HINTS = {"period_end", "end_date", "period_start", "start_date", "instant", "fy", "fiscal_year", "fp",
                "fiscal_period", "frame", "period"}


def q(conn, sql, args=None, limit_note=""):
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            return cols, cur.fetchall()
    except Exception as e:  # noqa: BLE001 - keep surveying
        conn.rollback()
        return None, f"{type(e).__name__}: {str(e).strip().splitlines()[0]}"


def main():
    conn = connect()
    conn.set_session(readonly=True, autocommit=True)
    out = {"tables": [], "fact_tables": [], "filings": None}

    cols, rows = q(conn, """
        SELECT c.table_schema, c.table_name, string_agg(c.column_name || ':' || c.data_type, ', ' ORDER BY c.ordinal_position)
        FROM information_schema.columns c
        WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
        GROUP BY 1, 2 ORDER BY 1, 2""")
    if cols is None:
        sys.exit(f"cannot read information_schema: {rows}")
    est = {}
    c2, r2 = q(conn, """SELECT n.nspname, c.relname, c.reltuples::bigint FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','v','m','p')""")
    if c2:
        est = {(a, b): n for a, b, n in r2}
    print("== 1. Readable tables ==")
    for schema, table, colspec in rows:
        names = {x.split(":")[0].lower() for x in colspec.split(", ")}
        n = est.get((schema, table))
        out["tables"].append({"schema": schema, "table": table, "est_rows": n, "columns": colspec})
        print(f"{schema}.{table:40} ~{n if n is not None else '?':>10} rows | {colspec[:160]}")
        if names & FACT_HINTS and names & VALUE_HINTS:
            out["fact_tables"].append({"schema": schema, "table": table, "columns": sorted(names)})

    print("\n== 2. Tables that look like XBRL facts ==")
    for ft in out["fact_tables"]:
        fq = f'{ft["schema"]}."{ft["table"]}"'
        names = set(ft["columns"])
        concept = next(c for c in ("concept", "tag", "xbrl_tag", "element", "metric", "line_item", "us_gaap") if c in names)
        who = next((c for c in ("ticker", "cik", "company", "company_name", "entity") if c in names), None)
        pend = next((c for c in ("period_end", "end_date", "instant", "period") if c in names), None)
        info = {"table": fq, "concept_col": concept, "company_col": who, "period_col": pend}
        c, r = q(conn, f"SELECT count(*), count(DISTINCT {concept}) FROM {fq}")
        info["rows_and_concepts"] = r if isinstance(r, str) else list(r[0])
        if who:
            c, r = q(conn, f"SELECT {who}, count(*), count(DISTINCT {concept}) FROM {fq} GROUP BY 1 ORDER BY 2 DESC LIMIT 40")
            info["by_company"] = r if isinstance(r, str) else [list(x) for x in r]
        if pend:
            c, r = q(conn, f"SELECT min({pend})::text, max({pend})::text, count(DISTINCT {pend}) FROM {fq}")
            info["period_range"] = r if isinstance(r, str) else list(r[0])
        c, r = q(conn, f"SELECT {concept}, count(*) FROM {fq} GROUP BY 1 ORDER BY 2 DESC LIMIT 25")
        info["top_concepts"] = r if isinstance(r, str) else [list(x) for x in r]
        c, r = q(conn, f"SELECT * FROM {fq} LIMIT 3")
        info["sample"] = r if isinstance(r, str) else [dict(zip(c, map(str, x))) for x in r]
        out["fact_tables"][out["fact_tables"].index(ft)] = {**ft, **info}
        print(json.dumps(info, indent=1, default=str)[:2500])

    print("\n== 3. Filings with chunks ==")
    c, r = q(conn, """SELECT ticker, form, reporting_period_end::text, count(DISTINCT accession_number), count(*)
                      FROM sec.chunk_citations GROUP BY 1, 2, 3 ORDER BY 1, 3, 2""")
    if isinstance(r, str):
        print("sec.chunk_citations:", r)
    else:
        out["filings"] = [list(x) for x in r]
        tick = sorted({x[0] for x in r if x[0]})
        print(f"{len(r)} ticker x form x period rows, {len(tick)} tickers: {', '.join(tick)}")
        for x in r:
            print(f"  {x[0] or '?':6} {x[1]:5} {x[2]}  filings={x[3]}  chunk rows={x[4]}")

    p = ROOT / "exports" / "rds_survey.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nWrote {p}  (send this file to Claude)")


if __name__ == "__main__":
    main()
