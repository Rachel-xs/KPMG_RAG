"""Deterministic pre-check (contract v1.3 draft): is the filing a question needs in the corpus at all?

Mentor guidance (11/12): before calling RAG or GraphRAG, the agent extracts which companies and periods the user
asks about, a tool checks whether those filings exist, and the hits and misses go back to the agent. If nothing
hits, the agent answers directly ("not in our database") without calling any retriever. This module is that tool
for the RAG corpus. It makes no model calls and reads only filing-level metadata.

    from rag.coverage import check_coverage, extract_request
    req = extract_request("What was Micorsoft's revenue for the three months ended March 31, 2026?")
    check_coverage(**req)
    # -> {"status": "all_hit", "targets": [{"ticker": "MSFT", "period_end": "2026-03-31", "status": "hit", ...}], ...}

check_coverage(tickers, companies, forms, fiscal_years, fiscal_periods, period_ends) -> dict
    status          "all_hit" | "partial" | "none" | "unresolved" | "no_target"
                    unresolved = a company name matched nothing in the corpus (e.g. Tesla) and nothing else hit
                    no_target  = the request names no company, so there is nothing to check (go on to retrieval)
    entities        how each company name / ticker was resolved: exact ticker, alias, or fuzzy (with score)
    unresolved      names that matched no company in the corpus
    targets         one row per company x requested form / fiscal year / period / date, each "hit" or "miss",
                    with the matching accession numbers
    available       for every requested company: the filings we do have (so the agent can say what it can answer)
    filters         RAG filters for the targets that hit, ready for retrieve_multi()
    message         one plain-English sentence the agent can show or paraphrase

Design choices (all conservative: a wrong "miss" would refuse an answerable question, a wrong "hit" only costs a
retrieval call, after which evidence_status still applies):
  * A date is covered by a filing whose period ends within DATE_TOLERANCE_DAYS of it (Apple and Micron close on
    52/53-week calendars), by the prior-year comparative column (period end minus one year), and for a 10-Q by the
    company's last fiscal year end (balance-sheet comparative).
  * Fuzzy company matching only for names of 5+ characters, at FUZZY_THRESHOLD; short names and tickers match
    exactly. Eval found a misspelled company name drops correct scope decisions from 98% to 19%.
"""
from __future__ import annotations

import csv
import difflib
import itertools
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATE_TOLERANCE_DAYS = 7
FUZZY_THRESHOLD = 0.84
MIN_FUZZY_LEN = 5
FISCAL_PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4")

# Extra names people use. Generated aliases (legal name minus Inc./Corporation/...) are added automatically.
EXTRA_ALIASES = {
    "MSFT": ["microsoft", "msft"],
    "AAPL": ["apple"],
    "CASY": ["casey's", "caseys", "casey's general stores"],
    "MCK": ["mckesson"],
    "MDT": ["medtronic"],
    "MU": ["micron", "micron technology"],
    "NKE": ["nike"],
    "NTAP": ["netapp", "net app"],
    "PH": ["parker-hannifin", "parker hannifin", "parker"],
    "TTWO": ["take-two", "take two", "take-two interactive", "take two interactive"],
}
_SUFFIXES = r"\b(inc|incorporated|corp|corporation|co|company|plc|ltd|limited|llc|holdings|the)\b\.?"
# Words that are never company names, so fuzzy matching on running text does not fire on them.
_STOP = {"revenue", "income", "quarter", "fiscal", "company", "companies", "report", "annual", "segment", "total",
         "share", "shares", "stock", "price", "dollars", "million", "billion", "percent", "growth", "margin",
         "operating", "expenses", "assets", "between", "during", "compared", "nine", "three", "months", "ended",
         "which", "where", "what", "their", "there", "these", "those", "about", "under", "after", "before",
         "apply", "applied", "micro", "explain", "describe", "compare", "among", "using", "state", "given",
         "derive", "list", "name", "rank", "report", "reported", "filing", "filings", "according", "based"}

