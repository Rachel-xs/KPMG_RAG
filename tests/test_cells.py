"""rag/cells.py: cell-level citations from table chunks (#2)."""
from datetime import date

from rag.cells import cite_answer, find_cells, parse_number, parse_table

IS = {"chunk_id": "T-C1-0010", "table_id": "T-t00", "ticker": "MSFT", "form": "10-Q", "accession": "A1",
      "is_table": True, "table_name": "INCOME STATEMENTS", "text": """ITEM 1. FINANCIAL STATEMENTS
INCOME STATEMENTS
(In millions, except per share amounts) (Unaudited)
|  | Three Months Ended March 31, 2026 | Three Months Ended March 31, 2025 | Nine Months Ended March 31, 2026 | Nine Months Ended March 31, 2025 |
| --- | --- | --- | --- | --- |
| Revenue: |  |  |  |  |
| Product | $15,089 | $15,319 | $47,462 | $46,810 |
| Service and other | 67,797 | 54,747 | 194,370 | 158,473 |
| Total revenue | 82,886 | 70,066 | 241,832 | 205,283 |
| Gross margin | 56,058 | 48,147 | 164,983 | 141,466 |
| Other income (expense), net | 942 | (623) | 7,253 | (3,194) |
| Diluted | $3.46 | $3.46 | $13.64 | $9.73 |"""}

CASY = {"chunk_id": "C-C1-0015", "table_id": "C-t02", "ticker": "CASY", "form": "10-Q", "accession": "A2",
        "is_table": True, "table_name": "Three Months Ended · July 31,", "text": """| Three Months Ended
July 31, |
|  | 2026 | 2025 |
| --- | --- | --- |
| Total revenue | $5,678,336 | $4,567,106 |
| Net income | $273,720 | $215,355 |"""}

MU_K = {"chunk_id": "M-C1-0112", "table_id": "M-t10", "ticker": "MU", "form": "10-K", "accession": "A3",
        "is_table": True, "table_name": "Results of Operations", "text": """Results of Operations
Columns: For the year ended | 2026 | 2025
|  |  |  |  |  |
| --- | --- | --- | --- | --- |
| Revenue | $133,188 | 100% | $37,378 | 100% |
| Operating income | 99,340 | 75% | 9,770 | 26% |"""}

MU_GARBLED = {"chunk_id": "M-C1-0020", "table_id": "M-t02", "ticker": "MU", "form": "10-Q", "accession": "A4",
              "is_table": True, "table_name": "", "text": """| May 28,
2026 | May 29,
Columns: 2025 | May 28, 2026 | May 29, 2025
|  |  |  |  |  |
| --- | --- | --- | --- | --- |
| Revenue | $41,456 | $9,301 | $78,959 | $26,063 |"""}


def test_parse_number():
    assert parse_number("$15,089") == (15089.0, False)
    assert parse_number("(623)") == (-623.0, False)
    assert parse_number("—") == (0.0, False)
    assert parse_number("12.5%") == (12.5, True)
    assert parse_number("Revenue")[0] is None


def test_columns_rows_and_keys():
    t = parse_table(IS)
    assert [(c.period_end, c.months) for c in t.columns] == [
        (date(2026, 3, 31), 3), (date(2025, 3, 31), 3), (date(2026, 3, 31), 9), (date(2025, 3, 31), 9)]
    cells = {c["cell_key"]: c for c in t.cells()}
    k = "T-t00|revenue > total revenue|3m@2026-03-31"
    assert cells[k]["value"] == 82_886e6 and cells[k]["row_path"] == ["Revenue", "Total revenue"]
    assert cells["T-t00|gross margin|9m@2026-03-31"]["value"] == 164_983e6   # "Total" closes the Revenue group
    assert cells["T-t00|other income expense net|3m@2025-03-31"]["value"] == -623e6
    assert cells["T-t00|diluted|3m@2026-03-31"]["value"] == 3.46            # per-share rows are not scaled


