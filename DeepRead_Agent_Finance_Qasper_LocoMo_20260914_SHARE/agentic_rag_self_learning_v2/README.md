# 研究内容2：Agent 自学习改进 RAG（V2）

这一目录实现一个严格分离训练、开发、测试数据的自学习闭环。它复用已经完成的
FinanceBench 141 题“标题路由 V1”答案和工具日志，不会修改原始数据、已有索引或旧实验结果。

流程如下：

1. 将 141 题按文档分组，固定划分为 60 题训练集、20 题开发集、61 题测试集。
2. Analyzer Agent 只阅读训练集的题目、答案、Gold、Judge 理由、Evidence 和压缩后的工具轨迹，归纳共性失败机制。
3. Repair Agent 根据诊断生成三套带触发条件的通用 RAG skills。它不能写入公司名、题号或具体答案。
4. 三套 skills 分别在开发集运行，固定 Judge 重评“原标题路由 Baseline”和三个候选。
5. Evaluation Agent（确定性程序）按准确率优先、成本次优的规则选出最佳方案；若都不提升，则保留 Baseline。
6. 测试集不会在第 4 步自动运行。只有技能冻结后，才单独运行一次 61 题测试。

## 你现在运行什么

在 PowerShell 中：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_self_learning_v2"
.\run_round1.ps1
```

密钥和模型配置默认复用 `..\agentic_rag_self_learning\.env`，不需要再次填写，也不会打印密钥。
命令支持断点复用：Teacher 的每批诊断、候选技能、已完成候选答案和 Judge 评分都会保存。

完成后先查看：

```text
runs\round1\ROUND1_REPORT.md
```

只有该报告确认了可接受的开发集候选后，才运行测试集：

```powershell
.\run_test61.ps1
```

## Round 2

Round 1完成后，运行以下命令会自动完成差异答案的成对复核、生成两套保守skills、
运行两套20题开发集实验，并执行准确率/回归/Token硬门槛：

```powershell
.\run_round2.ps1
```

Round 2不会自动打开测试集。只有 `runs\round2\ROUND2_REPORT.md` 显示候选通过全部门槛时，
才运行：

```powershell
.\run_round2_test61.ps1
```

如果需要通宵运行，可使用下面的条件流水线。它先完成Round 2；只有候选通过全部开发集
门槛并冻结后，才自动运行一次61题测试，否则安全停止：

```powershell
.\run_overnight_round2_then_test_if_pass.ps1
```

## Round 3：结构化经验库与按题路由

Round 1/2 已证明，把全部失败案例压缩成一套全局提示词会产生明显负迁移。Round 3
不覆盖前两轮结果，改为：

1. Teacher 直接读取训练集的答案、Evidence 和工具轨迹，生成结构化经验记录；
2. 每条经验包含适用标签、不适用边界、因果证据和一个可执行动作；
3. 程序根据每道题的题型特征，只选择 Top-2 匹配经验；
4. 没有经验可靠命中的题直接复用标题路由 Baseline，不额外调用 Student；
5. 成对 Judge 除了给出总体结果，还分别统计每条经验的胜、负和 Token 变化；
6. 只有完整路由策略通过开发集硬门槛，才允许运行一次 61 题测试。

运行完整 Round 3 开发集实验：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_self_learning_v2"
.\run_round3.ps1
```

该命令支持断点复用。完成后查看：

```text
runs\round3\ROUND3_REPORT.md
runs\round3\experience_library.json
runs\round3\experience_outcomes.json
```

只有 `runs\round3\gate.json` 中的 `passed` 为 `true` 时，下面的测试命令才会执行：

```powershell
.\run_round3_test61.ps1
```

## Round 4：根据Round 3反馈收紧路由

Round 3开发集结果为1胜、15平、4负，主要原因是`temporal`、`extraction`等宽泛标签
使19/20题都命中了经验。Round 4会自动隔离Round 3标为`quarantine`的经验，并执行：

- 宽泛标签不能单独触发经验；
- 非ANSWER_GUARD经验还必须与具体触发描述存在词项重合；
- `do_not_apply_when`会在路由阶段执行为排除条件；
- 未命中的题直接复用Baseline；
- 路由缓存同时包含经验、策略版本和题目成员，避免分组变化后误复用旧答案。

运行：

```powershell
.\run_round4.ps1
```

完成后查看：

```text
runs\round4\ROUND4_REPORT.md
```

只有Round 4通过开发集门槛，才运行：

```powershell
.\run_round4_test61.ps1
```

## 安全边界

- `Data\FinanceBench` 只读。
- 复用的 82 文档索引只读，脚本不会调用删除或重建索引。
- 旧的 141 题输出只读。
- Teacher 输入由程序强制过滤为 `split == train`。
- 开发集只用于选技能；测试集只允许冻结后运行一次。
- Round 3 未命中经验的题复用已有 Baseline，不会为了维持形式上的“全量运行”重复消耗 API。
