"""Week 6 chunking experiment: build each variant, index it, score it on the same gold set.

Controls (same for every variant): corpus = Data's chunks (one snapshot), retriever = BM25 + bge-small + RRF,
gold = eval/gold_v0_msft.jsonl (anchored on `contains` strings, so it is valid for any chunking).

    # full run (on a machine with sentence-transformers + the bge-small model)
    python scripts/run_chunking_exp.py --tokenizer <bge tokenizer.json>
    # BM25-only smoke run (no torch): --embedder lsa --methods bm25

Writes eval/results/chunking_exp_<ts>/{summary.csv, per_question.csv, paired_vs_A.csv, report.md}
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from build_chunk_variant import Tok, build  # noqa: E402
from rag.evaluate import evidence_hits, load_gold, score_question  # noqa: E402
from rag.index import build_index  # noqa: E402
from rag.retrieve import Retriever  # noqa: E402

KS = (5, 10)
PARENT_CAP = 1500  # max tokens of one parent handed to the Agent
CHILD_POOL = 30    # children fetched to fill 5 distinct parents


def parent_map(chunks: list[dict], tables: dict, tok: Tok) -> dict:
    """chunk_id -> (parent_id, parent_text). Table piece -> whole table (if <= PARENT_CAP tokens, else the piece);
    text chunk -> previous + itself + next text chunk of the same section, shrunk until <= PARENT_CAP."""
    out = {}
    by_sec = collections.defaultdict(list)
    for c in chunks:
        if c.get("is_table") and c.get("table_id") in tables:
            whole = tables[c["table_id"]]
            out[c["chunk_id"]] = (c["table_id"], whole) if tok.n(whole) <= PARENT_CAP else (c["chunk_id"], c["text"])
        else:
            by_sec[(c.get("accession"), c.get("section_id"))].append(c)
    for cs in by_sec.values():
        cs.sort(key=lambda c: c["seq"])
        for i, c in enumerate(cs):
            for lo, hi in ((i - 1, i + 2), (i, i + 2), (i, i + 1)):
                win = cs[max(0, lo) : hi]
                text = "\n\n".join(x["text"] for x in win)
                if tok.n(text) <= PARENT_CAP or hi - lo == 1:
                    out[c["chunk_id"]] = ("win:" + "|".join(x["chunk_id"] for x in win), text)
                    break
    return out


def parent_scores(q: dict, results: list[dict], pmap: dict, tok: Tok, k: int = 5) -> dict:
    """Recall when the Agent receives the top-k DISTINCT parents of the retrieved children."""
    seen, parents = set(), []
    for r in results:
        pid, ptext = pmap.get(r["chunk_id"], (r["chunk_id"], r["text"]))
        if pid in seen:
            continue
        seen.add(pid)
        parents.append({**r["metadata"], **r, "text": ptext})
        if len(parents) == k:
            break
    ev = q["gold"].get("evidence", [])
    rec = sum(any(evidence_hits(e, p) for p in parents) for e in ev) / len(ev) if ev else 0.0
    return {f"parent_recall@{k}": rec, f"parent_top{k}_tokens": sum(tok.n(p["text"]) for p in parents)}


def table_questions(gold: list[dict], chunks_a: list[dict]) -> set[str]:
    """A question is a 'table question' if one of its evidence anchors sits on a table row ('|' line) in Data's text."""
    by = collections.defaultdict(list)
    for c in chunks_a:
        by[c["accession"]].append(c)
    out = set()
    for q in gold:
        for e in q["gold"].get("evidence", []):
            subs = [s.lower() for s in e.get("contains", [])]
            for c in by.get(e.get("accession"), []):
                for line in c["text"].lower().split("\n"):
                    if subs and subs[0] in line and line.count("|") >= 2:
                        out.add(q["qid"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="A,B,C1,C2")
    ap.add_argument("--chunks-a", default="data/chunks_A/chunks.jsonl", help="Data's chunks (variant A)")
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--max-tokens", type=int, default=460)
    ap.add_argument("--embedder", default="st:BAAI/bge-small-en-v1.5")
    ap.add_argument("--methods", default="bm25,dense,hybrid")
    ap.add_argument("--filters", default="filtered,unfiltered")
    ap.add_argument("--gold", default="eval/gold_v0_msft.jsonl")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    tok = Tok(a.tokenizer)
    chunks_a = [json.loads(l) for l in open(ROOT / a.chunks_a)]
    gold = load_gold(ROOT / a.gold, True)
    tq = table_questions(gold, chunks_a)
    out = Path(a.out) if a.out else ROOT / "eval" / "results" / f"chunking_exp_{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    methods, fms = a.methods.split(","), a.filters.split(",")

    per_q, builds = [], {}
    for v in a.variants.split(","):
        cdir, idir = ROOT / "data" / f"chunks_{v}", ROOT / "data" / f"index_{v}"
        tables = {}
        chunks = build([dict(c) for c in chunks_a], v, tok, a.max_tokens, tables)
        pmap = parent_map(chunks, tables, tok)
        cdir.mkdir(parents=True, exist_ok=True)
        with open(cdir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        meta = build_index(cdir / "chunks.jsonl", idir, a.embedder, ROOT / "data" / "cache")
        n = [c["n_tokens"] for c in chunks]
        builds[v] = {"n_chunks": len(chunks), "n_table_chunks": sum(bool(c.get("is_table")) for c in chunks),
                     "mean_tokens": round(statistics.mean(n), 1), "max_tokens": max(n),
                     "over_512": sum(x > 512 for x in n), "index_version": meta["index_version"],
                     "chunking_version": chunks[0].get("chunking_version"), "build_seconds": meta["build_seconds"]}
        r = Retriever(idir, log_dir=None)
        for fm in fms:
            for m in methods:
                for q in gold:
                    resp = r.search(q["question"], filters=q.get("filters") if fm == "filtered" else None, top_k=CHILD_POOL, method=m)
                    s = score_question(q, resp["results"][: max(KS)], KS)
                    s.update(parent_scores(q, resp["results"], pmap, tok))
                    top5_tokens = sum(x["metadata"].get("n_tokens") or 0 for x in resp["results"][:5])
                    per_q.append({"variant": v, "filters": fm, "method": m, "qid": q["qid"], "tier": q.get("tier"),
                                  "qtype": "table" if q["qid"] in tq else "text", "top5_tokens": top5_tokens, **s})
        print(f"[exp] {v} done: {builds[v]}")

    # ---- summary ----
    keys = [k for k in per_q[0] if k.startswith(("evidence_recall", "hit", "mrr", "parent_"))]
    groups = collections.defaultdict(list)
    for r in per_q:
        groups[(r["variant"], r["filters"], r["method"])].append(r)
    summary = []
    for (v, fm, m), rs in groups.items():
        row = {"variant": v, "filters": fm, "method": m, "n": len(rs)}
        for k in keys:
            row[k] = round(statistics.mean(x[k] for x in rs), 3)
        for qt in ("table", "text"):
            sub = [x for x in rs if x["qtype"] == qt]
            row[f"recall@5_{qt}_q"] = round(statistics.mean(x["evidence_recall@5"] for x in sub), 3) if sub else None
        row["top5_tokens_mean"] = round(statistics.mean(x["top5_tokens"] for x in rs))
        summary.append(row)

    # ---- paired comparison vs A (per question, recall@5) ----
    paired = []
    base = {(r["filters"], r["method"], r["qid"]): r["evidence_recall@5"] for r in per_q if r["variant"] == "A"}
    for (v, fm, m), rs in groups.items():
        if v == "A" or not base:
            continue
        d = [x["evidence_recall@5"] - base[(fm, m, x["qid"])] for x in rs]
        paired.append({"variant": v, "filters": fm, "method": m, "wins": sum(x > 0 for x in d),
                       "losses": sum(x < 0 for x in d), "ties": sum(x == 0 for x in d), "mean_delta_recall@5": round(statistics.mean(d), 3)})

    for name, rows in (("per_question", per_q), ("summary", summary), ("paired_vs_A", paired)):
        if rows:
            with open(out / f"{name}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    (out / "builds.json").write_text(json.dumps({"builds": builds, "args": vars(a), "n_questions": len(gold),
                                                 "table_questions": sorted(tq)}, indent=2))

    lines = [f"# Chunking experiment ({time.strftime('%Y-%m-%d %H:%M')})", "",
             f"Gold: {a.gold} ({len(gold)} questions, {len(tq)} table questions). Embedder: {a.embedder}. Body budget: {a.max_tokens} tokens.", "",
             "## Builds", "", "| variant | chunks | table chunks | mean tok | max tok | >512 |", "|---|---|---|---|---|---|"]
    lines += [f"| {v} | {b['n_chunks']} | {b['n_table_chunks']} | {b['mean_tokens']} | {b['max_tokens']} | {b['over_512']} |" for v, b in builds.items()]
    lines += ["", "## Results", "", "| variant | filters | method | recall@5 | recall@10 | MRR | table-q recall@5 | text-q recall@5 | top-5 tokens | F: parent recall@5 | F: parent top-5 tokens |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in sorted(summary, key=lambda s: (s["filters"], s["method"], s["variant"])):
        lines.append(f"| {s['variant']} | {s['filters']} | {s['method']} | {s['evidence_recall@5']} | {s['evidence_recall@10']} | {s['mrr']} | "
                     f"{s['recall@5_table_q']} | {s['recall@5_text_q']} | {s['top5_tokens_mean']} | {s['parent_recall@5']} | {round(s['parent_top5_tokens'])} |")
    if paired:
        lines += ["", "## Paired vs A (recall@5, per question)", "", "| variant | filters | method | wins | losses | ties | mean Δ |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {p['variant']} | {p['filters']} | {p['method']} | {p['wins']} | {p['losses']} | {p['ties']} | {p['mean_delta_recall@5']} |"
                  for p in sorted(paired, key=lambda p: (p["filters"], p["method"], p["variant"]))]
    lines += ["", f"Noise note: {len(gold)} questions -> one question ≈ {1/len(gold):.3f}; treat |Δ| < ~0.07 as noise."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
