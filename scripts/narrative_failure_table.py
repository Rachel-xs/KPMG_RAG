"""#6 step 1: classify the narrative (anchored prose) retrieval misses, so the fix is chosen by cause.

    python scripts/narrative_failure_table.py      # reads the Round 1 v2.1 retrieval results, no API calls

Inputs: eval/results/round1_v2_1/per_question.csv and gold_v2_rag.jsonl (scripts/run_round1_eval.py output),
the Round 1 index (chunks + BM25). Dense ranks are not recomputed (no embedding model needed): the per-method
hit/miss at @10 comes from the retrieval run itself.

Causes (first that applies is the primary one; the others are listed as secondary):
  cross_company   several companies in the filter; retrieve_multi already finds it (route to structured / multi)
  scattered       the anchors sit in 2+ different chunks, and @10 does not hold all of them
  fusion          BM25 alone or dense alone has the evidence @10, hybrid RRF pushes it out
  anchor_problem  no indexed chunk contains the anchor text
  no_section      the anchor chunk has no section label (section filter would not help or hurt)
  wording         none of the above: the question's words differ from the filing's (query rewriting)
"""
from __future__ import annotations

import csv, json, pickle, sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.contract import chunk_matches, normalize_filters  # noqa: E402
from rag.retrieve import _filter_fields  # noqa: E402
from rag.text_utils import tokenize  # noqa: E402

RES = ROOT / "eval/results/round1_v2_1"
INDEX = ROOT / "data/round1/index_C1"
FIX = {"cross_company": "retrieve_multi / structured route (already in v1.2)",
       "scattered": "parent / neighbour expansion (parent_text, about 3k tokens), or k=15 for narrative",
       "fusion": "union of BM25 and dense top results for narrative questions, or the reranker on narrative only",
       "anchor_problem": "ask Eval to re-anchor", "no_section": "Data section field / title inference",
       "wording": "query rewriting (#5) on narrative only"}


def norm(t: str) -> str:
    return " ".join(t.replace("’", "'").lower().split())


def main():
    chunks = [json.loads(l) for l in open(INDEX / "chunks.jsonl", encoding="utf-8")]
    bm25 = pickle.load(open(INDEX / "bm25.pkl", "rb"))
    fields = [_filter_fields(c) for c in chunks]
    gold = {json.loads(l)["qid"]: json.loads(l) for l in open(RES / "gold_v2_rag.jsonl", encoding="utf-8")}
    rows = [r for r in csv.DictReader(open(RES / "per_question.csv", encoding="utf-8")) if r["kind"] == "anchored_prose"]
    misses = [r for r in rows if r["hybrid_filtered_strict@10"] != "True"]

    out = []
    for r in misses:
        q = gold[r["qid"]]
        nf = normalize_filters(q.get("filters"))
        idx = np.array([i for i, f in enumerate(fields) if chunk_matches(f, nf)])
        s = bm25.scores(tokenize(q["question"]))[idx]
        rank = {int(i): n + 1 for n, i in enumerate(idx[np.argsort(-s, kind="stable")])}
        anchors = []
        for ev in q.get("rag_evidence") or []:
            for x in ev.get("contains") or []:
                hits = [int(i) for i in idx if norm(x) in norm(chunks[i]["text"])]
                anchors.append({"text": x, "chunks": [chunks[i]["chunk_id"] for i in hits],
                                "bm25_rank": min((rank[i] for i in hits), default=None),
                                "sections": sorted({chunks[i].get("section") or "" for i in hits})})
        located = [a for a in anchors if a["chunks"]]
        common = set.intersection(*[set(a["chunks"]) for a in located]) if located else set()
        n_chunks = 1 if common else len({c for a in anchors for c in a["chunks"][:1]})
        single = {"bm25": r["bm25_filtered_strict@10"] == "True", "dense": r["dense_filtered_strict@10"] == "True"}
        causes = []
        if len(q.get("tickers") or []) > 1:
            causes.append("cross_company")
        if n_chunks >= 2:
            causes.append("scattered")
        if any(single.values()):
            causes.append("fusion")
        if len(located) < len(anchors):
            causes.append("anchor_problem")
        if located and all(not a["sections"] or a["sections"] == [""] for a in located):
            causes.append("no_section")
        if not causes:
            causes.append("wording")
        out.append({"qid": r["qid"], "type": r["type"], "primary": causes[0], "secondary": "|".join(causes[1:]),
                    "bm25@10": single["bm25"], "dense@10": single["dense"], "multi": r.get("multi_strict") or "",
                    "anchor_chunks": n_chunks,
                    "anchor_bm25_ranks": "|".join(str(a["bm25_rank"]) for a in anchors),
                    "anchor_sections": "|".join(",".join(a["sections"]) for a in anchors),
                    "fix": FIX[causes[0]], "question": q["question"]})

    out_dir = ROOT / "eval/results/narrative"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "failure_table.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    any_cause = Counter(c for o in out for c in [o["primary"], *filter(None, o["secondary"].split("|"))])
    md = [f"# Narrative retrieval misses: {len(out)} of {len(rows)} anchored-prose questions (hybrid, filtered, strict @10)\n",
          f"Primary cause: {dict(Counter(o['primary'] for o in out))}",
          f"Any cause: {dict(any_cause)}", "",
          "| qid | type | primary | also | BM25@10 | dense@10 | anchor chunks | anchor BM25 ranks | sections | fix |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {o['qid']} | {o['type']} | {o['primary']} | {o['secondary']} | {'✓' if o['bm25@10'] else '✗'} | "
           f"{'✓' if o['dense@10'] else '✗'} | {o['anchor_chunks']} | {o['anchor_bm25_ranks']} | {o['anchor_sections']} | {o['fix']} |"
           for o in out]
    (out_dir / "failure_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
