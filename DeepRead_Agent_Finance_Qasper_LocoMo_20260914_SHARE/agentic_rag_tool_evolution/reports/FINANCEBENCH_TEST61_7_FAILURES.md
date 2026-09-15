# FinanceBench 冻结 Test61：7 道未满分题的日志与原因分析

## 1. 分析范围

本文分析冻结测试集上“AI 自主生成工具”方案的 7 道未满分题。这里的“有问题”定义为 LLM Judge 得分低于 4 分，并不等价于答案必然完全错误。

- 测试集：61 题；
- 满分题：54 题；
- 未满分题：7 题；
- 归一化准确率：90.98%；
- 原始运行日志：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_generated_tool/output_0001/deepread_run.log`；
- 逐题答案与评分：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_generated_tool_judged.json`；
- 原始 Evidence：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_generated_tool/output_0001/_pipeline_records.json`。

需要特别说明：Baseline 也有 7 道未满分题，但题目集合并不完全相同。AI 工具修复了 Boeing gross margin 题，却使 AMCOR quick ratio 题由 4 分降到 1 分，因此最终是 1 胜、59 平、1 负，净分为 0。

## 2. 总体判断

7 道题的 `document_inventory_search` 都把正确公司对应的报告排到了前列：

| case_id | 路由 Top 候选 | 是否找对公司/报告 | 最终故障层级 |
|---|---|---:|---|
| `00807` | `3M_2023Q2_10Q` | 是 | quick ratio 定义与最终结论 |
| `00540` | `AES_2022_10K` | 是 | inventory turnover 公式口径 |
| `10420` | `AES_2022_10K` | 是 | net income 行、单位与 Gold/Evidence 冲突 |
| `00799` | AMCOR 2022/2023 报告，随后进入 `AMCOR_2023_10K` | 是 | quick ratio 定义覆盖不完整 |
| `00585` | `BOEING_2022_10K` | 是 | 负数分母下税率符号解释错误 |
| `01911` | `MGMRESORTS_2022Q4_EARNINGS`、`MGMRESORTS_2022_10K` | 是 | 目标字段缺失、搜索回退失控 |
| `00080` | `PAYPAL_2022_10K` | 是 | Gold 与资产负债表直接计算明显不一致 |

因此，不能把这 7 题解释为“AI 生成的文档路由工具没有找到正确文档”。更准确的结论是：

> 文档选择层基本成功；剩余瓶颈已经转移到指标定义、报表行选择、符号语义、答案覆盖和停止策略。若继续只修改标题/文档路由，不会直接解决这些题。

另外，其中多题存在 FinanceBench 标注口径与常见财务公式不一致，甚至 Gold 与所附 Evidence 互相冲突的情况。它们适合做数据质量分析，但不应在看过测试答案后回流修工具并继续宣称“无偏泛化提升”。

## 3. 七道题逐题分析

### 3.1 `financebench_id_00807`：3M quick ratio

**问题**：3M 在 FY2023 Q2 的 quick ratio 是否说明其流动性健康？

**Gold**：0.96，未达到 1，因此“不算健康”。

**模型答案**：按 `cash + marketable securities + accounts receivable` 计算得到 0.85，但进一步引用管理层“strong liquidity profile”、授信额度和现金流，最终回答 quick ratio 不适用、总体流动性健康。

**关键日志**：

```text
query_id = 069ae6eeaaa764d7
document_inventory_search
  Top1 = 2: 3M_2023Q2_10Q, score=6.0
get_doc_structure(doc_id=2)
read_section(doc_id=2, node_id=16)       # 资产负债表
regex_search(doc_id=2, "quick ratio")   # 报告未直接披露该词
read_section(nodes=125,126,127,128,129,130)
  # 又读取管理层流动性、授信、净债务、营运资本等材料
总工具调用 = 13
```

**真正原因**：

1. 路由正确，且所需资产负债表已经找到；
2. Gold 使用 `(current assets - inventory) / current liabilities`：`(15,754 - 5,280) / 10,936 ≈ 0.96`；
3. 模型使用更严格的 acid-test 定义：`(cash + marketable securities + receivables) / current liabilities ≈ 0.85`；
4. 模型随后让管理层对整体流动性的描述覆盖了题目要求的 quick-ratio 判断，导致结论与 Gold 相反。

**归类**：指标定义歧义 + 回答目标漂移，不是文档路由错误。

**可修方向**：建立“公式口径声明与双口径计算”算子。遇到 quick ratio 等存在多种定义的指标时，先按数据集/题目预期口径计算，同时注明另一种常见口径，不能直接宣布指标“不相关”。

---

### 3.2 `financebench_id_00540`：AES inventory turnover

**问题**：AES FY2022 的存货周转次数。

**Gold**：9.5 次。

**模型答案**：使用 `COGS / average inventory`，得到 `10,069 / ((1,055+604)/2) = 12.1` 次。

**关键日志**：

```text
query_id = b03b1500e13ba7c1
document_inventory_search
  Top1 = 8: AES_2022_10K, score=5.5
