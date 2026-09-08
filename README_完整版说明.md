# DeepRead Agent 自学习与自主工具演化：完整源码包

这份包用于代码审阅和复现准备。它不是单独的 `scripts` 文件夹，而是保留了实验实际依赖的四个同级工程目录。

## 1. 为什么只发 `agentic_rag_self_learning_v2/scripts` 不够

`v2/scripts` 只负责编排多轮实验。它并不独立完成模型调用、DeepRead检索或评测，而是继续引用：

- `agentic_rag_self_learning/scripts/run_pilot.py`：API调用、配置加载、Judge、结果解析等基础Harness；
- `ruc-ov-eval-zqy-DeepRead/ov_test/run.py`：真正启动DeepRead Benchmark；
- `ruc-ov-eval-zqy-DeepRead/DeepRead/`：Agent循环、工具Schema、检索与阅读工具；
- `agentic_rag_self_learning_v2/data/`：Train/Dev/Test划分及轨迹；
- 后续 `agentic_rag_tool_evolution/`：Analyzer自主诊断、生成Python工具、Dev A/B、自主修复和冻结Test。

因此只看 `v2/scripts`，会看不到模型API怎样变成Agent、工具怎样接入DeepRead、Judge怎样评分，以及后续自主写工具的完整闭环。

## 2. 四个核心目录

### `ruc-ov-eval-zqy-DeepRead`

底层RAG/DeepRead运行时，主要入口和组件：

- `ov_test/run.py`：Benchmark入口；
- `ov_test/src/pipeline.py`：数据准备、入库、检索、生成和评测流水线；
- `DeepRead/agent/runner.py`：LLM tool-calling循环；
- `DeepRead/tool/schema.py`：提供给模型的工具定义；
- `DeepRead/tool/retrieval.py`：BM25、向量、文档结构等检索实现；
- `DeepRead/prompt/system.py`：Student系统提示词；
- `ov_test/src/adapters/finance_bench_adapter.py`：FinanceBench适配器。

### `agentic_rag_self_learning`

最初的Teacher–Student实验和所有后续实验共用的基础Harness：

- `scripts/run_pilot.py`：环境变量、模型调用、JSON重试、Student配置生成、Judge；
- `scripts/run_baseline141.py`、`scripts/run_full141.py`：141题流程；
- `prompts/`：Teacher/Student相关提示词；
- `schemas/`：结构化输出约束；
- `config/`：实验配置模板；
- `.env.example`：配置示例，不含真实Key。

### `agentic_rag_self_learning_v2`

研究内容2的严格Train/Dev/Test版本：

- `scripts/content2.py`：数据划分、Baseline、Teacher分析和第一轮流程；
- `scripts/round2.py`：全局技能候选；
- `scripts/round3.py`：按问题路由经验；
- `scripts/round4.py`：触发条件与回归控制；
- `data/splits/`：固定60/20/61划分；
- `data/trajectories/`：供Analyzer使用的轨迹材料；
- 根目录PowerShell脚本：各轮运行入口。

### `agentic_rag_tool_evolution`

从“改提示词”转向“自主生成可执行工具”的完整实验：

- `scripts/blind_reconstruction.py`：只读Train失败/成功轨迹，Analyzer选择能力，Repair生成ToolSpec、代码、规则和测试；
- `scripts/dev_ab.py`：把候选动态接入DeepRead并做Dev A/B；
- `scripts/repair_round2.py`：读取Dev反馈后自主修复工具；
- `scripts/frozen_test61.py`：冻结代码、模型和划分后运行Test61；
- `reports/`：错误审计和阶段报告。

## 3. 完整调用关系

```text
PowerShell入口
  └─ v2或tool_evolution实验脚本
       ├─ 读取Train/Dev/Test、轨迹和Prompt
       ├─ 调用run_pilot.py中的LLM/JSON/Judge辅助函数
       ├─ 生成临时config.yaml
       └─ 启动ruc-ov-eval-zqy-DeepRead/ov_test/run.py
            └─ Pipeline
                 └─ DeepRead agent/runner.py
                      ├─ 调用Student API
                      ├─ 执行BM25/向量/结构/阅读工具
                      └─ 可选执行AI生成的candidate_tool.py
       └─ Judge逐题评分
       └─ Analyzer/Repair根据允许的数据进入下一轮
```