_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_DATE_RE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_FY_RE = re.compile(r"\b(?:fiscal(?:\s+year)?\s*|fy\s*'?)(\d{4}|\d{2})\b", re.I)
_Q_RE = re.compile(r"\b(?:q([1-4])|(first|second|third|fourth)\s+(?:fiscal\s+)?quarter)\b", re.I)
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_FORM_RE = re.compile(r"\b10-?([KQ])\b|\b(annual report|quarterly report)\b", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).replace("’", "'").lower()
    s = re.sub(_SUFFIXES, " ", s)
    s = re.sub(r"[^a-z0-9'& -]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,.-")


def _osa(a: str, b: str) -> int:
    """Optimal string alignment distance (Levenshtein + adjacent transposition)."""
    if abs(len(a) - len(b)) > 2:
        return 99
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _d(s) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    s = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s) or None
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)  # Data's CSV: M/D/YYYY
    if m:
        return date(int(m[3]), int(m[1]), int(m[2]))
    raise ValueError(f"unrecognised date: {s!r}")


def _minus_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - 1, day=28)


@dataclass(frozen=True)
class Filing:
    ticker: str
    company: str
    form: str
    accession: str
    period_end: date | None
    fiscal_year: int | None
    fiscal_period: str | None

    def label(self) -> str:
        fy = f" FY{self.fiscal_year} {self.fiscal_period}" if self.fiscal_year else ""
        pe = f", period ended {self.period_end}" if self.period_end else ""
        return f"{self.form}{fy}{pe}"