get_doc_structure(doc_id=8)
在 doc 8 内反复检索 Inventory、Cost of sales、Operating margin
bm25_search = 5 次
regex_search = 24 次
read_section = 10 次
总工具调用 = 41
```

**真正原因**：

1. 正确报告、COGS、2021/2022 inventory 都已经找对；
2. 常见财务定义通常使用平均存货，模型的 12.1 计算在该定义下自洽；
3. Gold 的 9.5 实际对应 `10,069 / 1,055 ≈ 9.54`，即使用期末存货而不是平均存货；
4. 题目没有显式给出公式，因此这是明显的评测口径歧义；
5. 模型又花了 41 次工具调用论证“该指标对公用事业公司意义有限”，增加成本但没有帮助评分。

**归类**：公式口径歧义 + 过度搜索。

**可修方向**：若题目未给公式，输出“按平均存货为 12.1；若按期末存货为 9.5”，并优先覆盖可能的评测口径。加入数值已齐备后的强制停止规则。

---

### 3.3 `financebench_id_10420`：AES ROA

**问题**：`FY2022 net income / average total assets`，保留两位小数。

**Gold**：-0.02。

**模型答案**：取 total assets 38,363 和 32,963，取 net income -505，计算得到 -0.01416，最后以百分数写成 -1.42%。

**关键日志**：

```text
query_id = d84bf04a0230af76
document_inventory_search
  Top1 = 8: AES_2022_10K, score=5.5
get_doc_structure(doc_id=8)
regex_search "Net income", "Net income attributable", "Total assets" 等 14 次
read_section(nodes=167,173,174)
总工具调用 = 20
```

**真正原因**：

1. 路由与 total assets 均正确；
2. 模型没有稳定区分 `net income`、`income from continuing operations`、`net income attributable to AES` 等相邻行；
3. 模型把题目要求的比率值改写成百分数，输出形式与 Gold 不一致；
4. 更关键的是，当前 `_pipeline_records.json` 附带的 Gold Evidence 中 FY2022 `NET INCOME (LOSS)` 显示为 -505，而 Judge 理由声称应使用 -713。Gold、Judge 理由和附带 Evidence 三者存在冲突。

**归类**：报表行选择与单位错误，同时存在数据标注冲突。

**可修方向**：技术上应加入“报表行身份验证”算子；研究上应把该题标记为 annotation audit case，而不是直接用测试 Gold 反向改工具。

---

### 3.4 `financebench_id_00799`：AMCOR quick ratio

**问题**：AMCOR FY2023 相比 FY2022 的 quick ratio 是改善还是下降。

**Gold**：0.67 → 0.69，改善。

**模型答案**：按 `cash + receivables` 计算 0.53 → 0.57，结论仍为改善，但因数值不符只得 1 分。

**关键日志**：

```text
query_id = 93bf88c6cb6c76c7
document_inventory_search
  返回多个 AMCOR 2022/2023 强候选
get_doc_structure(doc_id=15,12)
进入 doc 15: AMCOR_2023_10K
检索 Current assets、Inventories、Cash、Trade receivables、Current liabilities
总工具调用 = 19
```

**真正原因**：

1. 正确报告与所有数字均已找到；
2. Gold 同样使用 `(current assets - inventory) / current liabilities`，得到约 0.67 和 0.69；
3. Candidate 只保留了 `cash + receivables` 的 acid-test 口径；
4. Baseline 的主要答案也是 0.53 → 0.57，但额外补充了“另一口径为 0.67 → 0.69”，因此被 Judge 评为 4 分；Candidate 删除了这句补充后变为 1 分。

**归类**：答案覆盖回归 + 指标定义歧义。它不是 AI 工具把文档找错导致的回归。

**可修方向**：多定义指标必须保留口径覆盖，不应只输出单一公式。成对 Judge 也应固定公式口径，减少“同一核心答案因是否顺带提到 Gold 口径而产生 4→1”的不稳定性。

---

### 3.5 `financebench_id_00585`：Boeing effective tax rate

**问题**：比较 Boeing FY2022 与 FY2021 effective tax rate。

**Gold**：FY2022 为 0.62%，FY2021 为 -14.76%。

**模型答案**：FY2022 为 -0.6% benefit，FY2021 为 +14.7% expense，正负号完全反转。

**关键日志**：

```text
query_id = 602754d0e5912bf9
document_inventory_search
  Top1 = 28: BOEING_2022_10K, score=5.5
