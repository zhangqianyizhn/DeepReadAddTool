# FinanceBench 实验封存说明

## 1. 封存决定

自 2026-08-22 起，FinanceBench 141 题在本项目中进入“已封存 benchmark”状态。

原因是：

- 141 题已被多轮 Baseline、提示词优化、人工标题工具和自主工具实验使用；
- 当前 60/20/61 划分中的 train、dev 和最终 test 结果均已产生；
- 61 道 test 的逐题答案和评分已经查看；
- 若继续根据这 61 题的错误修改工具，再在同一 test 上汇报提升，会产生测试集反馈泄露。

封存不表示删除数据，也不表示以后不能运行 FinanceBench。它表示：今后的 FinanceBench 运行只能被称为“复现、回归或 post-hoc 工程实验”，不能继续当作新的无偏泛化证据。

## 2. 冻结实验事实

### 2.1 最终协议

- 协议：`held_out_test61_ab_v1`
- Student：`deepseek-v4-flash`
- Judge：`deepseek-v4-flash`
- test 数量：61
- `max_rounds=50`
- `retrieval_topk=1`
- `agent_topk_max=1`
- pagination：关闭
- 旧人工标题工具：关闭
- Candidate：只开启冻结的 AI 生成 `document_inventory_search`

### 2.2 最终结果

| 方案 | 准确率 | 平均分 | 输入 Token/题 | 耗时/题 | Evidence Recall |
|---|---:|---:|---:|---:|---:|
| Baseline | 90.98% | 3.639 | 480,710 | 55.3s | 31.97% |
| 冻结 AI 工具 | 90.98% | 3.639 | 240,003 | 35.9s | 27.32% |

- 成对结果：1 胜 / 59 平 / 1 负，净分 0；
- 准确率：无提升；
- 平均输入 Token：下降 50.07%；
- 平均耗时：下降 35.06%。

### 2.3 冻结哈希

| 产物 | SHA-256 |
|---|---|
| AI 候选工具 | `74DCAB8E11DB78721DB730B74E53E7261EBF5E3E458E7CE4220D9D7C6B7EDB03` |
| test 划分 | `FE434029CCBC3F2FC90A99C197E9DBB7237CC017F309477E269DF3C7CFB20F07` |
| 最终报告 | `3344B1C7ED50AD84B8ABA36FBACA6A97EE16487C1313579A1CBD0368394A28C5` |
| Baseline judged JSON | `5C109A41048D0EDBDB6815C9054929687DB39C3FF78A7573A54384A422616D91` |
| Candidate judged JSON | `F4E95EFF1D928325C650B4EDC3682BCF4C6EF0E05E6C0E61864DCD009CF98812` |

## 3. 核心封存产物

- 冻结清单：`runs/blind_20260821_181044/repair_round2/frozen_test61/FROZEN_MANIFEST.json`
- 最终 A/B 报告：`runs/blind_20260821_181044/repair_round2/frozen_test61/FROZEN_TEST61_REPORT.md`
- 冻结工具：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_candidate_tool.py`
- Baseline 评分：`runs/blind_20260821_181044/repair_round2/frozen_test61/baseline_judged.json`
- Candidate 评分：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_generated_tool_judged.json`
- Candidate 原始日志：`runs/blind_20260821_181044/repair_round2/frozen_test61/frozen_generated_tool/output_0001/deepread_run.log`
- 7 道失败分析：`reports/FINANCEBENCH_TEST61_7_FAILURES.md`

## 4. 后续纪律

以下行为不会破坏封存：

- 读取、复制和汇报已有结果；
- 重新计算汇总统计；
- 对标注质量进行人工审计；
- 为代码重构执行回归测试，但结果明确标记为 post-hoc；
- 在新数据集上复用相同的 Agent 闭环框架。

以下行为会破坏“无偏测试”声明：

- 把 61 道 test 的失败案例交给 Analyzer 或 Repair Agent；
- 根据 test 结果修改候选工具、策略或权重后再次声称 test 提升；
- 从 test 题中提取公司别名、公式规则或单题补丁并加入候选；
- 在报告中把后验修复结果与原冻结结果混写。

如确需继续调试 FinanceBench，应创建独立目录并在名称中包含 `posthoc_financebench`，且不得覆盖本目录任何冻结文件。

## 5. 校验命令（只读）

```powershell
$root = "D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\repair_round2\frozen_test61"

Get-FileHash -Algorithm SHA256 -LiteralPath `
  "$root\frozen_candidate_tool.py", `
  "$root\FROZEN_TEST61_REPORT.md", `
  "$root\baseline_judged.json", `
  "$root\frozen_generated_tool_judged.json"
```

该命令只读取文件并计算哈希，不会修改任何数据。
