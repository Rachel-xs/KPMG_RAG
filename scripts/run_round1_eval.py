"""Round 1 retrieval evaluation on Eval's Gold Set v2 (155 questions), evidence level (no reader model).

    python scripts/run_round1_eval.py --index data/round1/index_C1

Inputs (pinned copies from thomassong0604-oss/kpmg-eval @ 41823f9, Week 8):
    eval/round1/benchmark_v2.jsonl      Gold Set v2
    eval/round1/rag_anchor_fixes.csv    Eval's fixes to our Gold v1 anchors (narrow / remove / drop)

Scoring (same rules as Eval's scripts/run_side_by_side.py, plus a stricter variant):
  number questions  every input figure of the gold answer appears in the top k, as printed
                    (USD in millions with commas, or in thousands for filers that print thousands;
                    per-share to cents; ratios as %). "strict" also requires the chunk to come from
                    one of the question's gold filings (accession).
  anchored prose    every gold evidence item (after anchor fixes) is matched by a top-k chunk:
                    same ticker/form/accession and the chunk contains all of its `contains` strings.
  no anchor yet     prose questions Eval has not anchored yet are listed, not scored.
  unanswerable      refusal questions: we record whether RAG returns nothing (it should not be the
                    only abstain signal) and the score margins, as input for the "weak result" signal.
  graph route       Exhibit 21 relationship questions (route_expected = graph). Exhibits are not in the
                    round-1 corpus, so these are reported separately and left to GraphRAG.
  NTAP 10-Q         the 3 questions Eval marks review_required (NetApp 10-Q left out of round 1)
                    are reported separately and excluded from the headline.

Writes eval/results/round1/: summary.json, summary.md, per_question.csv, gold_v2_rag.jsonl.
Retrieval vs reading errors: this run is retrieval only. A question whose figures are in the top k but
is answered wrongly later is a reading error; one whose figures are missing is a retrieval error.
"""
from __future__ import annotations

import argparse, csv, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag.retrieve import Retriever  # noqa: E402

KS = (5, 8, 10)
NTAP_10Q = "0001193125-26-380207"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("—", "-")).lower()


# ------------------------------------------------------------------ gold
def apply_fixes(gold: list[dict], fixes_path: Path) -> tuple[list[dict], Counter, list[str]]:
    """Apply Eval's anchor fixes to the questions' rag_evidence. Returns gold, counts, pending notes."""
    by_q = defaultdict(list)
    for r in csv.DictReader(open(fixes_path, encoding="utf-8")):
        by_q[r["qid"]].append(r)
    done, pending = Counter(), []
    for q in gold:
        for r in by_q.get(q["qid"], []):
            old = [s.strip() for s in r["rag_anchor"].split("|") if s.strip()]
            ev = next((e for e in q.get("rag_evidence") or [] if [c.strip() for c in e["contains"]] == old), None)
            if r["action"] == "drop":
                done["drop (question not in v2)"] += 1
                continue
            if ev is None:
                done[f"{r['action']}: already applied by Eval in v2"] += 1
                continue
            if r["action"] == "remove":
                q["rag_evidence"].remove(ev)
                done["remove"] += 1
            elif r["action"] == "narrow" and r["suggested_anchor"] and "|" in r["suggested_anchor"]:
                ev["contains"] = [s.strip() for s in r["suggested_anchor"].split("|") if s.strip()]
                ev["anchor_fix"] = "narrowed by Eval"
                done["narrow (row label added)"] += 1
            else:
                ev["anchor_fix"] = "pending: row label to add"
                pending.append(f"{q['qid']}: {r['rag_anchor']} ({r['why']})")
                done["narrow pending (no label given)"] += 1
    return gold, done, pending


