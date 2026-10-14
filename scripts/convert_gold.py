"""Convert Yulei's gold_set_v0.md (30 MSFT 10-Q questions) into the evaluator's JSONL format.

For each evidence region in the md "Evidence catalog", pick 1-3 short anchor strings from the
quoted source text that (a) appear in the region and (b) appear in as few corpus chunks as possible.
Those anchors become `contains` for the evidence item, so scoring does not depend on chunk_ids.
Usage: python convert_gold.py gold_set_v0.md chunks.jsonl out.jsonl
"""
import json, re, sys
from collections import Counter

md, chunks_path, out = sys.argv[1:4]
text = open(md, encoding="utf-8").read()
chunks = [json.loads(l) for l in open(chunks_path)]
norm = lambda s: re.sub(r"\s+", " ", s).lower()
ctext = [norm(c["text"]) for c in chunks]

# ---- evidence catalog
cat = {}
for m in re.finditer(r"### Evidence ([\w-]+)\n(.*?)(?=\n### Evidence |\n## )", text, re.S):
    name = m.group(1).replace("-", "_")
    body = m.group(2)
    sec = re.search(r"\*\*Section:\*\* (.*)", body).group(1).strip()
    quote = body.split("`", 2)[-1]
    quote = re.sub(r"^.*?\n", "", quote, count=1)  # drop rest of xpath line
    cat[name] = {"section": sec, "quote": norm(quote)}

def anchors(quote):
    """Candidate anchors: numbers with commas/decimals/% and 3-6 word phrases from the quote."""
    nums = re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\.\d+%?|\b\d+%", quote)
    words = quote.split()
    phrases = [" ".join(words[i:i+4]) for i in range(0, max(0, len(words)-4), 2)]
    phrases = [p for p in phrases if len(p) > 18 and not re.search(r"[()$]", p)]
    return list(dict.fromkeys(nums)) + phrases

report = {}
for name, ev in cat.items():
    cands = [a for a in anchors(ev["quote"]) if any(a in t for t in ctext)]
    # best chunk = most candidate anchors present
    score = Counter()
    for i, t in enumerate(ctext):
        score[i] = sum(a in t for a in cands)
    best, hits = score.most_common(1)[0] if cands else (None, 0)
    picked = []
    if best is not None and hits:
        in_best = [a for a in cands if a in ctext[best]]
        # prefer the rarest anchors
        in_best.sort(key=lambda a: (sum(a in t for t in ctext), -len(a)))
        for a in in_best:
            picked.append(a)
            matches = [i for i, t in enumerate(ctext) if all(p in t for p in picked)]
            if len(matches) <= 1 or len(picked) == 3:
                break
    matches = [i for i, t in enumerate(ctext) if picked and all(p in t for p in picked)]
    ev.update(contains=picked, match_chunks=[chunks[i]["chunk_id"] for i in matches],
              best_overlap=hits, n_cands=len(cands))
    report[name] = ev

# ---- questions
rows = []
for m in re.finditer(r"### (GSv0-MSFT-\d+) — ([^\n]+)\n(.*?)(?=\n### GSv0|\n## Evidence catalog)", text, re.S):
    qid, tags, body = m.groups()
    tier = tags.split("·")[0].strip()
    q = re.search(r"\*\*Question:\*\* (.*)", body).group(1).strip()
    ref = re.search(r"\*\*Reference answer:\*\* (.*)", body).group(1).strip()
    pts = re.findall(r"^- (.*)$", body.split("**Required answer points:**")[1].split("**")[0], re.M)
    evs = re.findall(r"\(#evidence-([\w-]+)\)", body)
    period = re.search(r"\*\*Period:\*\* `([^`]*)`", body)
    inp = re.search(r"\*\*Inputs:\*\* (.*)", body)
    nums = [f"{int(float(v)):,}" if abs(float(v)) >= 1000 else v
            for v in re.findall(r"=\s*(-?[\d.]+)", inp.group(1))] if inp else []
    nums = [n.lstrip("-") for n in nums]
    evidence = []
    for e in evs:
        r = report[e.replace("-", "_")]
        own = [n for n in nums if n in r["quote"] and any(n in t for t in ctext)]
        own.sort(key=lambda a: sum(a in t for t in ctext))
        anchors_q = own[:1] if own else r["contains"]
        evidence.append({"region": e.replace("-", "_"), "ticker": "MSFT", "form": "10-Q",
                         "accession": "0001193125-26-191507", "contains": anchors_q,
                         "anchor_source": "question_input" if own else "region"})
    rows.append({
        "qid": qid, "tier": tier, "question": q,
        "filters": {"ticker": "MSFT", "form": "10-Q"},
        "gold": {"chunk_ids": [], "evidence": evidence},
        "expected": {"ticker": ["MSFT"]},
        "quantitative": "quantitative" in tags,
        "reference_answer": ref, "required_points": pts,
        "period": period.group(1) if period else None,
        "status": "draft",
        "notes": "auto-converted from gold_set_v0.md; anchors need human check",
    })

with open(out, "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"{len(rows)} questions -> {out}; tiers={Counter(r['tier'] for r in rows)}")
print("\nregion                     anchors -> #matching chunks")
for n, r in report.items():
    print(f"{n:26s} {r['contains']!s:70.70s} -> {len(r['match_chunks'])}  (overlap {r['best_overlap']}/{r['n_cands']})")
json.dump(report, open(out.replace(".jsonl", "_regions.json"), "w"), indent=1)