get_doc_structure(doc_id=28)
bm25_search(doc_id=28, "effective tax rate")
read_section(doc_id=28, node_id=139)
总工具调用 = 4
```

**真正原因**：路由和证据定位都很高效，但在“税收费用/收益”和“税前亏损”同时带符号时，模型按自然语言的 expense/benefit 重新解释了符号，没有按 `income tax expense or benefit / pretax income or loss` 的代数符号直接计算。

**归类**：真正的数值符号推理错误。

**可修方向**：加入带符号数值核验：先原样抄录分子与分母符号，再计算，再用乘回检查；不得用“expense/benefit”的语义自行翻转一次。

---

### 3.6 `financebench_id_01911`：MGM interest coverage

**问题**：使用 FY2022 Adjusted EBIT / annual Interest Expense 计算 interest coverage。

**Gold**：Adjusted EBIT 为负，因此 coverage ratio 为 0。

**模型答案**：达到 50 轮上限，没有生成最终答案。

**关键日志**：

```text
query_id = 94a0a20d878eafb9
document_inventory_search
  Top 候选 = MGMRESORTS_2022Q4_EARNINGS、MGMRESORTS_2022_10K
随后反复搜索：
  "Adjusted EBIT"
  "Adjusted EBIT(?!DAR)"
  "Interest Coverage Ratio"
  "coverage"
bm25_search = 6 次
regex_search = 63 次
read_section = 18 次
vector_search = 1 次
总工具调用 = 93，最终达到 max_rounds
```

**真正原因**：MGM 报告更常直接披露 `Adjusted EBITDAR`，而题目要求 `Adjusted EBIT`。模型已经进入正确公司的正确年份报告，却执着寻找完全一致的字段名；在查不到时既没有根据可用行推导，也没有按 Gold 规则将负值截断为 0，更没有及时停止。

**归类**：缺失指标推导 + 回退与停止策略失控。

**可修方向**：需要“指标依赖图/派生公式工具”和检索预算守卫。例如连续若干次同义搜索无新增 Evidence 时，切换到派生计算；仍不可计算时明确回答证据不足，不能循环到 50 轮。

---

### 3.7 `financebench_id_00080`：PayPal working capital

**问题**：PayPal FY2022 是否有正营运资本。

**Gold**：是，约 1.6B 美元。

**模型答案**：从资产负债表读取 current assets 57,517M、current liabilities 45,101M，计算为 +12,416M，即 +12.4B。

**关键日志**：

```text
query_id = 79db95c83f8804d8
document_inventory_search
  Top1 = 68: PAYPAL_2022_10K, score=5.5
get_doc_structure(doc_id=68)
read_section(doc_id=68, nodes=153,169,172,234)
总工具调用 = 6
```

**真正原因**：按 Gold Evidence 中的资产负债表直接相减，模型的 `57,517 - 45,101 = 12,416M` 是正确算术。即便剔除客户资金资产与负债，也不能自然得到 1.6B。当前 Gold 的 1.6B 与附带 Evidence 明显不一致。

**归类**：高概率数据标注错误，而非检索或计算错误。

**可修方向**：进入人工 annotation audit，不应为了迎合该 Gold 修改算法。

## 4. 共性归因

按主要原因归类：

| 故障类型 | 题目 | 数量 |
|---|---|---:|
| 指标/公式口径歧义 | 3M quick ratio、AES inventory turnover、AMCOR quick ratio | 3 |
| Gold、Judge 与 Evidence 冲突或疑似标注错误 | AES ROA、PayPal working capital | 2 |
| 数值符号推理错误 | Boeing effective tax rate | 1 |
| 派生指标缺失与停止策略失控 | MGM interest coverage | 1 |
| 文档路由错误 | 无 | 0 |

最值得向老师汇报的结论不是“还有 7 道题没修好”，而是：

> AI 自主生成的文档清单工具已经把这 7 道题都路由到了正确公司材料；错误分布表明瓶颈从文档选择转移到了财务指标语义、公式规范和搜索控制。与此同时，至少数道题暴露出 FinanceBench 的公式口径或标注一致性问题。

## 5. 是否继续在 FinanceBench 上修改

不建议再用这 61 道测试题生成或筛选新工具。测试答案、逐题评分和失败类型已经被查看；任何针对这些错误的改动都属于 post-hoc engineering，不能再作为无偏泛化结果。

FinanceBench 后续只保留三种用途：

1. 复现实验与回归测试；
2. 典型案例展示和数据质量研究；
3. 明确标注为 post-hoc 的工程调试。

新的“Agent 自动发现失败机制并生成工具”研究，应迁移到尚未用于该闭环的新数据集，并提前冻结按文档划分的 train/dev/test。
