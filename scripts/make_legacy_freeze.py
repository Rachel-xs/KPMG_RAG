"""Freeze list for the full index built from LEGACY processing sets (decided 11/24: Data's corrected "source" sets
render tables with huge empty header/separator rows, numeric recall@10 0.89 -> 0.57 on the same 21 filings).

    python scripts/make_legacy_freeze.py     # eval/full_filings_versions.csv -> eval/full_filings_legacy.csv

Rule: the 20 round-1 filings keep their frozen set (19 legacy + NKE 10-Q source) (eval/round1_filings.csv), so they must rebuild identically;
other filings take the newest PASSED legacy set; filings without one fall back to the passed source set (2 NTAP 10-Qs).
Same columns as eval/full_filings.csv. No database access.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
base = {r["accession_number"]: r for r in csv.DictReader(open(ROOT / "eval/full_filings.csv"))}
vers = defaultdict(list)
for r in csv.DictReader(open(ROOT / "eval/full_filings_versions.csv")):
    vers[r["accession_number"]].append(r)
frozen = {r["accession_number"]: r for r in csv.DictReader(open(ROOT / "eval/round1_filings.csv"))}

out, why = [], Counter()
for acc, b in base.items():
    vs = vers[acc]
    pick = None
    if acc in frozen:  # keep the exact frozen set (legacy, or NKE 10-Q's source set) if Data still has it as passed
        pick = next((v for v in vs if v["processing_set_id"] == frozen[acc]["processing_set_id"]
                     and v["validation_status"] == "passed"), None)
        reason = "frozen_round1_set"
    if pick is None:
        leg = sorted((v for v in vs if v["processing_family"] == "legacy" and v["validation_status"] == "passed"),
                     key=lambda v: v["created_at"])
        if leg:
            pick, reason = leg[-1], "newest_passed_legacy"
        else:
            pick = next(v for v in vs if v["processing_family"] == "source" and v["validation_status"] == "passed")
            reason = "no_passed_legacy_use_source"
    why[reason] += 1
    out.append({**b, "processing_family": pick["processing_family"], "processing_set_id": pick["processing_set_id"],
                "validation_status": pick["validation_status"], "selection_reason": reason})

with open(ROOT / "eval/full_filings_legacy.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(next(iter(base.values())).keys()))
    w.writeheader()
    w.writerows(out)
print(f"{len(out)} filings:", dict(why))
print("source fallbacks:", [(r["ticker"], r["form"], r["accession_number"]) for r in out
                            if r["selection_reason"] == "no_passed_legacy_use_source"])
print("wrote eval/full_filings_legacy.csv\nNext: python scripts/export_full_rds.py --freeze eval/full_filings_legacy.csv --out exports/full233_legacy.csv")
