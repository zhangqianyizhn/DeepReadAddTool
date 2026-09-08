# Agent 自动工具演化：盲重建实验

这个目录用于回答一个非常具体的问题：

> 在看不到现成 `search_document_titles`、人工错误分析和历史 A/B 结论的情况下，Agent 只根据训练集上的 baseline 失败轨迹，能否独立诊断缺失能力，并写出一个可执行的候选工具？

这不是标题路由的再次手工实现，也不是旧 Teacher–Student 提示词实验。程序严格使用：

- 固定训练集 `60` 题；
- 旧的无标题路由 baseline 轨迹、答案和评分；
- FinanceBench 训练数据自带的 question、gold answer 和 evidence；
- 一个通用且受限的工具接口。

程序明确不读取：

- test 61 题；
- 已有标题路由代码；
- 标题路由实验轨迹和报告；
- 人工撰写的失败归因；
- 任何旧 Teacher 候选提示词。

## 实验阶段

1. **Analyzer**：对原始失败轨迹聚类，定位可重复、可被工具修复的能力缺口。
2. **Tool Architect**：把诊断转成 ToolSpec、Python 候选工具、使用规则和测试案例。
3. **静态安全检查**：禁止文件、网络、进程、动态执行等能力；候选代码不会自动写入 DeepRead。
4. **人工只做实验审计**：查看 Agent 是否独立重建出合理能力，而不是替它指出“应该做标题路由”。
5. 候选通过审计后，再进入 dev 20 题接入与 A/B；test 61 题只在方案冻结后运行一次。

## API Key

只填写下面这个文件中的一行：

`D:\桌面\DeepRead\agentic_rag_self_learning\.env`

```dotenv
VOLCENGINE_API_KEY=在这里粘贴新套餐的Key
```

不要把 `.env` 截图、上传或发到聊天里。模型和 Base URL 已配置为：

```dotenv
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
STUDENT_MODEL=deepseek-v4-flash
TEACHER_MODEL=deepseek-v4-flash
JUDGE_MODEL=deepseek-v4-flash
EMBEDDING_MODEL_NAME=doubao-embedding-vision
```

## 运行

在 PowerShell 中执行：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution"
.\run_blind_reconstruction.ps1
```

默认会选取训练集中的 16 个低分案例和 4 个成功案例作为对照。运行结束后查看终端显示的 `BLIND_RECONSTRUCTION_REPORT.md`。候选代码只会保存在本目录的 `runs` 中，不会自动接入仓库。

只检查输入是否齐全、不调用 API：

```powershell
.\run_blind_reconstruction.ps1 -DryRun
```

## 如何解释结果

- 若 Agent 独立提出并实现了文档级元数据路由或功能等价工具：核心想法获得第一项正证据。
- 若诊断正确但代码失败：问题主要位于 ToolSpec 到实现阶段。
- 若诊断停留在泛化提示词：问题主要位于轨迹归因和能力缺口抽象阶段。
- 若工具可运行但 dev 无提升：问题主要位于调用策略、工具适配或过拟合。

一次失败不能直接证明方向不可行；它会把失败定位到闭环中的具体模块。真正的最终结论要由“盲重建 + dev A/B + 冻结后 test”共同给出。

## 盲重建完成后的 Dev 20 严格 A/B

盲重建候选生成后执行：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution"
.\run_dev_ab.ps1
```

该命令会依次运行同模型 Baseline、AI生成工具方案及固定 Judge。旧的
`search_document_titles` 在两组中均关闭；候选组只增加盲重建生成的工具和它自己生成的使用策略。
运行支持断点续跑，期间会阻止 Windows 自动睡眠，结束或中断后自动恢复正常睡眠设置。

## Round 2：Agent读取Dev反馈后自主修复

首次dev A/B完成后执行：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution"
.\run_autonomous_repair_round2.ps1
```

该命令把原候选、dev成对评分和候选轨迹交回Repair Agent。程序不会把人工发现的具体代码错误写进提示词，
也不会访问test。Agent生成修复代码与策略并通过安全/泄漏/自生成测试后，只重跑修复候选20题，原baseline直接复用。

## 最终冻结Test 61

仅在dev达到预设条件后运行一次：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution"
.\run_frozen_test61.ps1
```

程序会冻结候选代码、策略、模型配置和test划分的SHA-256，然后依次运行61题Baseline、61题冻结候选和两组Judge。
test反馈不会进入任何Repair Agent。重新执行同一命令只能复用相同冻结版本，候选或模型一旦变化会拒绝继续。