这里的“Agent”不是某个模型名称，而是：

```text
模型API + 角色Prompt + 上下文/状态 + 工具接口
+ Python调度循环 + 重试/停止条件 + 轨迹记录 + Judge/Validator
```

## 4. 建议师兄先看的文件

如果目标是快速审查Agent架构，建议顺序：

1. `agentic_rag_tool_evolution/README.md`；
2. `agentic_rag_tool_evolution/scripts/blind_reconstruction.py`；
3. `agentic_rag_tool_evolution/scripts/dev_ab.py`；
4. `agentic_rag_self_learning/scripts/run_pilot.py`；
5. `ruc-ov-eval-zqy-DeepRead/DeepRead/agent/runner.py`；
6. `ruc-ov-eval-zqy-DeepRead/ov_test/src/pipeline.py`；
7. `reference_artifacts/financebench_round1/analysis.json`；
8. `reference_artifacts/financebench_round2/candidate_tool.py`；
9. `reference_artifacts/financebench_test61/FROZEN_TEST61_REPORT.md`。

## 5. Reference artifacts

为了避免把全部运行目录塞进源码包，`reference_artifacts/` 仅保留一套能够说明闭环的FinanceBench产物：

```text
Train轨迹
→ Analyzer analysis.json
→ 第一版candidate_tool.py
→ Dev A/B
→ Round2 candidate_tool.py
→ 冻结Test61报告和逐题Judge结果
```

这部分用于证明代码实际运行过，而不是重新整理出的伪代码。

## 6. 环境准备

推荐Python 3.11或仓库声明版本。底层仓库使用 `pyproject.toml` 和 `uv.lock`：

```powershell
cd .\ruc-ov-eval-zqy-DeepRead
uv sync
```

基础实验的额外依赖：

```powershell
cd ..\agentic_rag_self_learning
python -m pip install -r .\requirements-pilot.txt
Copy-Item .\.env.example .\.env
```

然后只在本地 `.env` 中填写Key。不要上传或提交真实 `.env`。

## 7. 典型运行顺序

### V2提示词/经验自学习

```powershell
cd .\agentic_rag_self_learning_v2
.\run_round1.ps1
.\run_round2.ps1
.\run_round3.ps1
.\run_round4.ps1
```

### DeepSeek自主工具生成

```powershell
cd .\agentic_rag_tool_evolution
.\run_blind_reconstruction.ps1
.\run_dev_ab.ps1
.\run_autonomous_repair_round2.ps1
.\run_frozen_test61.ps1
```

这些脚本按相对位置寻找另外三个同级目录，所以请保持当前目录结构。

## 8. 未放入压缩包的内容

为了安全和体积，源码包明确排除：

- `.env`和所有真实API Key；
- `.git`和本机虚拟环境；
- `__pycache__`、`.pyc`和日志；
- 大部分历史 `runs/`；
- FinanceBench原始PDF；
- 约500MB的processed docs和向量/BM25索引。

因此，这是一份**完整源码与代表性产物包**，不是包含全部运行数据的离线镜像。若要端到端重跑，还需要在包根目录提供：

```text
Data/FinanceBench/
agentic_rag_self_learning/data/generated/full141/DeepRead/processed_docs/
agentic_rag_self_learning/data/generated/full141/DeepRead/store_index/
```

索引建议在目标机器重新构建，因为旧索引和配置中可能包含本机绝对路径。

## 9. 安全说明

本包生成后会检查：

- 不包含名为 `.env` 的文件；
- 不包含常见API Key形式；
- Python文件可以被AST解析；
- JSON文件可以正常读取。

如果需要将完整PDF和轨迹数据另行分享，建议作为独立数据包发送，不要与源码和Key混在一起。
