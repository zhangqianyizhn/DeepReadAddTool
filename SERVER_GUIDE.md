# 服务器运行教程（Linux / macOS 通用）

本文件是在**全新机器**上从零复现三个数据集（FinanceBench / HotpotQA / SyllabusQA）
工具演化实验的完整步骤。所有入口均为 bash 脚本，无需 PowerShell。

## 1. 获取代码

```bash
git clone <你的仓库地址> DeepReadAddTool     # 或 git pull / rsync 同步
cd DeepReadAddTool
```

git 不会同步以下内容（均在 .gitignore 中），需在本机准备：
`.env`、`Data/`、索引、`runs/`、`ExperimentArtifacts/`。

## 2. 安装环境（唯一一次）

```bash
cd ruc-ov-eval-zqy-DeepRead
uv sync                # 需要 Python >=3.11；无 uv 时先 curl -LsSf https://astral.sh/uv/install.sh | sh
cd ..
```

精简后的依赖只有 52 个包（不含 torch/transformers），CPU 服务器即可。

## 3. 配置 API Key

```bash
cp agentic_rag_self_learning/.env.example agentic_rag_self_learning/.env
vi agentic_rag_self_learning/.env      # 填入 VOLCENGINE_API_KEY=...
```

模型默认值（deepseek-v4-flash / doubao-embedding-vision / 火山方舟 base_url）已在
`.env.example` 中配好，通常只需填 Key 一行。

## 4. 放置数据集

默认数据根是 `<工作区>/Data`。结构要求：

```text
Data/
├─ FinanceBench/
│   ├─ data/financebench_open_source.jsonl
│   └─ markdown/ 或 pdfs/          # 82 个文档，至少覆盖每个 doc_name 之一
├─ HotpotQA/
│   ├─ hotpot_qa_100.json
│   └─ hotpot_articles.json
└─ SyllabusQA/
    ├─ train.csv / val.csv / test.csv
    └─ syllabi/*.docx
```

**数据在别处时**（服务器上很常见），两种方式任选：

```bash
# 方式 A：软链（推荐，与 mac 本机当前做法一致）
ln -s /你的/数据路径/Data ./Data

# 方式 B：环境变量（所有脚本都会读）
export DEEPREAD_DATA_ROOT=/你的/数据路径/Data
```

注意 `DEEPREAD_DATA_ROOT` 需要在每次会话中生效（写进 `~/.bashrc` 或在命令前加）。

## 5. 预检（不消耗 API 额度）

```bash
./run_all.sh --dry-run
```

预检会检查 venv、`.env`、三个数据集的数据文件是否齐全，并打印将执行的全部命令。
缺什么会逐条列出。

## 6. 一键全流程

```bash
./run_all.sh
```

这一条命令对三个数据集依次执行：

```text
prepare_splits（仅 HotpotQA/SyllabusQA：40%/20%/40% 划分，SyllabusQA 先抽样 200 题）
  → run_baseline（索引缺失则先入库；跑 baseline + Judge 评分，产出轨迹 artifact）
  → blind_reconstruction（Analyzer 诊断 train 失败 → Repair Agent 生成候选工具）
  → dev_ab（dev 集严格 A/B + 固定 Judge）
  → repair_round2（Repair Agent 读 dev 反馈自主修复 → 复测）
  → frozen_test61（SHA-256 冻结后跑 test 集最终 A/B）
```

只跑部分数据集：

```bash
./run_all.sh --datasets financebench
./run_all.sh --datasets hotpotqa,syllabusqa
```

**断点续跑**：所有阶段都有断点（入库按文档跳过、答案/Judge 评分按文件复用、
候选与冻结清单按 SHA-256 校验）。中断或失败后，直接重新运行 `./run_all.sh` 即可。

**防休眠**：macOS 下脚本自动用 `caffeinate` 包裹；Linux 服务器建议配合
`tmux`/`nohup` 使用：

```bash
nohup ./run_all.sh > run_all.log 2>&1 &
```

## 7. 预计耗时与成本

每个数据集 = (全量 baseline + dev A/B 两组 + 修复复测 + test A/B 两组) ×
每题最多 50 轮工具调用。粗略量级：FinanceBench 约 500 题次、HotpotQA 约 300 题次、
SyllabusQA 约 700 题次。请确认火山方舟套餐余额充足；脚本遇到 403/欠费会立即停止并保留断点。

## 8. 查看结果

```text
agentic_rag_tool_evolution/runs/<dataset>/blind_*/
├─ BLIND_RECONSTRUCTION_REPORT.md        # 盲重建报告
├─ dev_ab/DEV_AB_REPORT.md               # dev A/B
└─ repair_round2/
    ├─ dev_ab/ROUND2_DEV_AB_REPORT.md    # 修复后 dev 复测
    └─ frozen_test61/FROZEN_TEST61_REPORT.md   # 冻结 test 最终报告
ExperimentArtifacts/<数据集>/Output/deepread_matched_baseline_*/   # baseline 产物
```

（FinanceBench 的 runs 直接在 `runs/` 根下，与历史实验目录结构保持一致。）

## 9. 单独运行某一阶段（调试用）

```bash
cd agentic_rag_tool_evolution
./run_blind_reconstruction.sh --dataset syllabusqa --dry-run
./run_dev_ab.sh --dataset hotpotqa
./run_autonomous_repair_round2.sh --dataset hotpotqa
./run_frozen_test61.sh --dataset hotpotqa
# baseline 单独重建：
../ruc-ov-eval-zqy-DeepRead/.venv/bin/python scripts/run_baseline.py --dataset syllabusqa --dry-run
```

不带 `--dataset` 时一律默认 `financebench`，与原实验命令完全兼容。

## 常见问题

- **"缺少统一环境 .venv"**：没做第 2 步，或 `uv sync` 在别的目录执行了。
- **"环境变量 XXX 未设置"**：`.env` 没填全，参照 `.env.example`。
- **划分不一致报错**：`data/splits/<dataset>/` 是冻结产物；不要手改，确认后整个删除再重跑
  `prepare_splits.py --dataset <name> --force`。
- **服务器无 GPU**：不需要。PDF 解析走 pymupdf，Embedding 走火山方舟 API。
