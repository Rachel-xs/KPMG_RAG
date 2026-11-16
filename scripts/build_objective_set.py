"""Build the pre-registered objective question sets (docs/preregistration_objective_eval.md) from Data's XBRL metrics.

    python scripts/build_objective_set.py --set A      # 20 frozen Round 1 filings, 15 per company (150)
    python scripts/build_objective_set.py --set C      # companies outside the Round 1 ten, 1 per company (<= 100)
    python scripts/build_objective_set.py --set A --from-json exports/metric_rows.json   # offline, from a saved pull
    python scripts/build_objective_set.py --set A --seed <private number>                # holder picks the seed

Source: finance.metric_value (validation passed, status reported) joined to the table cell Data links to the fact.
Output: eval/objective/<set>.jsonl in the Gold Set v2 format (Eval's grader scores it unchanged) plus
eval/objective/<set>_manifest.json (population, exclusions per rule, strata counts, seed, git commit).
Nothing here looks at RAG's chunks or retrieval: questions come from a fixed template per metric and period.
"""
from __future__ import annotations

import argparse, csv, json, random, re, subprocess, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261116
CORE = ["AAPL", "CASY", "MCK", "MDT", "MSFT", "MU", "NKE", "NTAP", "PH", "TTWO"]
PER_COMPANY_A = {"income_statement": 6, "balance_sheet": 5, "cash_flow_statement": 4}  # 15 per company
CURRENT_SHARE = 2 / 3

LABEL = {  # plain metric names, independent of any filing's wording
    "revenue": "total revenue",
    "cost_of_revenue": "total cost of revenue",
    "operating_income": "operating income",
    "net_income": "net income",
    "eps_diluted": "diluted earnings per share",
    "cash_and_equivalents": "cash and cash equivalents",
    "long_term_debt_current": "current portion of long-term debt",
    "long_term_debt_noncurrent": "long-term debt, excluding the current portion",
    "shareholders_equity": "total shareholders' equity",
    "short_term_borrowings": "short-term borrowings",
    "total_assets": "total assets",
    "total_liabilities": "total liabilities",
    "capital_expenditures": "capital expenditures (cash paid for property, plant and equipment)",
    "dividends_paid": "cash dividends paid",
    "operating_cash_flow": "net cash provided by (used in) operating activities",
}
COMPANY = {"AAPL": "Apple", "CASY": "Casey's", "MCK": "McKesson", "MDT": "Medtronic", "MSFT": "Microsoft",
           "MU": "Micron", "NKE": "Nike", "NTAP": "NetApp", "PH": "Parker-Hannifin", "TTWO": "Take-Two"}
_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|plc|ltd|limited|n\.?v|s\.?a)\.?$", re.I)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]

SQL = """
SELECT mv.ticker, mv.company_name, mv.cik, mv.accession_number, mv.form, mv.filing_date::text AS filing_date,
       mv.reporting_period_end::text AS reporting_period_end, mv.metric_key, mv.statement_type, mv.period_kind,
       mv.period_start::text AS period_start, mv.period_end::text AS period_end, mv.duration_days,
       mv.value::float8 AS value, mv.fact_ids::text[] AS fact_ids, mv.concept_names, mv.status, mv.validation_status,
       c.table_id::text AS cell_table_id, c.cell_key, c.display_text, c.row_heading, c.column_period::text AS column_period
FROM finance.metric_value mv
LEFT JOIN LATERAL (
    SELECT tc.table_id, tc.cell_key, tc.display_text, tc.row_heading, tc.column_period
    FROM sec.cell_fact_links l JOIN sec.table_cells tc ON tc.id = l.cell_id
    WHERE l.fact_id = mv.fact_ids[1] ORDER BY l.reference_order LIMIT 1) c ON true
WHERE mv.validation_status = 'passed' AND mv.status IN ('reported', 'conflict', 'review_required')
"""


def company_name(ticker: str, raw: str | None) -> str:
    if ticker in COMPANY:
        return COMPANY[ticker]
    n = (raw or ticker).strip()
    for _ in range(2):
        n = _SUFFIX.sub("", n).strip(" ,.")
    if n.isupper():
        # keep acronyms (no vowel, e.g. CVS; or two letters) in capitals, title-case the rest
        n = " ".join(w if (w.isalpha() and (len(w) <= 2 or not re.search(r"[AEIOUY]", w))) else w.capitalize()
                     for w in n.split())
    return n