def kind(q: dict) -> str:
    if q.get("snapshot_status") == "review_required":
        return "ntap_10q_excluded"
    if q.get("route_expected") == "graph":
        return "graph_route"
    if not q["answerable"] or q["answer_type"] == "refusal":
        return "unanswerable"
    if q["answer_type"] == "exact_numeric" and q.get("facts") and q.get("fact_values"):
        return "number"
    if [c for e in q.get("rag_evidence") or [] for c in e["contains"]]:
        return "anchored_prose"
    return "prose_no_anchor"


def figures(q: dict) -> list[list[str]]:
    """Each input number as printed; a list of acceptable spellings per number."""
    a = q["answer"]
    first = None
    if q["type"] in ("extraction", "segment") and len(q["facts"]) == 1 and a.get("required_points"):
        first = re.sub(r"[^0-9.,%]", "", a["required_points"][0]).strip(".,") or None
    out = []
    for k, v in zip(q["facts"], q["fact_values"].values()):
        v = abs(float(v))
        if k["unit"] == "USD":
            out.append([f"{v / 1e6:,.0f}", f"{v / 1e3:,.0f}", f"{v / 1e6:,.1f}"])
        elif k["unit"] == "USD/shares":
            out.append([f"{v:.2f}"])
        elif k["unit"] == "pure":
            out.append([f"{v * 100:.0f}%", f"{v * 100:.1f}%"])
        else:
            out.append([f"{v:,.0f}"])
    if first:  # Eval's spelling first; the unit-based spellings cover filers that print thousands
        out = [[first] + out[0]] if len(out) == 1 else [[first]]
    return out


def acc(r: dict) -> str:
    return r.get("accession_number") or r.get("accession") or ""


def ev_hits(e: dict, r: dict) -> bool:
    for key in ("ticker", "form", "accession"):
        got = acc(r) if key == "accession" else r.get(key)
        if e.get(key) and str(got or "") != str(e[key]):
            return False
    t = norm(r.get("text") or "")
    return all(norm(c) in t for c in e["contains"])


# ------------------------------------------------------------------ scoring
def score(q: dict, res: list[dict]) -> dict:
    k_ = kind(q)
    out = {"n_returned": len(res)}
    if res:
        s = [r.get("score") or 0.0 for r in res]
        out["top1_score"] = round(s[0], 5)
        out["top1_margin"] = round(s[0] - s[1], 5) if len(s) > 1 else None
    gold_acc = {f["accession"] for f in q.get("facts") or []} | {e.get("accession") for e in q.get("rag_evidence") or [] if e.get("accession")}
    for k in KS:
        top = res[:k]
        if k_ in ("number", "ntap_10q_excluded") and q.get("facts") and q["answer_type"] == "exact_numeric":
            blob = norm(" ".join(r["text"] for r in top))
            blob_s = norm(" ".join(r["text"] for r in top if acc(r) in gold_acc))
            figs = figures(q)
            out[f"loose@{k}"] = all(any(norm(f) in blob for f in alts) for alts in figs)
            out[f"strict@{k}"] = all(any(norm(f) in blob_s for f in alts) for alts in figs)
            if k == 8:
                ds = [d["value"] for d in (q.get("gold") or {}).get("distractors", []) if d.get("value")]
                out["distractor_shown@8"] = any(f"{abs(d) / 1e6:,.0f}" in blob for d in ds) if ds else None
        evs = q.get("rag_evidence") or []
        anchored = [e for e in evs if e["contains"]]
        if anchored and k_ != "unanswerable":
            sat = sum(any(ev_hits(e, r) for r in top) for e in anchored)
            out[f"anchor_recall@{k}"] = round(sat / len(anchored), 4)
            if k_ == "anchored_prose":
                blob = norm(" ".join(r["text"] for r in top))
                out[f"loose@{k}"] = all(norm(c) in blob for e in anchored for c in e["contains"])
                out[f"strict@{k}"] = sat == len(anchored)
    if res:
        out["top_accessions"] = ";".join(dict.fromkeys(acc(r) for r in res[:8]))
    return out


