"""Cost / latency / accuracy table across reader runs (mentor 11/12: "what does it cost to reach a 0.9 retrieval
rate?"). Reads eval/results/round1/reader/<run>/summary.json and per_question.csv; makes no API calls.

    python scripts/cost_table.py                       # all runs, prices from config.yaml
    python scripts/cost_table.py --target 0.9          # cheapest run that reaches the target, per metric
    python scripts/cost_table.py --price-in 0.1 --price-out 0.4    # what-if: a cheaper reader model

Columns
  NAA                 numerical answer accuracy (Eval's grader)
  num. retrieval      share of number questions whose every input figure was in the reader's context (strict)
  BRAA                balanced refusal accuracy
  in / out tok        reader tokens per question (retrieval itself uses a local embedding model: no API tokens)
  $/1k q              reader cost per 1,000 questions at the given prices
  reader p50 / p95    reader call latency, from runs made after 11/16 (older runs: n/a)
"""
from __future__ import annotations

import argparse, csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_runs(base: Path) -> list[dict]:
    runs = []
    for d in sorted(p for p in base.iterdir() if (p / "summary.json").exists()):
        s = json.loads((d / "summary.json").read_text())
        rows = list(csv.DictReader(open(d / "per_question.csv", encoding="utf-8")))
        nums = [r for r in rows if r["group"] == "number"]
        got = [r for r in nums if r.get("retrieved_all_figures") in ("True", "False")]
        n = s["n_questions"]
        pq = s.get("per_question") or {}
        runs.append({
            "run": d.name, "model": s["model"], "prompt": s["prompt"], "top_k": s["top_k"], "multi": s.get("multi", False),
            "n": n, "naa": s["numbers"]["naa"], "n_num": len(nums),
            "num_retrieval": sum(r["retrieved_all_figures"] == "True" for r in got) / len(got) if got else None,
            "braa": s["raa"]["balanced_raa"],
            "in_tok": s["tokens"].get("prompt_tokens", 0) / n, "out_tok": s["tokens"].get("completion_tokens", 0) / n,
            "reader_p50": pq.get("reader_latency_ms_p50"), "reader_p95": pq.get("reader_latency_ms_p95"),
            "retrieval_p50": pq.get("retrieval_ms_p50"),
        })
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="eval/results/round1/reader")
    ap.add_argument("--price-in", type=float, default=None)
    ap.add_argument("--price-out", type=float, default=None)
    ap.add_argument("--target", type=float, default=0.9)
    ap.add_argument("--out", default="eval/results/cost")
    a = ap.parse_args()
    from rag.config import load_config
    gen = load_config().get("generation", {})
    p_in = a.price_in if a.price_in is not None else gen.get("price_per_1m_input")
    p_out = a.price_out if a.price_out is not None else gen.get("price_per_1m_output")
    if p_in is None or p_out is None:
        raise SystemExit("set generation.price_per_1m_input/output in config.yaml or pass --price-in/--price-out")

    runs = load_runs(ROOT / a.runs)
    for r in runs:
        r["usd_per_1k"] = (r["in_tok"] * p_in + r["out_tok"] * p_out) / 1e6 * 1000
    runs.sort(key=lambda r: r["usd_per_1k"])
    base = min(runs, key=lambda r: r["usd_per_1k"])

    f = lambda x, d=3: "n/a" if x is None else f"{x:.{d}f}"  # noqa: E731
    md = [f"# Reader runs: cost vs accuracy (prices: ${p_in}/M input, ${p_out}/M output)\n",
          "| run | k | multi | NAA | num. retrieval | BRAA | in tok/q | out tok/q | $/1k q | Δ NAA per +$1/1k q | reader p50 / p95 ms |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        dc = r["usd_per_1k"] - base["usd_per_1k"]
        slope = f"{(r['naa'] - base['naa']) / dc:+.3f}" if dc > 1e-9 else "-"
        lat = "n/a" if r["reader_p50"] is None else f"{r['reader_p50']} / {r['reader_p95']}"
        md.append(f"| {r['run']} | {r['top_k']} | {'yes' if r['multi'] else 'no'} | {f(r['naa'])} | {f(r['num_retrieval'])} | "
                  f"{f(r['braa'])} | {r['in_tok']:,.0f} | {r['out_tok']:,.0f} | {r['usd_per_1k']:.2f} | {slope} | {lat} |")
    md.append("")
    for metric, label in (("num_retrieval", "number retrieval (all input figures in context)"), ("naa", "NAA")):
        ok = [r for r in runs if r[metric] is not None and r[metric] >= a.target]
        if ok:
            c = min(ok, key=lambda r: r["usd_per_1k"])
            md.append(f"- Cheapest run with {label} >= {a.target}: **{c['run']}** ({f(c[metric])}) at "
                      f"${c['usd_per_1k']:.2f} per 1,000 questions, {c['in_tok']:,.0f} input tokens per question.")
        else:
            md.append(f"- No run reaches {label} >= {a.target}.")
    md.append("- Retrieval (BM25 + local bge-small embeddings) makes no API calls; the reader's input tokens, which grow "
              "with top_k and with retrieve_multi, are the whole marginal cost.")
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "cost_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(out / "cost_table.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(runs[0]))
        w.writeheader()
        w.writerows(runs)
    print("\n".join(md))


if __name__ == "__main__":
    main()
