# Week 6 Chunking：E0 诊断与三轮实验结果（10/20）

语料：Data 组 `paragraph-v1` chunk（RDS 导出，9 份 filing，1,780 个 chunk）。Gold 为 `eval/gold_v0_msft.jsonl`，共 30 题、43 条证据。
Token 数使用 bge-small 的真实分词器统计。复现命令见文末。

## 1. E0 诊断（`scripts/e0_diagnostics.py`）

| 检查项 | 结果 | 含义 |
|---|---|---|
| 超过 512 tokens 的 chunk | 81 / 1,780（4.6%），**全部是含表格的 chunk**（表格 chunk 中占 15.4%）；加上 `rag.index` 拼接的上下文头后为 121 个 | 截断只影响表格，被截掉的是表格下半部分的行 |
| 纯文本 chunk 长度 | p50 233，max 366 | 文本长度没有问题 |
| 含表格行的 chunk | 527（29.6%）；pipeline 标记为 `is_table` 的只有 46 个 | `is_table` 字段基本不可用 |
| 表格空单元格比例 | 60.8% | 大量 `\| \|` 噪声 |
| 数值表格 chunk 缺列头（如 "Three Months Ended"） | 135 / 480（28%） | 读到数字时无法判断属于哪个期间 |
| 数值表格 chunk 缺单位行（如 "In millions"） | 213 / 480（44%） | 数量级可能读错 |
| chunk 起点落在单词中间 | 1,009 / 1,771 个边界（57%） | 按字符窗口切分、重叠 150 字符，起点没有对齐词边界 |
| chunk 边界落在表格中间 | 162 个（9.1%） | 表格被切断 |
| Gold 锚点完整落在单个 chunk 内 | **43 / 43** | 得益于 150 字符重叠，锚点没有被切断，strict 分数可以得到 |
| 表格类锚点的 chunk 缺列头或单位 | 3 / 15（3 条都是现金流量表的 `127,494`） | 见下方例子 |

**典型失败：** GSv0-MSFT-003 问 “nine months ended March 31, 2026 的 net cash from operations”。
包含答案 `127,494` 的 chunk 从表格中间一行 `(166 | ) | ...` 开始，没有表名、没有 "Nine Months Ended" 列头，也没有单位，结果 hybrid 在 top-10 内都没召回。
即使召回了，LLM 也无法判断 `127,494` 是三个月还是九个月的数。

**Exp1 按题型拆分（hybrid，filtered）：** 表格题 recall@5 = 0.474，文本题 = 0.618；dense 在表格题上最弱（0.397 对 0.544）。

**对计划的两点修正：**
1. Data 组的表格**并没有被拍平**。行结构和 `|` 分隔符都在，只是有噪声并且被切断。利用 Data 组的 char offset 可以把每个 section 的原文精确拼回来，所以**方案 B 不需要 Data 组额外提供表格，也不需要重新解析 edgartools**。
2. `rag/index.py` 的 `index_text()` 已经给每个 chunk 加了上下文头（公司、ticker、form、期间、section）。因此实验 E 只需要补充**表名、单位和列头**，不用从零开始做。

## 2. 新增代码

| 文件 | 作用 |
|---|---|
| `rag/tables.py` | 把 section 原文解析成 text/table 块；清洗单元格（`$` 与数字合并、`(623 \| )` 合并为 `(623)`、删除空单元格）；合并跨行的多层表头，并组合成 "Three Months Ended March 31, 2026" 这样的完整列名（支持跨列 span 和 "Percentage Change" 列）；保留表名、单位和脚注；去掉页码和页眉噪声；超长表格按行拆分，每块重复表头，并补上所属分组（如 "Revenue (cont.)"）。数值表中有 80%（310/387）能自动对齐列名，对不齐的主要是 exhibit 列表和目录 |
| `scripts/build_chunk_variant.py` | 生成 A / B / B-linear / C1 / C2 五个变体；用 offset 拼回 section 原文后在 section 内重新切分，保留 `section_id`，表格带 `table_id` 和 `parent_chunk_id`（schema lock v1 的可选字段）；`+L` 把表格渲染成每行写明列名，`+E` 在索引头加上最近的子标题 |
| `scripts/run_chunking_exp.py` | 对每个变体依次建索引、跑 gold，输出 summary、逐题结果、相对 A 的逐题输赢，以及表格题和文本题分开统计；同时计算 F（parent-child）的 parent recall@5 和返回 token 数 |
| `scripts/e0_diagnostics.py` | 本页第 1 节的诊断 |
| `tests/test_tables.py` | 6 个测试（单元格合并、列头组合、百分比列、caption 识别、linear 渲染、拆分时重复表头） |

