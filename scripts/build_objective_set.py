"""Build the pre-registered objective question sets (docs/preregistration_objective_eval.md) from Data's XBRL metrics.

    python scripts/build_objective_set.py --set A      # 20 frozen Round 1 filings, 15 per company (150)
    python scripts/build_objective_set.py --set C      # companies outside the Round 1 ten, 1 per company (<= 100)
    python scripts/build_objective_set.py --set A --from-json exports/metric_rows.json   # offline, from a saved pull
    python scripts/build_objective_set.py --set A --seed <private number>                # holder picks the seed
    python scripts/build_objective_set.py --pull-only                  # save the metric rows for the holder; builds nothing
    python scripts/build_objective_set.py --set A --from-json rows.json --seed <n> --exclude-gold dev.jsonl --exclude-gold holdout.jsonl

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


def printed_number(display: str | None) -> float | None:
    """The number as printed in the linked cell ("(1,234.5)" -> 1234.5), or None."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", display or "")
    return float(m.group(0).replace(",", "")) if m else None


def printed_scale(r: dict) -> float | None:
    """The table's scale: value / printed number, snapped to 1, 1e3, 1e6 or 1e9 (None if it matches none)."""
    p = printed_number(r.get("display_text"))
    if not p:
        return None
    ratio = abs(float(r["value"])) / p
    for s in (1.0, 1e3, 1e6, 1e9):
        if abs(ratio / s - 1) < 0.01:
            return s
    return None


def printed_sig_figs(display: str | None) -> int | None:
    """Significant figures of the printed number, counted like Eval's grader (kpmg_eval.normalize.Quantity.sig_figs):
    leading zeros never count; trailing zeros of a whole number do not count ("1,200" -> 2)."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", display or "")
    if not m:
        return None
    s = m.group(0).replace(",", "")
    digits = s.replace(".", "").lstrip("0")
    if "." not in s:
        digits = digits.rstrip("0")
    return len(digits) or 1


def answer_unit(r: dict) -> tuple[str, float]:
    """(unit phrase for the question, divisor). Per-share stays per share; otherwise ask in the table's own scale
    (thousands for e.g. Casey's) so the printed digits are exactly what a correct answer writes."""
    if r["metric_key"] == "eps_diluted":
        return "USD per share", 1.0
    return ("USD thousands", 1e3) if printed_scale(r) == 1e3 else ("USD millions", 1e6)


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


ATTRIBUTABLE = {"net_income", "shareholders_equity"}  # lines a statement may print twice: consolidated and attributable


def question_text(r: dict) -> str:
    who = company_name(r["ticker"], r.get("company_name"))
    tail = f"{period_phrase(r)}? Answer in {answer_unit(r)[0]}."
    # Eval 11/27: when the gold cell is the "attributable to <company>" line, say so; "net income" alone also fits the
    # consolidated line printed above it (all 7 wrong values on sets B and C2 were that line). Sets A-C2 were built at
    # 6b7d53b, before this wording, and rebuild unchanged from that commit.
    if r["metric_key"] in ATTRIBUTABLE and "attributable" in (r.get("row_heading") or "").lower():
        return f"What was {LABEL[r['metric_key']]} attributable to {who} {tail}"
    poss = who if who.endswith("'s") else who + ("'" if who.endswith("s") else "'s")
    return f"What was {poss} {LABEL[r['metric_key']]} {tail}"


def to_item(r: dict, qid: str, stratum: dict) -> dict:
    eps = r["metric_key"] == "eps_diluted"
    value = float(r["value"])
    unit_phrase, div = answer_unit(r)
    # precision floor = the digits printed in the linked cell (Eval 11/16, rule d), counted the grader's way; if the
    # table's scale is not the one the question asks for (should not happen after answer_unit), never demand more
    # digits than the asked unit's integer part carries
    sf = printed_sig_figs(r.get("display_text")) or sig_figs(r.get("display_text"))
    if not eps and printed_scale(r) != div:
        sf = min(sf, len(str(int(round(abs(value) / div)))) or 2)
    sf = max(1, sf)
    m = months(r.get("duration_days"))
    if eps:
        disp = f"USD {value:,.2f} per share"
    else:
        word = "thousand" if div == 1e3 else "million"
        disp = f"USD {value / div:,.{0 if abs(value) / div >= 1000 else 1}f} {word}"
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
        "answer_unit": unit_phrase, "printed_scale": printed_scale(r),
    }


