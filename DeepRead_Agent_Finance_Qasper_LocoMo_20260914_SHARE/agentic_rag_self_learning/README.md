# Agentic RAG Prompt Self-Learning

这是一个独立于现有代码和实验结果的新工作目录，用于设计并实施 FinanceBench 141 题上的 Agentic RAG Prompt 自学习流程。

当前状态：**20题 Pilot 已具备一键运行入口；默认运行1个 Teacher 候选，完成完整自学习闭环。**

## 直接运行20题 Pilot

在 PowerShell 中执行：

```powershell
cd "D:\桌面\DeepRead\agentic_rag_self_learning"
.\run_pilot.ps1
```

第一次运行会在本文件夹建立独立 `.venv`、安装依赖，并在
`data/generated/pilot20` 中建立20文档的独立索引。原始
`Data/FinanceBench` 仅被读取，不会被改写。

默认流程为：20题 Baseline → 固定 Judge 评分 → Teacher 只分析12道训练题
→ 生成3套候选 → 实际复跑第1套 → 在8道开发题上比较。

如果只想检查配置和数据、不调用 API：

```powershell
.\run_pilot.ps1 -DryRun
```

确认默认闭环可用后，如需评测全部3套候选：

```powershell
.\run_pilot.ps1 -CandidateLimit 3
```

## 通宵连续跑：20题完成后自动跑141题

```powershell
.\run_overnight_pilot_then_141.ps1
```

该入口会自动续跑最近一次未完成的20题 Pilot，完成后读取最佳提示词，
继续运行优化提示词版本的 FinanceBench 全部141题并评分。运行期间会临时
阻止 Windows 自动休眠；脚本退出后恢复正常休眠行为。141题包含 Pilot
用过的20题，因此生成的全量结果属于描述性结果，而不是严格 held-out 结果。

## 这次“自学习”指什么

本项目暂不训练或微调模型权重，而是进行可审计的 Prompt 优化：

1. Student（低阶模型）运行 FinanceBench，产生答案、检索文本和工具轨迹。
2. Teacher（高阶模型）只分析训练集中的失败，提出通用的 Agent 指令候选。
3. Student 使用不同候选 Prompt 在开发集上重新运行。
4. 根据固定指标选择最佳 Prompt。
5. 冻结 Prompt 后，只在未参与学习的测试集上评估一次。

## 先看哪些文件

1. `PLAN.md`：完整研究思路和执行步骤。
2. `DECISIONS_FOR_REVIEW.md`：需要审核确认的关键选择。
3. `config/experiment.yaml`：实验参数草案。
4. `.env`：填写 API Key 和模型名的位置。
5. `prompts/teacher_prompt_optimizer.md`：Teacher 生成 Prompt 的元提示词。
6. `schemas/teacher_candidates.schema.json`：Teacher 必须遵守的结构化输出格式。

## API Key

打开本目录下的 `.env`，至少填写：

```env
VOLCENGINE_API_KEY=你的火山方舟APIKey
STUDENT_MODEL=低阶模型或Endpoint ID
TEACHER_MODEL=高阶模型或Endpoint ID
JUDGE_MODEL=固定评测模型或Endpoint ID
```

`.env` 已加入本目录 `.gitignore`。不要把真实密钥复制进 Markdown、YAML、Prompt 或聊天记录。

## 与现有 DeepRead 的连接点

现有仓库已经支持通过 YAML 的以下字段追加 Agent 指令：

```yaml
store:
  agent_instructions:
    - "instruction 1"
    - "instruction 2"
```

它最终会传入：

```text
DeepReadWrapper.agent_instructions
→ run_agent(additional_instructions=...)
→ build_system_prompt(...)
```

因此第一版不需要重写 DeepRead Agent，只需要增加一个外层优化器，负责生成 Prompt、写入派生配置、运行现有 harness 并比较结果。

## 计划中的目录

```text
agentic_rag_self_learning/
├── .env
├── .env.example
├── .gitignore
├── README.md
├── PLAN.md
├── DECISIONS_FOR_REVIEW.md
├── config/
│   └── experiment.yaml
├── prompts/
│   ├── student_agent_instructions_v0.md
│   └── teacher_prompt_optimizer.md
├── schemas/
│   └── teacher_candidates.schema.json
├── data/
│   └── README.md
└── runs/
    └── README.md
```

代码脚本将在方案审核通过后实现，避免在研究变量尚未确认前先写死流程。