验证结果：每个变体中，43 条 gold 锚点都完整落在单个 chunk 内；加上上下文头后超过 512 tokens 的 chunk 从 121 个降到 2–5 个。
用变体 A 跑 BM25 的结果（0.500 / 0.611）与 10/14 的 Exp1 完全一致，说明实验框架能复现 baseline。

## 3. 首轮结果：仅 BM25

| 变体 | filtered R@5 | filtered R@10 | 表格题 R@5 | 文本题 R@5 | unfiltered R@5 | 相对 A 逐题 赢/输（filtered） |
|---|---|---|---|---|---|---|
| A baseline | 0.500 | 0.611 | 0.500 | 0.500 | 0.331 | — |
| B 表格整块 markdown | 0.561 | 0.672 | **0.718** | 0.441 | 0.486 | 5 / 2 |
| B-linear 每行写明列名 | 0.567 | 0.672 | 0.654 | 0.500 | 0.425 | 3 / 1 |
| C1 B + 固定 460 tokens | **0.633** | 0.753 | 0.692 | **0.588** | 0.450 | 8 / 3 |
| C2 B + 递归 460 tokens | 0.578 | 0.753 | **0.718** | 0.471 | **0.511** | 7 / 3 |

初步解读（30 题，差距小于约 0.07 视为噪声）：
- **表格整块处理对表格题有明显帮助**：BM25 下表格题从 0.50 升到约 0.70，unfiltered 从 0.40 升到 0.72。这是本轮最清楚的信号。
- 文本切分方式（B、C1、C2）之间的差别目前还在噪声范围内，需要看 dense 和 hybrid 的结果。BM25 本身偏好较长的 chunk，C1 的平均长度最长（326 tokens）。
- top-5 返回给 Agent 的总 token 数：B 最省（约 1,280），C1 最多（约 1,920）。

## 3b. 完整结果：bge-small，dense 和 hybrid

Agent 实际会传 filter，所以主要看 **hybrid + filtered** 这一行：

| 变体 | R@5 | R@10 | MRR | 表格题 R@5 | 文本题 R@5 | top-5 tokens | 相对 A 逐题 赢/输 |
|---|---|---|---|---|---|---|---|
| A baseline | 0.556 | 0.689 | 0.418 | 0.474 | 0.618 | 1,569 | — |
| B | 0.606 | 0.706 | 0.496 | **0.667** | 0.559 | 1,293 | 6 / 3 |
| B-linear | 0.589 | 0.706 | **0.503** | 0.628 | 0.559 | 1,449 | 4 / 2 |
| **C1** | **0.683** | **0.831** | 0.480 | 0.615 | **0.735** | 1,877 | **10 / 5** |
| C2 | 0.592 | 0.764 | 0.422 | 0.538 | 0.632 | 1,743 | 9 / 6 |

解读：
- **C1 整体最好**：R@5 +0.13，R@10 +0.14，逐题 10 胜 5 负。但 30 题的样本下，10 比 5 还不算统计显著，而且 C1 的平均 chunk 最长（326 tokens，C2 是 294），所以**目前分不清是“切法”的作用还是“chunk 长度”的作用**。需要在相同长度下再比一次（见 3c）。
- **表格整块处理对 BM25 有效**（表格题 0.50 → 0.72），在 hybrid 里也有效（0.47 → 0.67）。但**单用 dense 时，markdown 表格反而更差**（filtered 0.397 → 0.346）。把每行写成“行名: 列名 = 数值”（B-linear）对 dense 帮助最大：filtered 0.551，unfiltered 0.526。
- **unfiltered 下 hybrid 各变体的差距都在噪声范围内**，再次说明 Agent 必须正确传 filter。
- **成本**：C1 返回给 Agent 的 top-5 比 A 多约 20% 的 token。

BM25 冒烟测试中的 F 和 E（同样是 filtered）：
- C1 的 parent recall@5 = 0.764（child 层面为 0.633），但 top-5 parent 合计约 4,800 tokens，是 child 的 2.5 倍。
- E 在 BM25 下没有提升（0.600 对 0.633，在噪声范围内）。

