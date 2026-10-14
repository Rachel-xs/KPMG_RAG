"""Region-level ("lenient") evidence recall, reported beside the strict anchor-based metric.

A retrieved chunk counts for an evidence item if it is from the target filing AND >= 60% of its
distinct words (4+ chars) appear in that evidence region's source text (eval/gold_v0_msft_regions.json).
This credits a correct chunk of a multi-chunk region even when it lacks the item's anchor string.
It can over-credit boilerplate, so read it as an upper bound; strict recall is the lower bound.

    python scripts/region_recall.py            # all methods, filters on/off, averaged per question
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.retrieve import Retriever  # noqa: E402
from rag.evaluate import load_gold, evidence_hits  # noqa: E402

TARGET = "0001193125-26-191507"
reg = json.load(open("eval/gold_v0_msft_regions.json"))
tok = lambda s: set(re.findall(r"[a-z0-9][a-z0-9,.%-]{3,}", s.lower()))
rtok = {k: tok(v["quote"]) for k, v in reg.items()}

def lenient(e, c):
    if c.get("accession_number") != TARGET:
        return False
    t = tok(c["text"])
    return len(t) > 5 and len(t & rtok[e["region"]]) / len(t) >= 0.6

r = Retriever("data/index", log_dir=None)
gold = load_gold(Path("eval/gold_v0_msft.jsonl"), True)
methods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["bm25", "dense", "hybrid"]
print(f"{'filters':10s} {'method':8s} {'strict@5':>9s} {'region@5':>9s} {'strict@10':>10s} {'region@10':>10s}")
for fm in ("filtered", "unfiltered"):
    for m in methods:
        acc = {k: [0.0, 0.0] for k in (5, 10)}
        for q in gold:
            res = r.search(q["question"], filters=q["filters"] if fm == "filtered" else None, top_k=10, method=m)["results"]
            ev = q["gold"]["evidence"]
            for k in (5, 10):
                top = res[:k]
                acc[k][0] += sum(any(evidence_hits(e, c) for c in top) for e in ev) / len(ev)
                acc[k][1] += sum(any(evidence_hits(e, c) or lenient(e, c) for c in top) for e in ev) / len(ev)
        n = len(gold)
        print(f"{fm:10s} {m:8s} {acc[5][0]/n:9.3f} {acc[5][1]/n:9.3f} {acc[10][0]/n:10.3f} {acc[10][1]/n:10.3f}")