def rate(rows, key):
    xs = [r[key] for r in rows if r.get(key) is not None]
    if not xs:
        return None
    return {"rate": round(sum(xs) / len(xs), 3), "n": len(xs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/round1/index_C1")
    ap.add_argument("--gold", default="eval/round1/benchmark_v2.jsonl")
    ap.add_argument("--fixes", default="eval/round1/rag_anchor_fixes.csv")
    ap.add_argument("--methods", default="hybrid,bm25,dense")
    ap.add_argument("--out", default="eval/results/round1")
    a = ap.parse_args()

    gold = [json.loads(l) for l in open(ROOT / a.gold, encoding="utf-8")]
    gold, fix_counts, pending = apply_fixes(gold, ROOT / a.fixes)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "gold_v2_rag.jsonl", "w", encoding="utf-8") as fh:
        for q in gold:
            fh.write(json.dumps({k: q[k] for k in ("qid", "question", "type", "answer_type", "answerable",
                                                   "tickers", "filters", "rag_evidence", "snapshot_status")
                                 if k in q}, ensure_ascii=False) + "\n")

    retr = Retriever(ROOT / a.index, log_dir=None)
    methods = [m for m in a.methods.split(",") if m]
    rows = []
    for q in gold:
        row = {"qid": q["qid"], "kind": kind(q), "type": q["type"], "route_expected": q.get("route_expected"),
               "tickers": "|".join(q["tickers"]), "question": q["question"]}
        for m in methods:
            for flt_name, flt in (("filtered", q.get("filters") or None), ("nofilter", None)):
                if flt_name == "nofilter" and m != "hybrid":
                    continue
                env = retr.search(q["question"], filters=flt, top_k=max(KS), method=m)
                res = env["results"]
                for key, val in score(q, res).items():
                    row[f"{m}_{flt_name}_{key}"] = val
                if flt_name == "filtered" and m == "hybrid":
                    row["filter_warning"] = "; ".join(env.get("warnings") or [])
        rows.append(row)

    groups = defaultdict(list)
    for r in rows:
        groups[r["kind"]].append(r)
    summary = {"gold": a.gold, "n_questions": len(rows), "index": a.index,
               "index_version": retr.meta.get("index_version"), "embedder": retr.meta.get("embedder"),
               "by_kind_counts": {k: len(v) for k, v in groups.items()},
               "anchor_fixes": dict(fix_counts), "anchor_fixes_pending": pending, "headline": {}, "by_company": {},
               "by_type": {}, "unanswerable": {}}
    scored = groups["number"] + groups["anchored_prose"]
    for m in methods:
        pre = f"{m}_filtered_"
        h = {}
        for k in KS:
            h[f"all_scored_loose@{k}"] = rate(scored, pre + f"loose@{k}")
            h[f"all_scored_strict@{k}"] = rate(scored, pre + f"strict@{k}")
            h[f"number_loose@{k}"] = rate(groups["number"], pre + f"loose@{k}")
            h[f"number_strict@{k}"] = rate(groups["number"], pre + f"strict@{k}")
            h[f"prose_strict@{k}"] = rate(groups["anchored_prose"], pre + f"strict@{k}")
            h[f"anchor_recall@{k}"] = rate(scored, pre + f"anchor_recall@{k}")
        h["number_distractor_shown@8"] = rate(groups["number"], pre + "distractor_shown@8")
        summary["headline"][m] = h
    summary["headline"]["hybrid_nofilter"] = {f"all_scored_strict@{k}": rate(scored, f"hybrid_nofilter_strict@{k}") for k in KS}
    for r in scored:  # a question naming several companies counts once, under "multi-company"
        t = r["tickers"].split("|")
        summary["by_company"].setdefault(t[0] if len(t) == 1 else "multi-company", []).append(r)
        summary["by_type"].setdefault(r["type"], []).append(r)
    summary["non_msft_single_company"] = rate([r for r in scored if r["tickers"] not in ("MSFT",) and "|" not in r["tickers"]],
                                              "hybrid_filtered_strict@10")
    for d in ("by_company", "by_type"):
        summary[d] = {k: {"n": len(v), "strict@10": rate(v, "hybrid_filtered_strict@10"),
                          "loose@10": rate(v, "hybrid_filtered_loose@10")} for k, v in sorted(summary[d].items())}
    un = groups["unanswerable"]
    summary["unanswerable"] = {"n": len(un), "empty_results": sum(1 for r in un if r.get("hybrid_filtered_n_returned") == 0)}
    misses = [r["qid"] for r in scored if r.get("hybrid_filtered_strict@10") is False]
    summary["retrieval_misses_strict@10"] = misses
    summary["not_scored_prose_no_anchor"] = [r["qid"] for r in groups["prose_no_anchor"]]
    summary["ntap_10q_excluded"] = [r["qid"] for r in groups["ntap_10q_excluded"]]
    summary["graph_route_excluded"] = [r["qid"] for r in groups["graph_route"]]
    summary["filter_warnings"] = {r["qid"]: r["filter_warning"] for r in rows if r.get("filter_warning")}

    with open(out / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
        cols = list(dict.fromkeys(c for r in rows for c in r))
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    json.dump(summary, open(out / "summary.json", "w"), indent=1, ensure_ascii=False)

    def f(x):
        return "-" if not x else f"{x['rate']:.3f} (n={x['n']})"
    md = [f"# Round 1 retrieval results (Gold Set v2, evidence level)\n",
          f"Index `{a.index}`; {len(rows)} questions: " + ", ".join(f"{k} {len(v)}" for k, v in groups.items()) + ".\n",
          "| method | k | all scored, strict | numbers, strict | numbers, loose | anchored prose, strict |",
          "|---|---|---|---|---|---|"]
    for m in methods:
        for k in KS:
            h = summary["headline"][m]
            md.append(f"| {m} | {k} | {f(h[f'all_scored_strict@{k}'])} | {f(h[f'number_strict@{k}'])} | "
                      f"{f(h[f'number_loose@{k}'])} | {f(h[f'prose_strict@{k}'])} |")
    md += ["", "Hybrid without filters, all scored, strict: " +
           ", ".join(f"@{k} {f(summary['headline']['hybrid_nofilter'][f'all_scored_strict@{k}'])}" for k in KS), "",
           f"Non-MSFT single-company questions (hybrid, filtered, strict@10): {f(summary['non_msft_single_company'])}", "",
           "## By company (hybrid, filtered, k=10)", "", "| ticker | n | strict | loose |", "|---|---|---|---|"]
    md += [f"| {t} | {v['n']} | {f(v['strict@10'])} | {f(v['loose@10'])} |" for t, v in summary["by_company"].items()]
    md += ["", "## By question type (hybrid, filtered, k=10)", "", "| type | n | strict | loose |", "|---|---|---|---|"]
    md += [f"| {t} | {v['n']} | {f(v['strict@10'])} | {f(v['loose@10'])} |" for t, v in summary["by_type"].items()]
    md += ["", f"Wrong-period figure also in top 8 (numbers): {f(summary['headline']['hybrid']['number_distractor_shown@8'])}",
           f"Unanswerable: {un and len(un)} questions, {summary['unanswerable']['empty_results']} with an empty result.",
           f"Retrieval misses (strict@10): {', '.join(misses) or 'none'}",
           f"Not scored yet (prose without Eval anchors): {', '.join(summary['not_scored_prose_no_anchor']) or 'none'}",
           f"Excluded (NetApp 10-Q not in round 1): {', '.join(summary['ntap_10q_excluded'])}",
           f"Left to GraphRAG (Exhibit 21 relationship questions, exhibits not indexed): {', '.join(summary['graph_route_excluded'])}",
           f"Anchor fixes applied: {dict(fix_counts)}"]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nWrote {out}/summary.md, summary.json, per_question.csv, gold_v2_rag.jsonl")


if __name__ == "__main__":
    main()
