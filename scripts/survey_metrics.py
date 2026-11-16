"""Read-only survey, part 2: Data's normalised metrics (finance.metric_value) and table-cell <-> fact links.

    python scripts/survey_metrics.py            # prints a report, writes exports/rds_metrics_survey.json

Answers, for the objective question generator and for cell citations:
  1. which metrics Data defines (finance.metric_definition): key, statement, period kind, definition
  2. metric_value coverage: rows by validation_status / status, by ticker x statement x period kind, period range
  3. for the 20 frozen Round 1 filings: metric_value rows, facts, table cells and cell <-> fact links
  4. three sample rows of finance.metric_value, sec.table_cells and sec.cell_fact_links
Only SELECTs; nothing is written to the database.
"""
from __future__ import annotations

import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import connect  # noqa: E402
from survey_rds import q  # noqa: E402


def show(title, res, out, key):
    cols, rows = res
    print(f"\n== {title} ==")
    if cols is None:
        print("  ", rows)
        out[key] = rows
        return
    out[key] = [dict(zip(cols, map(str, r))) for r in rows]
    for r in rows[:80]:
        print("  " + " | ".join(str(x)[:90] for x in r))
    if len(rows) > 80:
        print(f"  ... {len(rows)} rows (all in the JSON)")


def main():
    conn = connect()
    conn.set_session(readonly=True, autocommit=True)
    out = {}
    frozen = [r["accession_number"].strip() for r in csv.DictReader(open(ROOT / "eval/round1_filings.csv"))]
    acc = ",".join("'" + a.replace("'", "") + "'" for a in frozen)

    show("1. metric definitions", q(conn, """SELECT metric_key, statement_type, period_kind, unit_kind, method,
            array_length(concepts, 1) AS n_concepts, left(definition, 140)
            FROM finance.metric_definition ORDER BY statement_type, metric_key"""), out, "definitions")
    show("2a. metric_value by validation_status / status", q(conn, """SELECT validation_status, status, count(*),
            count(DISTINCT ticker), count(DISTINCT accession_number)
            FROM finance.metric_value GROUP BY 1, 2 ORDER BY 3 DESC"""), out, "by_status")
    show("2b. metric_value by statement x period_kind", q(conn, """SELECT statement_type, period_kind, count(*),
            count(DISTINCT metric_key), count(DISTINCT ticker), min(period_end)::text, max(period_end)::text
            FROM finance.metric_value GROUP BY 1, 2 ORDER BY 1, 2"""), out, "by_statement")
    show("2c. metric_value per ticker (top 60)", q(conn, """SELECT ticker, count(*), count(DISTINCT metric_key),
            count(DISTINCT accession_number), count(DISTINCT period_end)
            FROM finance.metric_value GROUP BY 1 ORDER BY 2 DESC LIMIT 60"""), out, "by_ticker")
    show("2d. tickers with metric values", q(conn, """SELECT count(DISTINCT ticker), count(DISTINCT accession_number),
            count(*) FROM finance.metric_value"""), out, "totals")
    show("3a. Round 1 filings: metric values", q(conn, f"""SELECT ticker, form, accession_number, count(*),
            count(DISTINCT metric_key), count(*) FILTER (WHERE period_end = reporting_period_end) AS current_period
            FROM finance.metric_value WHERE accession_number IN ({acc}) GROUP BY 1, 2, 3 ORDER BY 1, 2"""), out, "round1_metrics")
    show("3b. Round 1 filings: facts, table cells, cell<->fact links", q(conn, f"""
            SELECT f.accession_number,
                   (SELECT count(*) FROM sec.financial_facts x WHERE x.filing_id = f.id) AS facts,
                   (SELECT count(*) FROM sec.table_cells c WHERE c.filing_id = f.id) AS cells,
                   (SELECT count(*) FROM sec.cell_fact_links l WHERE l.filing_id = f.id) AS links
            FROM sec.filings f WHERE f.accession_number IN ({acc}) ORDER BY 1"""), out, "round1_cells")
    show("4a. sample metric_value", q(conn, """SELECT ticker, form, accession_number, metric_key, statement_type,
            period_kind, period_start::text, period_end::text, value, status, validation_status, concept_names
            FROM finance.metric_value WHERE ticker = 'MSFT' ORDER BY period_end DESC LIMIT 5"""), out, "sample_metric")
    show("4b. sample table_cells", q(conn, """SELECT cell_key, row_index, column_index, kind, display_text, row_heading,
            column_headings, column_period, is_total FROM sec.table_cells WHERE kind IS NOT NULL LIMIT 5"""), out, "sample_cells")
    show("4c. sample cell_fact_links", q(conn, """SELECT link_method, reference_order, left(evidence::text, 200)
            FROM sec.cell_fact_links LIMIT 5"""), out, "sample_links")
    show("4d. link methods", q(conn, """SELECT link_method, count(*) FROM sec.cell_fact_links GROUP BY 1 ORDER BY 2 DESC"""),
         out, "link_methods")

    p = ROOT / "exports" / "rds_metrics_survey.json"
    p.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nWrote {p}")


if __name__ == "__main__":
    main()
