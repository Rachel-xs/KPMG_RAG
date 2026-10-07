# 从这里开始（中文速览）

## 这个 repo 做什么
把 SEC 的 10-K / 10-Q 切成带 metadata 的 chunk，建 BM25 + 向量索引，提供 `retrieve()` 给 Agent 组调用，并用 gold set 打分。

## 第一次运行（在自己的 Mac 上）
```bash
cd kpmg-rag-retrieval
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make test     # 20 个离线测试，应全部通过
make demo     # 用两份假文件跑通 切分→索引→检索→评估 全流程
cp .env.example .env   # 把 SEC_USER_AGENT 改成你的名字和邮箱
make pilot    # 下载 6 家公司的真实文件并建索引（第一次会下载 bge-small 模型，约 130MB）
python -m rag.cli search "supply chain risks" --ticker CAT,DE --section "Item 1A"
```

## 跑完 `make pilot` 后先看什么
1. 终端里每份文件的 `coverage`：低于 0.5 的会被标出来。银行（JPM/BAC/C）的 10-K 很可能偏低，因为它们按年报格式排版。
2. 挑几个 chunk 读一读（`data/chunks/chunks.jsonl`）：切分位置对不对？表格完不完整？
3. 用 `search` 试 10 个问题，记下 BM25 和 dense 各漏掉了什么。

## 分工对应（见 charter）
- B：`rag/parse.py`、`rag/chunk.py`（切分质量、coverage）
- C：`rag/retrieve.py`、`rag/embed.py`（混合检索、比较 embedder）
- D：`eval/gold_v0.jsonl`（标注 evidence，把 status 改成 labeled）
- E：`rag/generate.py`（引用式回答、成本日志）
- A：`docs/retrieval_api.md`（发给 Agent、Eval、Data、Graph、UI 组征求意见）