def fmt_date(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def months(duration_days) -> int | None:
    if not duration_days:
        return None
    return {3: 3, 6: 6, 9: 9, 12: 12}.get(round(int(duration_days) / 30.44))


def period_phrase(r: dict) -> str | None:
    if r["period_kind"] == "instant":
        return f"as of {fmt_date(r['period_end'])}"
    m = months(r.get("duration_days"))
    if m is None:
        return None
    if m == 12:
        return f"for the fiscal year ended {fmt_date(r['period_end'])}"
    return f"for the {['', '', '', 'three', '', '', 'six', '', '', 'nine'][m]} months ended {fmt_date(r['period_end'])}"


def sig_figs(display: str | None) -> int:
    digits = re.sub(r"[^\d]", "", (display or "").split(".")[0]) + re.sub(r"[^\d]", "", (display or "").split(".", 1)[1] if "." in (display or "") else "")
    return max(2, len(digits.lstrip("0")) or 3)


def question_text(r: dict) -> str:
    who = company_name(r["ticker"], r.get("company_name"))
    poss = who if who.endswith("'s") else who + ("'" if who.endswith("s") else "'s")
    unit = "Answer in USD per share." if r["metric_key"] == "eps_diluted" else "Answer in USD millions."
    return f"What was {poss} {LABEL[r['metric_key']]} {period_phrase(r)}? {unit}"


def to_item(r: dict, qid: str, stratum: dict) -> dict:
    eps = r["metric_key"] == "eps_diluted"
    value = float(r["value"])
    sf = sig_figs(r.get("display_text"))
    if not eps:  # the question asks for USD millions: never demand more digits than the integer millions carry
        sf = max(2, min(sf, len(str(int(round(abs(value) / 1e6)))) or 2))
    m = months(r.get("duration_days"))
    disp = f"USD {value:,.2f} per share" if eps else f"USD {value / 1e6:,.{0 if abs(value) >= 1e9 else 1}f} million"
    fact = {"cik": r.get("cik"), "accession": r["accession_number"], "concept": "us-gaap:" + (r.get("concept_names") or ["?"])[0],
            "period_start": r.get("period_start"), "period_end": r["period_end"],
            "unit": "USD/shares" if eps else "USD", "ticker": r["ticker"], "level": "FACT"}
    return {
        "qid": qid, "source": "objective_xbrl_v1", "type": "extraction", "tier": "basic", "answerable": True,
        "question": question_text(r), "tickers": [r["ticker"]],
        "filters": {"ticker": r["ticker"], "form": r["form"], "reporting_period_end": r["reporting_period_end"]},
        "answer_type": "exact_numeric",
        "answer": {"kind": "money", "value": value, "unit": fact["unit"], "display": disp,
                   "required_points": [r.get("display_text") or disp], "min_sig_figs": sf},
        "gold": {"value": value, "kind": "money", "min_sig_figs": sf, "evidence": [fact], "distractors": []},
        "facts": [fact],
        "fact_values": {f"{r['ticker']}|{r['metric_key']}|{r.get('period_start') or ''}|{r['period_end']}": value},
        "gold_cell": {"table_id": r.get("cell_table_id"), "cell_key": r.get("cell_key"), "display_text": r.get("display_text"),
                      "row_heading": r.get("row_heading"), "column_period": r.get("column_period"),
                      "period_months": 0 if r["period_kind"] == "instant" else m},
        "metric_key": r["metric_key"], "strata": stratum, "rag_evidence": [], "status": "auto_xbrl",
    }


def population(rows: list[dict], scope_accessions: set | None, scope_tickers: set | None, exclude_tickers: set | None):
    """Apply the pre-registered exclusions; return (kept rows, exclusion counts)."""
    excl = Counter()
    pool = []
    for r in rows:
        if scope_accessions is not None and r["accession_number"] not in scope_accessions:
            continue
        if scope_tickers is not None and r["ticker"] not in scope_tickers:
            continue
        if exclude_tickers and r["ticker"] in exclude_tickers:
            continue
        if not r.get("ticker"):
            excl["no_ticker"] += 1
        elif r["status"] in ("conflict", "review_required"):
            excl["4_conflict_or_review"] += 1
        elif r.get("value") in (None, 0) or float(r["value"]) == 0:
            excl["1_zero_or_nil"] += 1
        elif not r.get("cell_key"):
            excl["2_no_linked_cell"] += 1
        elif r["metric_key"] not in LABEL or period_phrase(r) is None:
            excl["unsupported_metric_or_period"] += 1
        else:
            pool.append(r)
    # 3. one row per (company, metric, period): the filing whose own period is this one, else the latest filing
    best = {}
    for r in pool:
        k = (r["ticker"], r["metric_key"], r.get("period_start"), r["period_end"])
        cur = r["period_end"] == r["reporting_period_end"]
        rank = (cur, r.get("filing_date") or "")
        if k not in best or rank > best[k][0]:
            if k in best:
                excl["3_duplicate_period"] += 1
            best[k] = (rank, r)
        else:
            excl["3_duplicate_period"] += 1
    return [v[1] for v in best.values()], excl


def sample_A(pool: list[dict], rng: random.Random) -> list[tuple[dict, dict]]:
    out = []
    by_t = defaultdict(list)
    for r in pool:
        by_t[r["ticker"]].append(r)
    for t in sorted(by_t):
        rows = by_t[t]
        want = dict(PER_COMPANY_A)
        picked = []
        for st, n in want.items():
            cand = [r for r in rows if r["statement_type"] == st]
            cur = [r for r in cand if r["period_end"] == r["reporting_period_end"]]
            pri = [r for r in cand if r["period_end"] != r["reporting_period_end"]]
            rng.shuffle(cur), rng.shuffle(pri)
            n_cur = round(n * CURRENT_SHARE)
            take = cur[:n_cur] + pri[:n - n_cur]
            if len(take) < n:  # short stratum: fill from the rest of this statement
                rest = [r for r in cur[n_cur:] + pri[n - n_cur:] if r not in take]
                take += rest[:n - len(take)]
            picked += take
        total = sum(want.values())
        if len(picked) < total:  # fill from the company's largest remaining statement
            rest = [r for r in rows if r not in picked]
            rng.shuffle(rest)
            picked += rest[:total - len(picked)]
        out += [(r, {"set": "A", "statement": r["statement_type"],
                     "relation": "current" if r["period_end"] == r["reporting_period_end"] else "prior"}) for r in picked]
    return out


def sample_C(pool: list[dict], rng: random.Random, n_companies: int = 100) -> list[tuple[dict, dict]]:
    by_t = defaultdict(list)
    for r in pool:
        by_t[r["ticker"]].append(r)
    tickers = sorted(by_t)
    rng.shuffle(tickers)
    out = []
    for t in sorted(tickers[:n_companies]):
        cur = [r for r in by_t[t] if r["period_end"] == r["reporting_period_end"]] or by_t[t]
        r = rng.choice(sorted(cur, key=lambda x: (x["metric_key"], x["period_end"], x["accession_number"])))
        out.append((r, {"set": "C", "statement": r["statement_type"],
                        "relation": "current" if r["period_end"] == r["reporting_period_end"] else "prior"}))
    return out


def fetch_rows() -> list[dict]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from export_round1_rds import connect
    conn = connect()
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute(SQL)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, x)) for x in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["A", "C"], required=True)
    ap.add_argument("--from-json", default=None, help="use a saved pull instead of querying the database")
    ap.add_argument("--save-pull", default="exports/metric_rows.json")
    ap.add_argument("--out", default="eval/objective")
    ap.add_argument("--seed", type=int, default=SEED,
                    help="sampling seed; whoever holds the set picks it and keeps it private (only a hash is logged)")
    a = ap.parse_args()

    if a.from_json:
        rows = json.loads(Path(ROOT / a.from_json).read_text())
    else:
        rows = fetch_rows()
        p = ROOT / a.save_pull
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(rows, default=str))
        print(f"pulled {len(rows)} metric rows -> {p}")
    for r in rows:
        if isinstance(r.get("concept_names"), str):
            r["concept_names"] = r["concept_names"].strip("{}").split(",")

    rng = random.Random(a.seed)
    if a.set == "A":
        frozen = {r["accession_number"].strip() for r in csv.DictReader(open(ROOT / "eval/round1_filings.csv"))
                  if r.get("validation_status", "passed") == "passed"}
        pool, excl = population(rows, frozen, set(CORE), None)
        picked = sample_A(pool, rng)
    else:
        pool, excl = population(rows, None, None, set(CORE))
        picked = sample_C(pool, rng)

    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    items = [to_item(r, f"OBJ-{a.set}-{i:03d}", s) for i, (r, s) in enumerate(picked, 1)]
    with open(out / f"set_{a.set}.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None
    import hashlib
    manifest = {"set": a.set, "seed_sha256": hashlib.sha256(str(a.seed).encode()).hexdigest()[:16],
                "seed_is_default": a.seed == SEED, "git_commit": commit, "rows_pulled": len(rows),
                "population_after_exclusions": len(pool), "exclusions": dict(excl), "n_questions": len(items),
                "by_company": dict(Counter(it["tickers"][0] for it in items)),
                "by_statement": dict(Counter(it["strata"]["statement"] for it in items)),
                "by_relation": dict(Counter(it["strata"]["relation"] for it in items)),
                "by_metric": dict(Counter(it["metric_key"] for it in items))}
    (out / f"set_{a.set}_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))
    print(f"\nWrote {out}/set_{a.set}.jsonl. Do not open the questions before the run (pre-registration).")


if __name__ == "__main__":
    main()