class CoverageIndex:
    """Filing-level manifest of what the corpus holds, plus company-name resolution."""

    def __init__(self, filings: list[Filing], source: str = ""):
        self.filings = sorted(set(filings), key=lambda f: (f.ticker, f.period_end or date.min, f.form))
        self.source = source
        self.by_ticker: dict[str, list[Filing]] = {}
        for f in self.filings:
            self.by_ticker.setdefault(f.ticker, []).append(f)
        self.aliases: dict[str, str] = {}
        for t, fs in self.by_ticker.items():
            self.aliases[t.lower()] = t
            for name in {f.company for f in fs if f.company}:
                n = _norm(name)
                if n:
                    self.aliases[n] = t
                    self.aliases[n.replace("'", "")] = t
            for a in EXTRA_ALIASES.get(t, []):
                self.aliases[_norm(a)] = t
        # last fiscal-year end month/day per ticker (from its 10-K), for 10-Q balance-sheet comparatives
        self.fy_end = {t: max((f.period_end for f in fs if f.form == "10-K" and f.period_end), default=None)
                       for t, fs in self.by_ticker.items()}

    # ---------- loaders ----------
    @classmethod
    def from_chunks(cls, path: str | Path) -> "CoverageIndex":
        """Index chunks.jsonl (custom backend) - one record per accession."""
        with open(path, encoding="utf-8") as fh:
            recs = (json.loads(line) for line in fh if line.strip())
            return cls.from_records(recs, source=str(path))

    @classmethod
    def from_records(cls, chunks, source: str = "records") -> "CoverageIndex":
        """Any iterable of stored chunks, e.g. a live retriever's `.chunks` (custom or Chroma backend)."""
        seen: dict[str, Filing] = {}
        for c in chunks:
            acc = c.get("accession_number") or c.get("accession")
            if acc in seen:
                continue
            seen[acc] = Filing(c.get("ticker") or "", c.get("company_name") or c.get("company") or "",
                               c.get("form") or "", acc,
                               _d(c.get("reporting_period_end") or c.get("period_of_report")),
                               int(c["fiscal_year"]) if c.get("fiscal_year") else None,
                               (c.get("fiscal_period") or None))
        return cls(list(seen.values()), source=source)

    @classmethod
    def from_csv(cls, path: str | Path, company_names: dict[str, str] | None = None) -> "CoverageIndex":
        """A filings manifest CSV (e.g. eval/round1_filings.csv or a Data export): ticker, accession_number, form,
        reporting_period_end, optional company_name / fiscal_year / fiscal_period / validation_status.
        Rows with validation_status other than "passed" are left out (NTAP 10-Q until Data releases it)."""
        out = []
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("validation_status") and r["validation_status"] != "passed":
                    continue
                t = r["ticker"].strip().upper()
                out.append(Filing(t, r.get("company_name") or (company_names or {}).get(t, ""), r["form"].strip(),
                                  r["accession_number"].strip(), _d(r.get("reporting_period_end")),
                                  int(r["fiscal_year"]) if r.get("fiscal_year") else None,
                                  r.get("fiscal_period") or None))
        return cls(out, source=str(path))

    # ---------- company resolution ----------
    def resolve(self, name: str) -> dict:
        """{'input', 'ticker' | None, 'match': 'ticker'|'alias'|'fuzzy'|None, 'score'}"""
        raw = name.strip()
        if raw.upper() in self.by_ticker:
            return {"input": name, "ticker": raw.upper(), "match": "ticker", "score": 1.0}
        n = _norm(raw)
        for cand in (n, n.replace("'", ""), re.sub(r"'s$", "", n)):
            if cand in self.aliases:
                return {"input": name, "ticker": self.aliases[cand], "match": "alias", "score": 1.0}
        if len(n) >= MIN_FUZZY_LEN:
            best, score = None, 0.0
            for a, t in self.aliases.items():
                if len(a) < MIN_FUZZY_LEN:
                    continue
                s = difflib.SequenceMatcher(None, n, a).ratio()
                if s > score:
                    best, score = t, s
            if best and score >= FUZZY_THRESHOLD:
                return {"input": name, "ticker": best, "match": "fuzzy", "score": round(score, 3)}
            # one or two typing errors (swap / drop / double) in short names, where the ratio is too strict
            m = len(n.replace("'", ""))
            for a, t in self.aliases.items():
                if len(a) >= MIN_FUZZY_LEN and _osa(n.replace("'", ""), a.replace("'", "")) <= (1 if m <= 7 else 2):
                    return {"input": name, "ticker": t, "match": "fuzzy", "score": round(difflib.SequenceMatcher(None, n, a).ratio(), 3)}
        return {"input": name, "ticker": None, "match": None, "score": 0.0}

    # ---------- coverage ----------
    def _covers_date(self, f: Filing, d: date) -> bool:
        if not f.period_end:
            return False
        tol = timedelta(days=DATE_TOLERANCE_DAYS)
        cands = [f.period_end, _minus_year(f.period_end)]
        fy = self.fy_end.get(f.ticker)
        if f.form == "10-Q" and fy:  # balance sheet compares with the last fiscal year end before this quarter
            prior = fy
            while prior > f.period_end:
                prior = _minus_year(prior)
            cands.append(prior)
        return any(abs((c - d).days) <= tol.days for c in cands)

    def _match(self, f: Filing, form, fy, fp, pe) -> bool:
        if form and f.form.upper() != form.upper():
            return False
        if fy is not None and f.fiscal_year != fy:
            # a 10-K also reports the prior fiscal year; a 10-Q the same quarter a year earlier
            if not (f.fiscal_year == fy + 1 and fp in (None, f.fiscal_period)):
                return False
        if fp and f.fiscal_period != fp:
            # a 10-K covers the full year and the fourth quarter (derived); "Q4" questions need the 10-K
            if not (fp == "Q4" and f.fiscal_period == "FY"):
                return False
        if pe is not None and not self._covers_date(f, pe):
            return False
        return True

    def check(self, tickers=None, companies=None, forms=None, fiscal_years=None, fiscal_periods=None,
              period_ends=None, combine: str = "product") -> dict:
        """combine="product": every company x form x fiscal year x period x date must be covered (structured
        filters from the Agent, like retrieve_multi's split). combine="independent": each kind of constraint is
        checked on its own per company - every date, every fiscal year/quarter pair, and the forms - which suits
        constraints pulled out of free text (e.g. "use the FY2026 10-K and the Q3 10-Q to derive Q4")."""
        if combine not in ("product", "independent"):
            raise ValueError("combine must be 'product' or 'independent'")
        as_list = lambda v: [] if v is None else (list(v) if isinstance(v, (list, tuple, set)) else [v])  # noqa: E731
        entities = [self.resolve(str(x)) for x in as_list(tickers) + as_list(companies)]
        resolved = list(dict.fromkeys(e["ticker"] for e in entities if e["ticker"]))
        unresolved = [e["input"] for e in entities if not e["ticker"]]
        forms_l = [f.upper().replace("10K", "10-K").replace("10Q", "10-Q") for f in as_list(forms)] or [None]
        fys = [int(x) for x in as_list(fiscal_years)] or [None]
        fps = [str(x).upper() for x in as_list(fiscal_periods)] or [None]
        for p in fps:
            if p and p not in FISCAL_PERIODS:
                raise ValueError(f"fiscal_period must be one of {FISCAL_PERIODS}, got {p!r}")
        pes = [_d(x) for x in as_list(period_ends)] or [None]

        if combine == "product":
            plan = list(itertools.product(forms_l, fys, fps, pes))
        else:
            plan = [(None, None, None, pe) for pe in pes if pe] + \
                   [(None, fy, fp, None) for fy, fp in itertools.product(fys, fps) if fy or fp] + \
                   [(f, None, None, None) for f in forms_l if f]
            plan = plan or [(None, None, None, None)]
        targets = []
        for t in resolved:
            for form, fy, fp, pe in plan:
                hits = [f for f in self.by_ticker.get(t, []) if self._match(f, form, fy, fp, pe)]
                targets.append({"ticker": t, "form": form, "fiscal_year": fy, "fiscal_period": fp,
                                "period_end": pe.isoformat() if pe else None,
                                "status": "hit" if hits else "miss",
                                "accessions": [f.accession for f in hits]})
        n_hit = sum(t["status"] == "hit" for t in targets)
        if not entities:
            status = "no_target"
        elif not resolved:
            status = "unresolved"
        elif n_hit == len(targets) and not unresolved:
            status = "all_hit"
        elif n_hit == 0:
            status = "none"
        else:
            status = "partial"
        available = {t: [f.label() for f in self.by_ticker.get(t, [])] for t in resolved}
        filters = None
        hit_acc = sorted({a for t in targets for a in t["accessions"]})
        if hit_acc:
            filters = {"accession_number": hit_acc}
        return {"status": status, "entities": entities, "unresolved": unresolved, "targets": targets,
                "available": available, "filters": filters, "message": self._message(status, targets, unresolved,
                                                                                         available),
                "manifest": {"source": self.source, "n_filings": len(self.filings)}}

    @staticmethod
    def _message(status, targets, unresolved, available) -> str:
        def desc(t):
            bits = [t["ticker"], t["form"] or "",
                    f"FY{t['fiscal_year']}" if t["fiscal_year"] else "", t["fiscal_period"] or "",
                    f"period ended {t['period_end']}" if t["period_end"] else ""]
            return " ".join(b for b in bits if b)
        miss = [desc(t) for t in targets if t["status"] == "miss"]
        parts = []
        if unresolved:
            parts.append("Not in our database: " + ", ".join(unresolved) + ".")
        if miss:
            parts.append("No filing in our database covers: " + "; ".join(miss) + ".")
            for tk in dict.fromkeys(t["ticker"] for t in targets if t["status"] == "miss"):
                parts.append(f"For {tk} we have: " + "; ".join(available.get(tk, [])) + ".")
        if status == "no_target":
            return "The question names no company, so there is nothing to pre-check."
        if status == "all_hit":
            return "All requested filings are in the database."
        return " ".join(parts)


