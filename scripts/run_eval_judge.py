"""Run the Evaluation team's narrative judge on RAG's answers, unchanged except for API plumbing.

    git clone https://github.com/thomassong0604-oss/kpmg-eval ../kpmg-eval          # once, next to this repo
    python scripts/run_eval_judge.py --answers <answer_blocks.jsonl> --tag rag_final_v1 --dry-run
    python scripts/run_eval_judge.py --answers <answer_blocks.jsonl> --tag rag_final_v1          # needs the key

Eval's script (kpmg-eval/Week 8/scripts/run_narrative_judge.py) does the work: its prompts, rubric, quote guard,
gold set (Gold v2.2, 30 narrative questions) and output files are used as they are. This wrapper only
  1. loads OPENAI_API_KEY / OPENAI_BASE_URL from this repo's .env,
  2. retries a call without temperature=0 when the model rejects that parameter (gpt-6 family), and
  3. writes eval/results/judge/<tag>_run.json: judge model, eval repo commit, prompt hash, whether temperature was
     dropped, so the deviation is on record.
Results land in Eval's repo as results/narrative_judge_<tag>.json (verdicts only, no answer text), plus, on a dry
run, private/judge_prompts_<tag>.jsonl and the blank hand-labelling sheet private/narrative_labels_<tag>_blank.csv.
Use a judge model other than the reader (gpt-6.1-terra) to avoid self-preference; default gpt-6-sol.
"""
from __future__ import annotations

import argparse, importlib.util, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2).strip("'\"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-repo", default=str(ROOT.parent / "kpmg-eval"))
    ap.add_argument("--answers", required=True)
    ap.add_argument("--chunks", default=str(ROOT / "data/round1/index_C1/chunks.jsonl"))
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    week8 = Path(a.eval_repo) / "Week 8"
    script = week8 / "scripts" / "run_narrative_judge.py"
    if not script.exists():
        sys.exit(f"Eval's judge not found at {script}. Clone it: git clone https://github.com/thomassong0604-oss/kpmg-eval {a.eval_repo}")
    load_env()
    spec = importlib.util.spec_from_file_location("eval_narrative_judge", script)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(week8))
    spec.loader.exec_module(mod)

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
    sys.argv = ["run_narrative_judge.py", "--answers", str(Path(a.answers).resolve()), "--chunks",
                str(Path(a.chunks).resolve()), "--provider", "openai", "--model", a.model, "--tag", a.tag] + \
               (["--dry-run"] if a.dry_run else [])
    mod.main()

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=week8).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None
    rec = {"tag": a.tag, "answers": a.answers, "judge_model": a.model, "dry_run": a.dry_run,
           "eval_repo_commit": commit, "prompt_sha": getattr(mod, "PROMPT_SHA", None), "calls": state["calls"],
           "temperature_dropped_on": state["temperature_dropped"],
           "deviation": "none" if not state["temperature_dropped"] else
           "temperature=0 rejected by the model; those calls ran at the model default"}
    out = ROOT / "eval/results/judge"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.tag}_run.json").write_text(json.dumps(rec, indent=1))
    res = week8 / "results" / f"narrative_judge_{a.tag}.json"
    if res.exists() and not a.dry_run:
        s = json.loads(res.read_text())
        print(json.dumps({k: s[k] for k in s if k != "questions"}, indent=1))
    print(f"run record -> {out / (a.tag + '_run.json')}")


if __name__ == "__main__":
    main()
