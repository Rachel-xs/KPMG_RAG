# 从这里开始（中文速览）

## 这个 repo 做什么
把 SEC 的 10-K / 10-Q 切成带 metadata 的 chunk，建 BM25 + 向量索引，提供 `retrieve()` 给 Agent 组调用，并用 gold set 打分。

## 第一次运行（在自己的 Mac 上）
```bash
cd KPMG_RAG
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python -m rag.cli demo   # 用两份假文件跑通自定义baseline全流程
cp .env.example .env   # 把 SEC_USER_AGENT 改成你的名字和邮箱
```

## Data RDS → Chroma MVP

先按 `scripts/export_rds_chunks.sql` 从 Data 组的 `sec.chunk_catalog` 导出固定 pilot corpus，再运行：

```bash
python scripts/rds_to_chunks.py exports/chunks.csv data/chunks/chunks.jsonl --fye MSFT=0630,AAPL=0927,NVDA=0126
python -m rag.cli index --backend chroma
python -m rag.cli search "Microsoft total revenue" --ticker MSFT --backend chroma
```

Agent 组仍然调用同一个 `retrieve(query, filters, top_k)` / `sec_filing_search`，无需改接口。需要复现 Experiment 1 时，使用 `--backend custom`。

## 建完索引后先看什么
1. 确认 Chroma collection 的记录数与 `chunks.jsonl` 一致，并保留 Data 的原始 `chunk_id`。
2. 挑几个 chunk 检查 section、table、accession 和 source URL 是否正确。
3. 分别用 custom 和 chroma backend 跑同一批问题，记录 recall、MRR、provenance 和 latency。
4. 架构选择与风险见 `docs/vector_store_decision.md`。

## 分工对应（见 charter）
- B：`rag/parse.py`、`rag/chunk.py`（切分质量、coverage）
- C：`rag/retrieve.py`、`rag/chroma_backend.py`、`rag/embed.py`（向量后端、混合检索、比较 embedder）
- D：`eval/gold_v0.jsonl`（标注 evidence，把 status 改成 labeled）
- E：`rag/generate.py`（引用式回答、成本日志）
- A：`docs/retrieval_api.md`（发给 Agent、Eval、Data、Graph、UI 组征求意见）