def used_keys(gold_files: list[str]) -> set[tuple]:
    """(ticker, concept, period_end) of every XBRL fact a dev or holdout question uses (Eval 11/16, rule a: leave out
    any company x metric x period a question already asks about). Concepts compare without their prefix."""
    keys = set()
    for path in gold_files or []:
        for q in map(json.loads, open(path, encoding="utf-8")):
            for f in (q.get("facts") or []) + ((q.get("gold") or {}).get("evidence") or []):
                if f.get("ticker") and f.get("concept") and f.get("period_end"):
                    keys.add((f["ticker"].upper(), f["concept"].split(":")[-1], str(f["period_end"])[:10]))
    return keys


def is_used(r: dict, used: set[tuple]) -> bool:
    concepts = r.get("concept_names") or []
    return any((r["ticker"].upper(), c.split(":")[-1], str(r["period_end"])[:10]) in used for c in concepts)


def population(rows: list[dict], scope_accessions: set | None, scope_tickers: set | None, exclude_tickers: set | None,
               used: set[tuple] | None = None):
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
        elif used and is_used(r, used):
            excl["5_used_by_dev_or_holdout"] += 1
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
    ap.add_argument("--set", choices=["A", "C"])
    ap.add_argument("--pull-only", action="store_true",
                    help="query the database, save the rows to --save-pull and stop (no questions are built)")
    ap.add_argument("--exclude-gold", action="append", default=[],
                    help="question file(s) whose company x metric x period must not be drawn (dev, holdout); repeatable")
    ap.add_argument("--from-json", default=None, help="use a saved pull instead of querying the database")
    ap.add_argument("--save-pull", default="exports/metric_rows.json")
    ap.add_argument("--out", default="eval/objective")
    ap.add_argument("--seed", type=int, default=SEED,
                    help="sampling seed; whoever holds the set picks it and keeps it private (only a hash is logged)")
    a = ap.parse_args()

    if not a.pull_only and not a.set:
        ap.error("--set is required unless --pull-only")
    if a.from_json:
        rows = json.loads(Path(ROOT / a.from_json).read_text())
    else:
        rows = fetch_rows()
        p = ROOT / a.save_pull
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(rows, default=str))
        import hashlib
        print(f"pulled {len(rows)} metric rows -> {p} (sha256 {hashlib.sha256(p.read_bytes()).hexdigest()[:16]})")
        if a.pull_only:
            print("--pull-only: no questions built. Send this file privately to the set holder.")
            return
    for r in rows:
        if isinstance(r.get("concept_names"), str):
            r["concept_names"] = r["concept_names"].strip("{}").split(",")

    used = used_keys(a.exclude_gold)
    rng = random.Random(a.seed)
    if a.set == "A":
        frozen = {r["accession_number"].strip() for r in csv.DictReader(open(ROOT / "eval/round1_filings.csv"))
                  if r.get("validation_status", "passed") == "passed"}
        pool, excl = population(rows, frozen, set(CORE), None, used)
        picked = sample_A(pool, rng)
    else:
        pool, excl = population(rows, None, None, set(CORE), used)
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
                "excluded_question_files": [Path(x).name for x in a.exclude_gold], "n_used_keys": len(used),
                "by_answer_unit": dict(Counter(it["answer_unit"] for it in items)),
                "by_company": dict(Counter(it["tickers"][0] for it in items)),
                "by_statement": dict(Counter(it["strata"]["statement"] for it in items)),
                "by_relation": dict(Counter(it["strata"]["relation"] for it in items)),
                "by_metric": dict(Counter(it["metric_key"] for it in items))}
    (out / f"set_{a.set}_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))
    print(f"\nWrote {out}/set_{a.set}.jsonl. Do not open the questions before the run (pre-registration).")


if __name__ == "__main__":
    main()