# ---------- question -> request (deterministic baseline; the Agent's LLM extractor can replace it) ----------
def extract_request(question: str, index: CoverageIndex | None = None) -> dict:
    """Pull companies, dates, fiscal years / quarters and forms out of a question with rules only.

    Companies: tickers written in capitals, known aliases, and fuzzy matches of capitalised words (typos)."""
    index = index or default_index()
    q = question.replace("’", "'")
    companies: list[str] = []
    for tk in index.by_ticker:
        if re.search(rf"(?<![A-Za-z]){re.escape(tk)}(?![A-Za-z])", q):
            companies.append(tk)
    low = " " + _norm(q) + " "
    for alias in sorted(index.aliases, key=len, reverse=True):
        if len(alias) < 3 or alias.upper() in index.by_ticker:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?:'s)?(?![a-z0-9])", low):
            companies.append(alias)
            low = low.replace(alias, " ")
    # capitalised words and two-word names that did not match exactly: fuzzy-resolve (typos), keep only hits
    known = {index.resolve(c)["ticker"] for c in companies}
    for m in re.finditer(r"\b([A-Z][A-Za-z'&-]{3,}(?:\s+[A-Z][A-Za-z'&-]+)?)", q):
        cand = m.group(1)
        parts = cand.split()
        words = ([cand] if len(parts) > 1 else []) + parts
        words = [v for w in words for v in dict.fromkeys([w, re.sub(r"'s$", "", w)])]
        for w in words:
            if _norm(w) in _STOP or len(_norm(w).replace("'", "")) < MIN_FUZZY_LEN:
                continue
            r = index.resolve(w)
            if r["match"] == "fuzzy" and r["ticker"] not in known:
                companies.append(w)
                known.add(r["ticker"])
                break

    period_ends = []
    for m in _DATE_RE.finditer(q):
        before, after = q[max(0, m.start() - 12):m.start()].lower(), q[m.end():m.end() + 30].lower()
        if "as of" in before or "snapshot" in after or "filed" in before:
            continue  # a cut-off or filing date, not the period asked about
        mo, dd, y = m.groups()
        period_ends.append(date(int(y), _MONTHS[mo.lower().rstrip('.')], int(dd)).isoformat())
    period_ends += [f"{y}-{mo}-{dd}" for y, mo, dd in _ISO_RE.findall(q)]
    fiscal_years = []
    for y in _FY_RE.findall(q):
        fiscal_years.append(int(y) if len(y) == 4 else 2000 + int(y))
    fiscal_periods = []
    for qn, word in _Q_RE.findall(q):
        fiscal_periods.append(f"Q{qn}" if qn else f"Q{_ORD[word.lower()]}")
    forms = []
    for kq, phrase in _FORM_RE.findall(q):
        forms.append("10-K" if (kq.upper() == "K" or (phrase and phrase.lower().startswith("annual"))) else "10-Q")
    if fiscal_years and not fiscal_periods and not period_ends and re.search(r"\b(full[- ]year|fiscal year)\b", q, re.I):
        fiscal_periods.append("FY")
    dedup = lambda xs: list(dict.fromkeys(xs)) or None  # noqa: E731
    return {"companies": dedup(companies), "period_ends": dedup(period_ends), "fiscal_years": dedup(fiscal_years),
            "fiscal_periods": dedup(fiscal_periods), "forms": dedup(forms)}


