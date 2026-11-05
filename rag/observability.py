"""Tracing hook for retrieve(): one LangSmith "retriever" span per call when tracing is on.

The Agent team runs LangGraph with LangSmith. When their process has tracing enabled
(LANGSMITH_TRACING=true, or LANGCHAIN_TRACING_V2=true) and calls rag.retrieve.retrieve() inside a traced
node, this span nests under their trace automatically and shows: query, filters, top_k, trace_id, backend,
index_version, latency and the returned chunks (as LangSmith retriever documents).

Without the `langsmith` package, or with tracing off, `traced_retriever` returns the function unchanged,
so RAG has no hard dependency on LangSmith.
"""
from __future__ import annotations

import functools
import os
from typing import Callable


def tracing_enabled() -> bool:
    flag = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2") or ""
    return flag.strip().lower() in {"1", "true", "yes"}


def _as_documents(outputs):
    """LangSmith renders retriever runs from [{page_content, type, metadata}]."""
    results = outputs.get("output", outputs) if isinstance(outputs, dict) else outputs
    if not isinstance(results, list):
        return outputs
    docs = []
    for r in results:
        meta = {k: v for k, v in r.items() if k not in ("text", "metadata")}
        meta.update({k: v for k, v in (r.get("metadata") or {}).items() if k != "parent_text"})
        docs.append({"page_content": r.get("text", ""), "type": "Document", "metadata": meta})
    return {"documents": docs}


def traced_retriever(fn: Callable) -> Callable:
    """Wrap a retrieve(query, filters, top_k, trace_id) function in a LangSmith retriever span."""
    try:
        from langsmith import traceable
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:  # pragma: no cover - langsmith is optional
        return fn

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        results = fn(*args, **kwargs)
        if tracing_enabled():
            run = get_current_run_tree()
            if run is not None and results:
                m = results[0].get("metadata", {})
                run.add_metadata({
                    "rag_index_version": results[0].get("index_version"),
                    "rag_backend": m.get("retrieval_backend"),
                    "rag_method": m.get("retrieval_method"),
                    "rag_request_id": m.get("request_id"),
                    "trace_id": m.get("trace_id"),
                    "n_results": len(results),
                })
        return results

    return traceable(run_type="retriever", name="rag.retrieve", process_outputs=_as_documents)(inner)
