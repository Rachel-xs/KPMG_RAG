"""Query rewriting vs Agent extraction (exploratory). Step 2 of 3: answer the messy-wording suite with one filter arm.

Runs scripts/run_round1_reader.py unchanged (preset final_v1, Chroma) and only swaps where the retrieval filters come
from. Nothing in the frozen code is edited: this wrapper imports it and replaces filters_for() for the file arms.

  none      search the whole index                     (built-in --filters none)
  precheck  rule-based extractor + rag.coverage        (built-in --filters precheck)
  gold      the suite's own filters (upper bound)      (built-in --filters gold)
  rag_llm   filters from eval/results/query_rewrite/filters_rag_llm.jsonl (step 1)
  agents    filters from eval/results/query_rewrite/filters_agents.jsonl  (step 1)
  agents_precheck  POST-HOC (added after seeing the arms above): Agents' companies + rule periods -> check_coverage

    python scripts/qr_run_arm.py --arm none
    python scripts/qr_run_arm.py --arm rag_llm --limit 5      # smoke test

All arms share one reader cache (seeded from eval/results/suites/cache.jsonl), so contexts already answered in the
D runs cost nothing. Output: eval/results/query_rewrite/<arm>/<tag>/ (summary.md, summary.json, per_question.csv,
answer_blocks.jsonl).
"""
from __future__ import annotations

import argparse, csv, importlib.util, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "eval/results/query_rewrite"
CACHE = BASE / "cache.jsonl"
SEED = ROOT / "eval/results/suites/cache.jsonl"
SUITE = "eval/suites/messy_wording_v1.jsonl"
BUILTIN = {"none": "none", "precheck": "precheck", "gold": "gold"}


def load_reader_module():
    spec = importlib.util.spec_from_file_location("run_round1_reader", ROOT / "scripts/run_round1_reader.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_round1_reader"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["none", "precheck", "gold", "rag_llm", "agents", "agents_precheck"], required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    BASE.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists() and SEED.exists():
        shutil.copy2(SEED, CACHE)
    rr = load_reader_module()

    class SharedCacheReader(rr.Reader):  # every arm reads and appends one cache
        def __init__(self, model, prompt, cache_path, *args, **kw):
            super().__init__(model, prompt, CACHE, *args, **kw)
    rr.Reader = SharedCacheReader

    mode = BUILTIN.get(a.arm, "gold")
    if a.arm not in BUILTIN:
        fpath = BASE / f"filters_{a.arm}.jsonl"
        if not fpath.exists():
            raise SystemExit(f"{fpath} missing: run scripts/qr_extract_filters.py --arm {a.arm} first")
        table = {}
        for line in open(fpath, encoding="utf-8"):
            r = json.loads(line)
            table[r["qid"]] = r

        def filters_for(q, _mode, _cov=None):
            r = table.get(q["qid"])
            if r is None:
                raise SystemExit(f"no extracted filters for {q['qid']} in {fpath.name}")
            if r.get("declined"):
                return None, {"status": r["precheck_status"], "message": r["message"]}
            return r.get("filters") or None, None
        rr.filters_for = filters_for

    out = BASE / a.arm
    argv = ["run_round1_reader.py", "--preset", "final_v1", "--backend", "chroma", "--gold", SUITE,
            "--out", str(out.relative_to(ROOT)), "--filters", mode]
    if a.limit:
        argv += ["--limit", str(a.limit)]
    if a.dry_run:
        argv += ["--dry-run"]
    sys.argv = argv
    print(f"arm {a.arm}: run_round1_reader.py {' '.join(argv[1:])}")
    rr.main()

    # label the output with the arm (the reader only knows gold / none / precheck)
    for d in out.iterdir():
        if not d.is_dir() or not (d / "per_question.csv").exists():
            continue
        rows = list(csv.DictReader(open(d / "per_question.csv", encoding="utf-8")))
        for r in rows:
            r["filter_mode"] = a.arm
        with open(d / "per_question.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        s = json.load(open(d / "summary.json"))
        s["filter_arm"] = a.arm
        s["index_note"] = "chroma_C1 7a7ad9801f86, persisted (fixed) index"
        json.dump(s, open(d / "summary.json", "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
