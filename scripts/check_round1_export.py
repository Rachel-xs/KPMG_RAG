"""Check a round-1 chunks.jsonl against the freeze list: every frozen filing present, nothing extra,
processing_set_id matches. Exit 1 on any mismatch.

    python scripts/check_round1_export.py data/round1/chunks_A/chunks.jsonl eval/round1_filings.csv
"""
import csv, json, sys
from collections import Counter

chunks, freeze = sys.argv[1], sys.argv[2]
want = {r["accession_number"]: r for r in csv.DictReader(open(freeze))}
got, psid = Counter(), {}
for line in open(chunks):
    c = json.loads(line)
    got[c["accession"]] += 1
    psid.setdefault(c["accession"], set()).add(c.get("processing_set_id"))
bad = 0
for acc, r in sorted(want.items(), key=lambda kv: (kv[1]["ticker"], kv[1]["form"])):
    n, ok_ps = got.get(acc, 0), psid.get(acc) == {r["processing_set_id"]}
    flag = "OK " if n and ok_ps else "BAD"
    note = "" if r["validation_status"] == "passed" else f"  [{r['validation_status']}]"
    print(f"{flag} {r['ticker']:5} {r['form']:5} {acc}  chunks={n:4}  set={'ok' if ok_ps else psid.get(acc)}{note}")
    bad += flag == "BAD"
extra = set(got) - set(want)
for acc in sorted(extra):
    print(f"BAD extra filing not in freeze list: {acc} ({got[acc]} chunks)")
print(f"\n{len(want) - bad}/{len(want)} frozen filings OK, {len(extra)} extra, {sum(got.values())} chunks total")
sys.exit(1 if bad or extra else 0)