_DEFAULT: CoverageIndex | None = None


def default_index() -> CoverageIndex:
    """Manifest from $RAG_COVERAGE_MANIFEST (CSV); else the custom index's chunks.jsonl ($RAG_INDEX_DIR, then config);
    else the chunks of the retriever the Agent actually calls (Chroma by default), so the pre-check covers exactly
    what retrieval can return."""
    global _DEFAULT
    if _DEFAULT is None:
        manifest = os.environ.get("RAG_COVERAGE_MANIFEST")
        if manifest:
            _DEFAULT = CoverageIndex.from_csv(manifest)
            return _DEFAULT
        idx = os.environ.get("RAG_INDEX_DIR")
        if not idx and not os.environ.get("RAG_CHROMA_DIR") and os.environ.get("RAG_BACKEND", "").lower() != "chroma":
            from .config import load_config
            idx = load_config()["paths"]["index"]
        if idx and (Path(idx) / "chunks.jsonl").exists():
            _DEFAULT = CoverageIndex.from_chunks(Path(idx) / "chunks.jsonl")
        else:
            from .retrieve import _default_retriever
            r = _default_retriever()
            _DEFAULT = CoverageIndex.from_records(r.chunks, source=f"{type(r).__name__}:{getattr(r, 'index_dir', '')}")
    return _DEFAULT


def check_coverage(tickers=None, companies=None, forms=None, fiscal_years=None, fiscal_periods=None,
                   period_ends=None, combine: str = "product") -> dict:
    """Agent-facing tool. See module docstring for the return shape."""
    return default_index().check(tickers=tickers, companies=companies, forms=forms, fiscal_years=fiscal_years,
                                 fiscal_periods=fiscal_periods, period_ends=period_ends, combine=combine)


def precheck_question(question: str) -> dict:
    """extract_request() + check_coverage(combine="independent") in one call; adds the extracted request."""
    idx = default_index()
    req = extract_request(question, idx)
    return {**idx.check(**req, combine="independent"), "request": req}
