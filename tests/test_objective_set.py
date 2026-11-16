"""scripts/build_objective_set.py: templates, exclusions, de-duplication and stratified sampling."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_objective_set as B  # noqa: E402


def row(**kw):
    r = {"ticker": "MSFT", "company_name": "MICROSOFT CORP", "cik": "789019", "accession_number": "A1", "form": "10-Q",
         "filing_date": "2026-04-29", "reporting_period_end": "2026-03-31", "metric_key": "revenue",
         "statement_type": "income_statement", "period_kind": "duration", "period_start": "2026-01-01",
         "period_end": "2026-03-31", "duration_days": 90, "value": 82886e6, "fact_ids": ["f1"],
         "concept_names": ["RevenueFromContractWithCustomerExcludingAssessedTax"], "status": "reported",
         "validation_status": "passed", "cell_table_id": "t1", "cell_key": "r010c003", "display_text": "82,886",
         "row_heading": "Total revenue", "column_period": '{"start": "2026-01-01", "end": "2026-03-31"}'}
    r.update(kw)
    return r


def test_templates():
    assert B.question_text(row()) == ("What was Microsoft's total revenue for the three months ended March 31, 2026? "
                                      "Answer in USD millions.")
    assert B.question_text(row(metric_key="total_assets", period_kind="instant", period_start=None)) == \
        "What was Microsoft's total assets as of March 31, 2026? Answer in USD millions."
    assert "nine months ended" in B.question_text(row(duration_days=273, period_start="2025-07-01"))
    assert "fiscal year ended June 30, 2026" in B.question_text(row(duration_days=365, period_end="2026-06-30"))
    assert B.question_text(row(ticker="CASY", company_name="CASEYS GENERAL STORES INC")).startswith("What was Casey's ")
    assert B.company_name("DAL", "DELTA AIR LINES, INC.") == "Delta Air Lines"


def test_item_is_gold_format_and_sig_figs():
    it = B.to_item(row(), "OBJ-A-001", {"set": "A"})
    assert it["gold"]["value"] == 82886e6 and it["answer_type"] == "exact_numeric"
    assert it["gold"]["min_sig_figs"] == 5 and it["gold_cell"]["period_months"] == 3
    # Casey's prints in thousands: ask in USD thousands and require every printed digit (Eval rule d)
    casy = B.to_item(row(ticker="CASY", value=5_678_336_000, display_text="5,678,336"), "x", {})
    assert casy["answer_unit"] == "USD thousands" and casy["question"].endswith("Answer in USD thousands.")
    assert casy["gold"]["min_sig_figs"] == 7 and casy["answer"]["display"] == "USD 5,678,336 thousand"
    # trailing zeros of a whole number do not count, the grader's way
    assert B.to_item(row(value=1_200e6, display_text="1,200"), "z", {})["gold"]["min_sig_figs"] == 2
    assert B.printed_sig_figs("(0.50)") == 2 and B.printed_scale(row(value=1_200e6, display_text="1,200")) == 1e6
    eps = B.to_item(row(metric_key="eps_diluted", value=4.27, display_text="4.27"), "y", {})
    assert eps["gold"]["min_sig_figs"] == 3 and eps["answer"]["unit"] == "USD/shares"


def test_exclusions_and_dedup():
    rows = [row(), row(value=0), row(cell_key=None), row(status="conflict"),
            row(accession_number="A2", reporting_period_end="2026-06-30", filing_date="2026-07-30", form="10-K")]
    pool, excl = B.population(rows, None, None, None)
    assert excl["1_zero_or_nil"] == 1 and excl["2_no_linked_cell"] == 1 and excl["4_conflict_or_review"] == 1
    assert excl["3_duplicate_period"] == 1 and len(pool) == 1 and pool[0]["accession_number"] == "A1"  # own-period filing wins


def test_sample_A_strata_and_determinism():
    rows = []
    for t in ("MSFT", "AAPL"):
        for i in range(40):
            st = ["income_statement", "balance_sheet", "cash_flow_statement"][i % 3]
            cur = i % 2 == 0
            rows.append(row(ticker=t, statement_type=st, metric_key=f"m{i}", period_end="2026-03-31" if cur else f"2025-{1 + i % 12:02d}-28"))
    a = B.sample_A(rows, random.Random(B.SEED))
    b = B.sample_A(rows, random.Random(B.SEED))
    assert [x[0]["metric_key"] for x in a] == [x[0]["metric_key"] for x in b]
    for t in ("MSFT", "AAPL"):
        mine = [x for x in a if x[0]["ticker"] == t]
        assert len(mine) == 15
        assert sum(x[1]["statement"] == "income_statement" for x in mine) == 6
        assert sum(x[1]["relation"] == "current" for x in mine) == 10


def test_rule_a_excludes_company_metric_period_used_by_a_question(tmp_path):
    import json
    q = {"qid": "D1", "facts": [{"ticker": "MSFT", "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                                 "period_end": "2026-03-31"}]}
    f = tmp_path / "dev.jsonl"
    f.write_text(json.dumps(q) + "\n")
    used = B.used_keys([str(f)])
    rows = [row(), row(metric_key="net_income", concept_names=["NetIncomeLoss"]), row(ticker="AAPL")]
    pool, excl = B.population(rows, None, None, None, used)
    assert excl["5_used_by_dev_or_holdout"] == 1 and {r["metric_key"] for r in pool} == {"net_income", "revenue"}
    assert {r["ticker"] for r in pool} == {"MSFT", "AAPL"}