## 3c. 第二、三轮结果（hybrid + filtered）

**第二轮：在 C1 上叠加 L（逐行写明列名的表格）和 E（子标题头）**

| 变体 | R@5 | R@10 | 表格题 | 文本题 | F: parent R@5 |
|---|---|---|---|---|---|
| C1 | **0.683** | **0.831** | 0.615 | **0.735** | **0.833** |
| C1+E | 0.683 | 0.797 | 0.615 | 0.735 | 0.833 |
| C1+L | 0.639 | 0.831 | 0.667 | 0.618 | 0.744 |
| C1+L+E | 0.644 | 0.797 | **0.679** | 0.618 | 0.733 |

- **E 没有提升**，不采用。现有的索引头已经包含公司、期间和 section，子标题提供的信息不多。
- **L 让表格题变好，但文本题变差**（0.735 → 0.618）。两个变体的文本 chunk 完全相同；文本题变差是因为逐行表格每一行都重复了 “Three Months Ended …” 这类列名，查询里的这些词会被表格 chunk 抢走排名，文本 chunk 被挤出 top-5。整体上不划算，不采用。

**第三轮：统一 300 tokens 的预算，比较切法**

| 变体（300） | 平均 tok | R@5 | R@10 | 文本题 | F: parent R@5 | F: parent tokens |
|---|---|---|---|---|---|---|
| C1 固定切 | 244 | 0.556 | 0.742 | 0.529 | 0.808 | 3,489 |
| C2 递归切 | 212 | **0.589** | 0.706 | **0.559** | **0.853** | **3,019** |

- 在相同预算下，**递归切不比固定切差**。C2 的 chunk 平均还更短，但 R@5 和 parent recall 都更高。
- 两者在 300 下都比 C1@460（0.683）低，说明**第一轮 C1 的优势主要来自 chunk 更长，而不是固定切这种方式本身**。

## 4. 当前结论

1. **表格整块 + 清洗（方案 B）保留。** 表格题提升稳定。markdown 表格对 dense 不利，但在 hybrid 下整体是正收益。
2. **检索单位推荐两种配置，取决于 Agent 的 token 预算：**
   - **不做 parent 扩展：C1 @460**，R@5 0.683（基线 0.556），top-5 约 1.9k tokens。
   - **做 parent 扩展（small-to-big）：C2 @300 + F**，parent R@5 **0.853**，top-5 约 3.0k tokens。比 C1@460 + F（0.833，约 4.7k tokens）效果更好，也更省。
   - 注意：以上 token 数按 top-5 计算；Agent 目前默认 `top_k=8`，需要按 k=8 重新确认预算。
3. **E 和 L 不采用。**
4. **局限：** 只有 30 题，全部来自一份 MSFT 10-Q，而且 gold 还是 draft。大部分差距只有 2–4 题。需要 Gold Set v1 映射完成后再确认。

## 5. 下一步
1. 和 Agent 组确认 token 预算（k=5 还是 k=8），以及 `parent_text` 的 contract 变更。
2. 把选定方案接入 `retrieve()`（返回 child 用于 citation，同时附带 parent 作为上下文），并导出 v2 索引。
3. Gold Set v1 映射后重新跑 C1@460、C2@300+F 和 C2@460+F。

## 复现
```bash
# Data 的 chunk 作为变体 A 的输入，放在 data/chunks_A/chunks.jsonl（data/ 不进 git）
TOK=~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/<snapshot>/tokenizer.json
python scripts/e0_diagnostics.py --chunks data/chunks_A/chunks.jsonl --tokenizer $TOK \
    --per-question eval/results/per_question_20261014-174752.csv
python scripts/run_chunking_exp.py --tokenizer $TOK --variants A,B,B-linear,C1,C2      # 第一轮：bm25/dense/hybrid × filter 开/关
python scripts/run_chunking_exp.py --tokenizer $TOK --variants A,C1,C1+L,C1+E,C1+L+E   # 第二轮：逐行表格 / 子标题头
python scripts/run_chunking_exp.py --tokenizer $TOK --variants C1,C2 --max-tokens 300   # 第三轮：相同长度下比较切法
python scripts/run_chunking_exp.py --tokenizer $TOK --embedder lsa --methods bm25       # 只跑 BM25（不需要 torch）
pytest -q tests/test_tables.py
```
