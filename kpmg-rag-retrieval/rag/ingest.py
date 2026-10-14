"""Download the most recent 10-K / 10-Q filings for a list of tickers from SEC EDGAR.

Uses only official public endpoints:
  * https://www.sec.gov/files/company_tickers.json        (ticker -> CIK)
  * https://data.sec.gov/submissions/CIK##########.json   (filing index per company)
  * https://www.sec.gov/Archives/edgar/data/...            (the filing's primary document)

SEC fair-access rules: <= 10 requests/second and a descriptive User-Agent with contact info.
Downloads are cached: a filing already on disk is not fetched again.

Temporary pilot tool — once the Data Engineering team's pipeline exists, point
`rag.chunk` at their output instead (same manifest fields).
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"


class EdgarClient:
    def __init__(self, user_agent: str, min_interval: float = 0.15):
        if not user_agent or "your_email" in user_agent:
            raise ValueError(
                "Set a real SEC User-Agent (name + email) in config.yaml or SEC_USER_AGENT in .env"
            )
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.min_interval = min_interval
        self._last = 0.0

    def get(self, url: str) -> requests.Response:
        for attempt in range(4):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self.session.get(url, timeout=60)
            self._last = time.time()
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp


def ticker_to_cik(client: EdgarClient) -> dict[str, int]:
    data = client.get(TICKER_URL).json()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def fiscal_label(period_of_report: str, fiscal_year_end: str, form: str) -> tuple[int, str]:
    """Return (fiscal_year, fiscal_period) for a filing.

    fiscal_year = calendar year in which the company's fiscal year ENDS.
    fiscal_year_end is EDGAR's 'MMDD' string (e.g. '1231', '1102').
    A 10-day tolerance handles 52/53-week fiscal years whose end date drifts.
    """
    y, m, d = (int(x) for x in period_of_report.split("-"))
    rep = date(y, m, d)
    fe_m, fe_d = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
    fe_d = min(fe_d, 28) if fe_m == 2 else fe_d
    fy_end_this_year = date(y, fe_m, fe_d)
    fy = y if rep <= fy_end_this_year + timedelta(days=10) else y + 1
    if form.startswith("10-K"):
        return fy, "FY"
    months_after_fy_end = (m - fe_m) % 12
    q = min(3, max(1, round(months_after_fy_end / 3)))
    return fy, f"Q{q}"


def _iter_filings(client: EdgarClient, sub: dict):
    """Yield filing rows (dicts), newest first: 'recent' block, then older paginated files.

    Large banks file thousands of prospectuses (424B2), so 'recent' may not reach back far enough.
    """
    def rows(block: dict):
        cols = list(block.keys())
        for i in range(len(block["form"])):
            yield {c: block[c][i] for c in cols}

    yield from rows(sub["filings"]["recent"])
    for extra in sub["filings"].get("files", []):
        yield from rows(client.get("https://data.sec.gov/submissions/" + extra["name"]).json())


def download_filings(
    client: EdgarClient, tickers: list[str], forms: dict[str, int], raw_dir: Path
) -> list[dict]:
    """Download the N most recent filings of each form per ticker; write raw_dir/manifest.jsonl."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    cik_map = ticker_to_cik(client)
    manifest: list[dict] = []

    for ticker in tickers:
        ticker = ticker.upper()
        if ticker not in cik_map:
            print(f"[ingest] WARNING: ticker {ticker} not found on EDGAR, skipped")
            continue
        cik = cik_map[ticker]
        sub = client.get(SUBMISSIONS_URL.format(cik=cik)).json()
        fye = sub.get("fiscalYearEnd") or "1231"
        counts = {f: 0 for f in forms}

        for row in _iter_filings(client, sub):  # newest first
            form = row["form"]
            if form not in forms or counts[form] >= forms[form]:
                continue
            accession = row["accessionNumber"]
            doc = row["primaryDocument"]
            por = row["reportDate"] or row["filingDate"]
            fy, fp = fiscal_label(por, fye, form)
            url = ARCHIVE_URL.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=doc)
            local = raw_dir / ticker / f"{accession}.htm"
            if not local.exists():
                print(f"[ingest] {ticker} {form} {por} -> {url}")
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(client.get(url).content)
            else:
                print(f"[ingest] {ticker} {form} {por} (cached)")
            manifest.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "company": sub.get("name", ticker),
                    "form": form,
                    "accession": accession,
                    "filing_date": row["filingDate"],
                    "period_of_report": por,
                    "fiscal_year": fy,
                    "fiscal_period": fp,
                    "fiscal_year_end": fye,
                    "primary_document": doc,
                    "source_url": url,
                    "local_path": str(local.relative_to(raw_dir)),
                }
            )
            counts[form] += 1
            if all(counts[f] >= forms[f] for f in forms):
                break

        missing = {f: forms[f] - c for f, c in counts.items() if c < forms[f]}
        if missing:
            print(f"[ingest] NOTE: {ticker} has fewer recent filings than requested: {missing}")

    with open(raw_dir / "manifest.jsonl", "w") as f:
        for row in manifest:
            f.write(json.dumps(row) + "\n")
    print(f"[ingest] {len(manifest)} filings -> {raw_dir / 'manifest.jsonl'}")
    return manifest
