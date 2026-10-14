"""Baseline "answer with citations" over retrieved chunks (optional; needs OPENAI_API_KEY).

The Agent team may own final generation; this exists so our arm can be scored end-to-end
and so token/cost per answer is logged from day one.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SYSTEM_PROMPT = """You answer questions about companies using ONLY the numbered SEC filing excerpts provided.
Rules:
- Cite every factual claim with the excerpt number in brackets, e.g. [2]. Use several if needed: [1][3].
- Quote numbers exactly as they appear, with units and the period they refer to.
- If the excerpts do not contain the answer, say "The provided filings do not contain this information." Do not guess.
- Be concise."""


def format_context(results: list[dict]) -> str:
    parts = []
    for i, r in enumerate(results, start=1):
        m = r.get("metadata", {})
        period = f"period ended {r['reporting_period_end']}" if r.get("reporting_period_end") else ""
        title = m.get("section_title") or ""
        parts.append(f"[{i}] {r['company_name']} ({r['ticker']}) {r['form']} {period}, {r['section'] or ''} {title}\n{r['text']}")
    return "\n\n---\n\n".join(parts)


def answer_with_citations(question: str, results: list[dict], cfg: dict, log_dir: Path | None = None) -> dict:
    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    gen = cfg.get("generation", {})
    model = gen.get("model", "gpt-4o-mini")
    t0 = time.perf_counter()
    resp = OpenAI().chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Excerpts:\n\n{format_context(results)}\n\nQuestion: {question}"},
        ],
    )
    usage = resp.usage
    p_in, p_out = gen.get("price_per_1m_input"), gen.get("price_per_1m_output")
    cost = (usage.prompt_tokens * p_in + usage.completion_tokens * p_out) / 1e6 if p_in is not None and p_out is not None else None
    out = {
        "question": question,
        "answer": resp.choices[0].message.content,
        "citations": [
            {"n": i, "chunk_id": r["chunk_id"], "source_url": r["source_url"], **{k: r[k] for k in ("ticker", "form", "accession_number", "reporting_period_end", "section")}}
            for i, r in enumerate(results, start=1)
        ],
        "model": model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost_usd": cost,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        with open(Path(log_dir) / "generation.jsonl", "a") as f:
            f.write(json.dumps({k: v for k, v in out.items() if k != "citations"} | {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return out
