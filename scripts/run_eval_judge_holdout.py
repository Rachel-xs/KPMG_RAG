"""gpt-6-sol judge on the holdout narrative answers (Eval's Week 8 script, rubric unchanged), for human-vs-judge kappa.

    python scripts/run_eval_judge_holdout.py --dry-run     # prompts only, no key, no cost
    python scripts/run_eval_judge_holdout.py               # 22 calls (HB-016 was not answered, so skipped)

Eval's script reads Gold v2.2 only; this wrapper swaps in the sealed holdout questions (narrative only) and is otherwise
run_eval_judge.py: key from .env, temperature=0 dropped when the model rejects it, run record in eval/results/judge/.
Verdicts go to ../kpmg-eval/Week 8/results/narrative_judge_holdout_{A_final_v1,B_final_v2}.json (local clone, untracked;
no answer text). Scoring only: the RAG system is not run again. Do not show the verdicts to the raters.
"""
from __future__ import annotations

import argparse, glob, importlib.util, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from run_eval_judge import load_env  # noqa: E402

RUNS = [("holdout_A_final_v1", "holdout_A.jsonl", "eval/results/holdout_A/final_v1_*/answer_blocks.jsonl"),
        ("holdout_B_final_v2", "holdout_B.jsonl", "eval/results/holdout_B/final_v2_*/answer_blocks.jsonl")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-repo", default=str(ROOT.parent / "kpmg-eval"))
    ap.add_argument("--holdout-dir", default=str(ROOT.parent / "holdout_private"))
    ap.add_argument("--chunks", default=str(ROOT / "data/round1/index_C1/chunks.jsonl"))
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    week8 = Path(a.eval_repo) / "Week 8"
    spec = importlib.util.spec_from_file_location("eval_narrative_judge", week8 / "scripts" / "run_narrative_judge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(week8))
    spec.loader.exec_module(mod)
    load_env()

    state = {"temperature_dropped": 0, "calls": 0}
    original = mod.call

    def call(provider, model, prompt):
        state["calls"] += 1
        try:
            return original(provider, model, prompt)
        except Exception as e:  # noqa: BLE001
            if provider != "openai" or "temperature" not in str(e):
                raise
            state["temperature_dropped"] += 1
            from openai import OpenAI
            r = OpenAI().chat.completions.create(model=model, response_format={"type": "json_object"},
                                                 messages=[{"role": "system", "content": mod.SYSTEM},
                                                           {"role": "user", "content": prompt}])
            return json.loads(r.choices[0].message.content)

    mod.call = call
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=week8).stdout.strip()
    for tag, gold_name, pattern in RUNS:
        answers = sorted(glob.glob(str(ROOT / pattern)))
        if len(answers) != 1:
            sys.exit(f"{tag}: expected one answer file for {pattern}, found {answers}")
        gold_path = Path(a.holdout_dir) / gold_name

        def load(args, gold_path=gold_path):
            gold = {q["qid"]: q for q in map(json.loads, open(gold_path)) if q["answer_type"] == "narrative"}
            ans = {b["qid"]: b for b in map(json.loads, open(args.answers)) if b["qid"] in gold}
            chunks = {}
            for line in open(args.chunks):
                c = json.loads(line)
                chunks[c["chunk_id"]] = c["text"]
            return gold, ans, chunks

        mod.load = load
        before = dict(state)
        sys.argv = ["run_narrative_judge.py", "--answers", answers[0], "--chunks", a.chunks, "--provider", "openai",
                    "--model", a.model, "--tag", tag] + (["--dry-run"] if a.dry_run else [])
        mod.main()
        rec = {"tag": tag, "answers": str(Path(answers[0]).relative_to(ROOT)), "gold": gold_name, "judge_model": a.model,
               "dry_run": a.dry_run, "eval_repo_commit": commit, "prompt_sha": getattr(mod, "PROMPT_SHA", None),
               "calls": state["calls"] - before["calls"],
               "temperature_dropped_on": state["temperature_dropped"] - before["temperature_dropped"],
               "note": "Eval's Week 8 judge with the holdout questions swapped in for Gold v2.2; scoring only"}
        out = ROOT / "eval/results/judge"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{tag}_run.json").write_text(json.dumps(rec, indent=1))
        print(f"run record -> {out / (tag + '_run.json')}")


if __name__ == "__main__":
    main()