def test_find_cells_prefers_right_period():
    hits = find_cells([IS], 82_886e6, "2026-03-31", 3)
    assert hits[0]["period_match"] and hits[0]["column_header"].startswith("Three Months")
    assert not find_cells([IS], 82_886e6, "2026-03-31", 9)[0]["period_match"]   # value right, period wrong


def test_unit_inferred_when_chunk_has_no_unit_line():
    hits = find_cells([CASY], 5_678.336e6, "2026-07-31", 3)
    assert hits and hits[0]["period_match"] and hits[0]["unit_inferred"] and hits[0]["unit_scale"] == 1e3


def test_columns_line_with_percent_columns():
    t = parse_table(MU_K, fy_end=date(2026, 9, 3))
    assert [c.header for c in t.columns] == ["2026", "2026", "2025", "2025"]
    assert find_cells([MU_K], 133_188e6, "2026-09-03", 12, {"MU": date(2026, 9, 3)})[0]["period_match"]


def test_garbled_header_gets_no_period():
    t = parse_table(MU_GARBLED)
    assert all(c.period_end is None for c in t.columns)
    hits = find_cells([MU_GARBLED], 9_301e6, "2026-05-28", 3)
    assert hits and hits[0]["period_match"] is None                 # found, but never claimed as the right period


def test_dash_never_matches_small_values():
    t = {**CASY, "text": CASY["text"] + "\n| Other | — | — |"}
    assert not [h for h in find_cells([t], 256.33) if h["value_text"] == "—"]


def test_percent_matches_fraction():
    t = {**IS, "text": IS["text"] + "\n| Effective tax rate | 19% | 18% | 20% | 18% |"}
    assert find_cells([t], 0.2, "2026-03-31", 9)[0]["row_label"] == "Effective tax rate"


def test_cite_answer():
    b = cite_answer({"value": 82_886e6, "period_end": "2026-03-31"}, [IS], period_months=3)
    assert b["cell_citations"][0]["cell_key"].endswith("|3m@2026-03-31")
    b = cite_answer({"value": 0.183, "period_end": "2026-03-31"}, [IS], period_months=3, values=[82_886e6, 70_066e6])
    assert [c["value"] for c in b["cell_citations"]] == [82_886e6, 70_066e6]


SEG = {"chunk_id": "S-C1-0030", "table_id": "S-t05", "ticker": "MSFT", "form": "10-Q", "accession": "A1",
       "is_table": True, "table_name": "SUMMARY RESULTS OF OPERATIONS", "text": """SUMMARY RESULTS OF OPERATIONS
(In millions, except percentages and per share amounts)
|  | Three Months Ended March 31, 2026 | Three Months Ended March 31, 2025 | Percentage Change |
| --- | --- | --- | --- |
| Revenue | $82,886 | $70,066 | 18% |
| Net income | 31,778 | 25,824 | 23% |
| Diluted earnings per share | 4.27 | 3.46 | 23% |"""}


def test_change_column_takes_current_period():
    t = parse_table(SEG)
    assert t.columns[2].change and t.columns[2].period_end == date(2026, 3, 31) and t.columns[2].months == 3
    h = find_cells([SEG], 18, "2026-03-31", 3, kind="percent")[0]
    assert h["period_match"] and h["change_column"] and h["cell_key"].endswith("|chg3m@2026-03-31")


def test_kind_keeps_amounts_and_percents_apart():
    t = {**SEG, "text": SEG["text"] + "\n| Other | 1 | 2 | 60% |"}
    assert not find_cells([t], 0.60, kind="amount")                     # $0.60 must not hit "60%"
    assert find_cells([t], 0.60, kind="percent")[0]["value_text"] == "60%"
    assert find_cells([SEG], 4.27, "2026-03-31", 3, kind="amount")[0]["row_label"] == "Diluted earnings per share"
