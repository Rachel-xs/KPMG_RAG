"""Export chunks for the full-corpus index from Data's RDS, pinned to the processing sets in a freeze list.

    python scripts/export_full_rds.py                     # eval/full_filings.csv -> exports/full233.csv
    python scripts/export_full_rds.py --check-only        # report ids + chunk counts per filing, writes nothing

Freeze lists: eval/full_filings.csv (all "source" sets) or eval/full_filings_legacy.csv (legacy sets, 11/24).
Source sets map to reports via sec.source_processing_reports, legacy sets via sec.filing_processing_sets.
v2: the set -> report mapping comes from the small base table sec.source_processing_reports (the catalog view
carries full report text and was too slow for 233 sets at once), and chunks are pulled one filing at a time with
a per-query timeout and progress lines. Same CSV columns as exports/round1_21.csv. Read-only.
"""
import argparse, csv, os, sys, time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_round1_rds import COLUMNS, connect  # noqa: E402

REPORTS = """SELECT processing_set_id::text, report_id::text, chunking_version
FROM sec.source_processing_reports WHERE processing_set_id = ANY(%s::uuid[])"""
LEGACY = """SELECT id::text, report_id::text, chunking_version
FROM sec.filing_processing_sets WHERE id = ANY(%s::uuid[])"""
LEGACY_FALLBACK = """SELECT DISTINCT processing_set_id::text, report_id::text, chunking_version
FROM sec.chunk_catalog WHERE processing_set_id = ANY(%s::uuid[])"""
CHUNKS = f"""
SELECT {COLUMNS.replace('sel.processing_set_id, sel.set_key', '%s::uuid AS processing_set_id, NULL AS set_key')}
FROM sec.chunk_citations cc
JOIN sec.chunks ch ON ch.id = cc.chunk_id
LEFT JOIN sec.report_sections rs ON rs.id = ch.section_id
WHERE cc.report_id = %s::uuid AND cc.chunking_version = %s
ORDER BY cc.chunk_index"""


CHUNKS_HIST = CHUNKS.replace("FROM sec.chunk_citations cc", "FROM sec.chunk_citations_history cc")
CHUNKS_CAT = f"""
SELECT DISTINCT ON (cc.chunk_id) {COLUMNS.replace('sel.processing_set_id, sel.set_key', 'cc.processing_set_id, cc.set_key')
                                     .replace('ch.section_id', 'cc.section_id').replace('rs.section_type', 'cc.section_type')
                                     .replace('rs.original_title', 'cc.original_title')}
FROM sec.chunk_catalog cc
WHERE cc.processing_set_id = %s::uuid AND cc.report_id = %s::uuid AND cc.chunking_version = %s
ORDER BY cc.chunk_id"""


def fetch(cur, ps, rid, cv, used):
    """Served view first; then the history view (non-served versions, e.g. legacy since 11/23); then chunk_catalog."""
    for name, sql in (("chunk_citations", CHUNKS), ("chunk_citations_history", CHUNKS_HIST), ("chunk_catalog", CHUNKS_CAT)):
        cur.execute(sql, (ps, rid, cv))
        rows = cur.fetchall()
        if rows:
            used[name] += 1
            if name == "chunk_citations_history":  # history may repeat a chunk; keep one row per chunk_id
                seen, uniq = set(), []
                for r in rows:
                    if r[0] not in seen:
                        seen.add(r[0]); uniq.append(r)
                rows = uniq
            return rows, cur.description
    used["none"] += 1
    return [], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", default=str(ROOT / "eval" / "full_filings.csv"))
    ap.add_argument("--out", default=str(ROOT / "exports" / "full233.csv"))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--timeout-s", type=int, default=120)
    a = ap.parse_args()
    want = list(csv.DictReader(open(a.freeze)))
    by_set = {r["processing_set_id"]: r for r in want}
    print(f"freeze list: {len(want)} filings, {len(by_set)} processing sets", flush=True)

    print("connecting to RDS ...", flush=True)
    conn = connect()
    conn.set_session(readonly=True, autocommit=True)
    print(f"connected; looking up report ids (timeout {a.timeout_s}s) ...", flush=True)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {a.timeout_s * 1000}")
        t = time.time()
        cur.execute(REPORTS, (list(by_set),))
        reps = defaultdict(list)
        for ps, rid, cv in cur.fetchall():
            reps[ps].append((rid, cv))
        rest = [ps for ps in by_set if ps not in reps]  # legacy sets live in sec.filing_processing_sets
        if rest:
            from psycopg2 import errors
            try:
                cur.execute(LEGACY, (rest,))
            except (errors.InsufficientPrivilege, errors.UndefinedTable) as e:
                print(f"[info] {str(e).strip().splitlines()[0]} -> chunk_catalog fallback (slower)", flush=True)
                cur.execute(LEGACY_FALLBACK, (rest,))
            for ps, rid, cv in cur.fetchall():
                reps[ps].append((rid, cv))
    print(f"report ids: {sum(map(len, reps.values()))} reports for {len(reps)}/{len(by_set)} sets "
          f"({time.time() - t:.1f}s)", flush=True)
    no_rep = [ps for ps in by_set if ps not in reps]
    multi = {ps: v for ps, v in reps.items() if len(v) > 1}
    if no_rep:
        print("NO REPORT for sets:", [(by_set[p]["ticker"], by_set[p]["form"], by_set[p]["accession_number"]) for p in no_rep])
    if multi:
        print(f"[warn] {len(multi)} sets have more than one report; all are exported, check counts below")

    per, w, fh, used = Counter(), None, None, Counter()
    if not a.check_only:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        fh = open(a.out, "w", newline="", encoding="utf-8")
        w = csv.writer(fh)
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {a.timeout_s * 1000}")
        for i, (ps, row) in enumerate(by_set.items(), 1):
            for rid, cv in reps.get(ps, []):
                rows, desc = fetch(cur, ps, rid, cv, used)
                if w is not None and fh.tell() == 0 and desc:
                    w.writerow([d[0] for d in desc])
                per[row["accession_number"]] += len(rows)
                if w is not None:
                    w.writerows([["" if v is None else v for v in r] for r in rows])
            if i % 10 == 0 or i == len(by_set):
                print(f"  {i}/{len(by_set)} filings, {sum(per.values())} chunks, {time.time() - t0:.0f}s  {dict(used)}", flush=True)
    if fh:
        fh.close()
    conn.close()

    empty = [(r["ticker"], r["form"], r["accession_number"]) for r in want if per[r["accession_number"]] == 0]
    by_t = Counter()
    for r in want:
        by_t[r["ticker"]] += per[r["accession_number"]]
    print(f"\n{sum(1 for r in want if per[r['accession_number']])}/{len(want)} filings exported, {sum(per.values())} chunks")
    print("chunks by company:", dict(sorted(by_t.items())))
    print("smallest filings (chunks, accession):", sorted((n, acc) for acc, n in per.items())[:5])
    if empty:
        print("MISSING (no chunks):", empty)
    if not a.check_only:
        print(f"wrote {a.out}\nNext: bash scripts/build_full.sh {os.path.relpath(a.out, ROOT)}")
    sys.exit(1 if empty else 0)


if __name__ == "__main__":
    main()
