# Qasper：AI自主生成单工具实验

本目录复现 FinanceBench 上的“单一工具生成”路线，但换用 Qasper，并提前注册数据隔离和判定规则。

## 实验问题

只给高阶模型 Qasper 训练题的原始 DeepRead 轨迹、答案与评分，它能否自主发现一种可工具化的共性故障，生成一个安全、只读、数据集针对性的工具，并在未见论文的问题上提高低阶模型 RAG 表现？

## 数据隔离

- train：60题，用于运行 Baseline、分析轨迹、生成工具。
- dev：20题，只用于严格A/B和最多一次自主修复。
- test：80题，工具和策略冻结后只打开一次。
- 划分单位是论文 `paper_id`，三组论文完全不重叠。
- 原始 `Data/Qasper/qasper-dev-v0.3.json` 始终只读。
- 联合语料索引包含三组论文正文，这是 RAG 的可检索语料；但生成工具的 Agent 在冻结前看不到 dev/test 问题、答案、轨迹或评分。

dev 不是“多余的小数据集”。如果直接用 test 调工具并继续修改，test 就变成了训练数据，最终提升无法作为泛化证据。dev 的作用是允许一次选择/修复，test 的作用是只做最终裁决。

## 固定实验变量

Baseline 与 Candidate 使用相同 Student、Judge、论文索引、`max_rounds=50`、`top-k=1`。Candidate 唯一增加：

1. AI生成的一个 `generated_corpus_search` 工具；
2. AI生成的该工具调用策略。

工具运行时只读以下结构信息，不读取文档正文：

```text
question
corpus[]:
  doc_id, source_name
  sections[]: node_id, title, paragraph_count, token_count
```

## 运行顺序

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution_qasper"

# 只做路径、配置和60/20/80划分检查，不调用API
.\run_train_generate.ps1 -DryRun

# 建联合论文索引，跑train 60 Baseline，Judge，Analyzer和Repair Agent生成一个工具
.\run_train_generate.ps1

# 工具生成成功后，进行dev 20严格A/B
.\run_dev_ab.ps1

# 如果train仍在另一个窗口运行，可在新窗口等待它结束后自动衔接dev A/B
.\run_wait_then_dev_ab.ps1

# 若第一轮Analyzer自主否决了标题/章节工具：准备原论文PDF后继续生成并自动跑dev
.\run_resume_pdf_then_dev.ps1
```

在 dev 报告产生前，不运行 test。若 dev 未过预注册门槛，只允许使用 dev 反馈自主修复一次；若通过，直接冻结后再新增最终 test 命令。
