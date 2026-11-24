"""rag.tables on text shaped like Data's paragraph-v1 output (rows on their own lines, '|' cells,
empty layout cells, '$' and ')' in separate cells, header cells wrapped across lines, page noise)."""
from rag.tables import merge_cells, parse_section, render, split_table

INCOME = """ITEM 1. FINANCIAL STATEMENTS

INCOME STATEMENTS

(In millions, except per share amounts) (Unaudited) | | Three Months Ended

March 31, | | | | Nine Months Ended

March 31, | |

| | 2026 | | | 2025 | | | | 2026 | | | | 2025 | |

Revenue: | | | | | | | | | | | | | | | | |

Product | | $ | 15,089 | | | $ | 15,319 | | | $ | 47,462 | | | $ | 46,810 | |

Service and other | | | 67,797 | | | | 54,747 | | | | 194,370 | | | | 158,473 | |

Total revenue | | | 82,886 | | | | 70,066 | | | | 241,832 | | | | 205,283 | |

28

PART I

Item 1

Other income (expense), net | | | 942 | | | | (623 | ) | | | 7,253 | | | | (3,194 | ) |

Refer to accompanying notes.
"""

SUMMARY = """SUMMARY RESULTS OF OPERATIONS

(In millions, except percentages and per share amounts) | | Three Months Ended

March 31, | | | Percentage

Change | | | Nine Months Ended

March 31, | | | Percentage

Change | |

| | | 2026 | | | | 2025 | | | | | | | 2026 | | | 2025 | | | | | |

Revenue | | $ | 82,886 | | | $ | 70,066 | | | | 18% | | | $ | 241,832 | | | $ | 205,283 | | | | 18% | |

More Personal Computing revenue | | $ | 13,192 | | | $ | 13,371 | | | | (1 | )% | | $ | 41,198 | | | $ | 41,198 | | | | 0% | |
"""


def _tables(text):
    return [b["table"] for b in parse_section(text) if b["type"] == "table"]


def test_merge_cells_glues_currency_and_parentheses():
    assert merge_cells("Product | | $ | 15,089 | | | $ | 15,319 | |") == ["Product", "$15,089", "$15,319"]
    assert merge_cells("Other | | | 942 | | | | (623 | ) |") == ["Other", "942", "(623)"]
    assert merge_cells("X | | (1 | )% | |") == ["X", "(1)%"]


def test_income_statement_is_one_table_with_composed_columns():
    tabs = _tables(INCOME)
    assert len(tabs) == 1  # page number / "PART I" / "Item 1" lines do not break the table
    t = tabs[0]
    assert t.unit.startswith("(In millions")
    assert t.caption[-1] == "INCOME STATEMENTS"
    assert t.columns == ["Three Months Ended March 31, 2026", "Three Months Ended March 31, 2025",
                         "Nine Months Ended March 31, 2026", "Nine Months Ended March 31, 2025"]
    assert ("Total revenue", ["82,886", "70,066", "241,832", "205,283"]) in t.rows
    assert ("Other income (expense), net", ["942", "(623)", "7,253", "(3,194)"]) in t.rows
    md = render(t)
    assert "| Total revenue | 82,886 | 70,066 | 241,832 | 205,283 |" in md
    assert "| |" not in md.split("\n", 4)[-1].replace("|  |", "")  # no empty layout cells left in rows with data


def test_sentence_before_table_is_not_a_caption():
    text = "Refer to accompanying notes.\n\nBALANCE SHEETS\n\n(In millions) | | | |\n\n| March 31, 2026 | | June 30, 2025 | |\n\nInventories | | | 1,219 | | | 938 | |\n"
    t = _tables(text)[0]
    assert t.caption == ["BALANCE SHEETS"]
    assert t.columns == ["March 31, 2026", "June 30, 2025"]


def test_percentage_change_columns_align():
    t = _tables(SUMMARY)[0]
    assert t.columns == ["Three Months Ended March 31, 2026", "Three Months Ended March 31, 2025", "Percentage Change",
                         "Nine Months Ended March 31, 2026", "Nine Months Ended March 31, 2025", "Percentage Change"]
    assert ("More Personal Computing revenue", ["$13,192", "$13,371", "(1)%", "$41,198", "$41,198", "0%"]) in t.rows


def test_linear_render_names_the_period_of_every_value():
    t = _tables(INCOME)[0]
    lin = render(t, "linear")
    assert "Total revenue: Three Months Ended March 31, 2026 = 82,886; " in lin


def test_split_repeats_header_and_group_label():
    t = _tables(INCOME)[0]
    count = lambda s: len(s.split())  # crude token counter is enough for the test
    pieces = split_table(t, count, max_tokens=60)
    assert len(pieces) > 1
    for p in pieces:
        assert "INCOME STATEMENTS" in p and "(In millions" in p and "Nine Months Ended March 31, 2026" in p
    assert any("Revenue (cont.)" in p for p in pieces[1:])
    body = "\n".join(pieces)
    for v in ("82,886", "(623)", "194,370"):
        assert v in body


def test_compact_layout_rows_without_trailing_pipe():
    """Data's later extraction (e.g. MSFT 10-Q FY2025 Q3): rows do not end with "|", header cells wrap with a single
    newline, rows are separated by blank lines. Each row must stay a row, and the three- vs nine-month headers must
    land on the right columns (11/24: the old parser glued the whole table into one row)."""
    from rag.tables import parse_section, render
    text = ("INCOME STATEMENTS\n\n(In millions, except per share amounts) (Unaudited) | Three Months Ended\nMarch 31, | "
            "Nine Months Ended\nMarch 31,\n\n2025 | 2024 | 2025 | 2024\n\nRevenue:\n\nProduct | $ | 15,319 | $ | 17,080 | $ | "
            "46,810 | $ | 51,556\n\nService and other | 54,747 | 44,778 | 158,473 | 128,839\n\nTotal revenue | 70,066 | "
            "61,858 | 205,283 | 180,395\n\nCost of revenue:\n\nProduct | 3,037 | 4,339 | 10,187 | 13,834\n")
    tables = [b["table"] for b in parse_section(text) if b["type"] == "table"]
    assert len(tables) == 1
    md = render(tables[0])
    assert "| Total revenue | 70,066 | 61,858 | 205,283 | 180,395 |" in md
    assert "| Revenue: |" in md
    header = md.splitlines()[2]
    assert header.count("Three Months Ended March 31, 2025") == 1 and "Nine Months Ended March 31, 2025" in header
    assert not any(line.count("---") > 10 for line in md.splitlines())
