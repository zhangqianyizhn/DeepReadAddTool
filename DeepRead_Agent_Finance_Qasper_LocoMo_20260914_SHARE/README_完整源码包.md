# DeepRead Agent 工具演化：完整源码交接包

整理日期：2026-09-14

这个目录是给项目协作者使用的**源码快照**。它汇总了共享的 DeepRead 运行框架，以及目前三个数据集方向中最新、实际运行过的实验代码：FinanceBench、Qasper 和 LocoMo。

本包只由原目录复制整理而成，没有修改或删除原项目。目录之间的相对依赖保持不变，因此不要只单独拿走某一个 `scripts` 文件夹。

## 1. 目录与版本说明

| 目录 | 作用 | 当前定位 |
|---|---|---|
| `ruc-ov-eval-zqy-DeepRead` | DeepRead/benchmark 公共运行框架 | 四组实验共同依赖 |
| `agentic_rag_self_learning` | API 配置、模型调用、早期 Student/Teacher 公共代码 | 公共依赖，`.env` 应放这里 |
| `agentic_rag_self_learning_v2` | FinanceBench 划分、轨迹和第二版自学习代码 | FinanceBench 公共依赖 |
| `agentic_rag_tool_evolution` | FinanceBench 盲发现、单工具生成、Dev 修复、冻结 Test61 | **FinanceBench 最新自主工具主线** |
| `agentic_rag_tool_evolution_qasper` | Qasper 公共模块和第一版实验 | 后续 Qasper/LocoMo 的代码依赖 |
| `agentic_rag_tool_evolution_qasper_blind_v2` | canonical text、论文隔离的单工具盲实验 | **Qasper 最新严格单工具主线** |
| `agentic_rag_tool_evolution_locomo` | 对话隔离划分、单工具生成、一次 Dev 修复、冻结 Test | **LocoMo 最新主线** |
| `selected_artifacts` | 各数据集 AI 生成的工具、诊断、冻结清单和核心报告 | 便于代码审计和结果核对 |

## 2. API Key 与模型配置

进入包根目录后，只需要从模板生成 `.env`：

```powershell
Copy-Item ".\agentic_rag_self_learning\.env.example" ".\agentic_rag_self_learning\.env"
notepad ".\agentic_rag_self_learning\.env"
```

只填写：

```dotenv
VOLCENGINE_API_KEY=在这里粘贴火山方舟APIKey
```

模板中的当前模型配置为：

```dotenv
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
STUDENT_MODEL=deepseek-v4-flash
TEACHER_MODEL=deepseek-v4-flash
JUDGE_MODEL=deepseek-v4-flash
EMBEDDING_MODEL_NAME=doubao-embedding-vision
```

`.env` 包含真实密钥，不能提交、截图或再次打包。本交接包中没有 `.env`。

## 3. 环境准备

建议使用 Windows PowerShell 和 Python 3.10/3.11。在包根目录创建独立虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\ruc-ov-eval-zqy-DeepRead"
python -m pip install python-dotenv openai pyyaml tqdm pymupdf
```

若仓库中的依赖文件与上面的最小依赖有冲突，以 `ruc-ov-eval-zqy-DeepRead` 自带的 `pyproject.toml` 和各实验 README 为准。

## 4. 数据说明

源码包已经包含：

- 代码、PowerShell 入口和配置模板；
- 实验使用的 Train/Dev/Test 划分文件；
- canonical inventory/units；
- 少量轨迹与最终生成工具、报告。

源码包没有包含：

- FinanceBench 财报 PDF、Qasper 原始论文 PDF、LocoMo 原始全集；
- `processed_docs`、`store_index` 等可重新生成的大型索引；
- 完整 `runs/output`、缓存和日志；
- 任何 API Key。

因此，**可以直接阅读、审计和继续开发全部代码，但在新电脑上正式重跑前仍需按各 README 放置原始数据**。如果在原来的 `D:\桌面\DeepRead` 环境运行，已有数据和索引可以继续复用；如果把 ZIP 发到其他电脑，需要另行同步数据目录。

## 5. 各数据集运行入口

以下命令均在这个交接包的根目录下执行。

### 5.1 FinanceBench

```powershell
cd ".\agentic_rag_tool_evolution"
.\run_blind_reconstruction.ps1 -DryRun
.\run_blind_reconstruction.ps1
.\run_dev_ab.ps1
.\run_autonomous_repair_round2.ps1
.\run_frozen_test61.ps1
```

流程是：Train 轨迹盲诊断 → AI 生成一个工具 → Dev A/B → AI 根据 Dev 反馈修复一次 → 冻结 Test61。

最终 Test61：准确率 `90.98% → 90.98%`，1 胜/59 平/1 负；输入 Token 约下降 50.07%，耗时约下降 35.06%。

### 5.2 Qasper 严格单工具主线

```powershell
cd ".\agentic_rag_tool_evolution_qasper_blind_v2"
.\run_blind_train_then_dev.ps1
.\run_frozen_test120.ps1
```

最终 Test120：8 胜/104 平/8 负，净分 -4；准确率 `82.08% → 81.25%`，输入 Token 下降约 10.72%，耗时下降约 26.90%。

### 5.3 LocoMo

```powershell
cd ".\agentic_rag_tool_evolution_locomo"
.\run_train_generate.ps1 -DryRun
.\run_all.ps1
```

也可分阶段运行：

```powershell
.\run_train_generate.ps1
.\run_dev_ab.ps1
.\run_dev_repair.ps1
.\run_frozen_test.ps1
```

最终 conversation-disjoint Test100：12 胜/83 平/5 负，净分 +13；准确率 `86.75% → 90.00%`，输入 Token 下降约 34.57%，耗时下降约 36.60%。这是目前跨数据集自主单工具实验中最明确的正向 Test 结果。

## 6. 去哪里看 AI 生成的代码

为避免在巨大的运行目录里寻找，关键快照已经整理到：

```text
selected_artifacts/
├─ FinanceBench/
├─ Qasper/
└─ LocoMo/
```

每个目录至少包含下列几类文件中的一部分：

- `analysis.json`：Analyzer 从训练轨迹得到的诊断与能力提议；
- `candidate.json`：ToolSpec、调用策略、自测定义等结构化结果；
- `candidate_tool.py`：AI 实际生成并通过安全/合成测试的工具代码；
- `*_REPORT.md`：Dev 或冻结 Test 的汇总与逐题变化；
- `*MANIFEST.json`：冻结时的代码、配置、数据划分哈希。

这些 artifact 是审计材料；真正控制流程的 Harness 在各实验目录的 `scripts/` 中。

## 7. 交接时必须说明的边界

1. “完整源码”不等于“完整运行数据”。原始数据、PDF 和大型索引因体积与授权问题没有包含。
2. Qasper 公共模块被 Qasper blind v2 和 LocoMo 复用，所以 `agentic_rag_tool_evolution_qasper` 不能删除。
3. FinanceBench 会复用 `agentic_rag_self_learning`、`agentic_rag_self_learning_v2` 和 DeepRead 公共框架，所以这些目录也不能删除。
4. `selected_artifacts` 中既有正结果也有负结果；保留它们是为了保证研究过程可核查，而不是把所有分支都宣称为有效改进。
5. 冻结 Test 的结果只能用于报告泛化效果，不应再反馈给 Analyzer/Repair Agent 调参。
