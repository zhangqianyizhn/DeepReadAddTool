# 需要审核确认的决策

在写正式执行脚本和调用 API 前，请确认以下事项。

## 1. 模型角色

- Student 模型/Endpoint ID：待填写。
- Teacher 模型/Endpoint ID：待填写。
- Judge 模型/Endpoint ID：待填写。
- Teacher 和 Judge 是否允许使用同一个高阶模型：建议可以，但 Judge 的 Prompt 和参数必须固定；若预算允许，使用独立 Judge 更稳妥。

## 2. 数据划分

建议：按 `doc_name` 分组，目标比例 60%/20%/20%，约 85/28/28 题。

原因：Teacher 会看到 Train Gold；同一份财报的问题不能同时出现在 Train 和 Test。

待确认：是否接受文档分组后实际题数与 85/28/28 有少量偏差。

## 3. 第一版优化对象

建议只优化：

```text
store.agent_instructions
```

以下保持不变：Student、Judge、索引、`top_k`、工具开关、分页、并发、最大轮数。

待确认：第一版是否同意不同时优化检索参数。

## 4. Prompt 形式

建议：生成一份全局通用 Prompt，最多 800 tokens。

暂不采用：

- 每个题型一份 Prompt；
- 每道题动态 Prompt；
- 公司或文档专属 Prompt；
- 直接把 Train Gold 写入 Prompt。

待确认：是否接受先做全局 Prompt，第二阶段再考虑题型路由。

## 5. 优化轮数和候选数

建议：

- 20 题 Pilot：1 轮，2～3 个候选。
- 正式流程：最多 2 轮，每轮 3 个候选。

待确认：API 预算是否支持约 4～7 小时的正式候选运行。

## 6. 选择指标

建议主指标使用 Dev Normalized Accuracy，Recall、paired changes、Token 和延迟作为辅助及约束。

待确认：是否更重视 Accuracy，还是希望设置成本上限，例如 Token 增长不得超过 20%。

## 7. 最终汇报数字

建议同时提供：

- Held-out Test 28 题：正式、无泄漏结论。
- 最终 Prompt 在全部 141 题上的描述性结果：便于与历史实验比较，但明确标注其中包含 Train/Dev，不能作为无偏测试结论。

待确认：是否需要最终再跑一次全 141 题。

## 8. 当前建议结论

如果没有额外要求，推荐采用：

```text
20题Pilot
→ 85/28/28文档分组划分
→ 全局Prompt优化
→ 2轮×3候选
→ Test只跑一次
→ 可选全141题描述性复跑
```
