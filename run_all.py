"""单命令全流程编排：指定数据集的工具演化闭环一键串跑。

用法：
    python3 run_all.py                              # 三个数据集依次串行全流程
    python3 run_all.py --datasets financebench      # 只跑指定数据集（逗号分隔）
    python3 run_all.py --workers 8                  # 答题线程数（默认按数据集 profile）
    python3 run_all.py --dry-run                    # 只预检环境/数据/索引，不调用 API

每个数据集依次执行（脚本内部均有断点续跑，中断后重跑同一条命令即可）：
    prepare_splits(仅新数据集) → run_baseline → blind_reconstruction
    → dev_ab → repair_round2 → frozen_test61（含 SHA-256 冻结）

数据集间并行：不需要本脚本支持——直接开多个终端，每个跑
    ./run_all.sh --datasets <name>
即可。三个数据集的索引、runs/<dataset>/、ExperimentArtifacts/ 输出目录完全隔离，
无文件冲突；唯一共享约束是模型 API 的 QPS（429 由底层指数退避重试兜底）。

环境变量 DEEPREAD_DATA_ROOT 可覆盖数据根目录（默认 <workspace>/Data）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
VENV_PYTHON = WORKSPACE / "ruc-ov-eval-zqy-DeepRead" / ".venv" / "bin" / "python"
SCRIPTS = WORKSPACE / "agentic_rag_tool_evolution" / "scripts"
ENV_FILE = WORKSPACE / "agentic_rag_self_learning" / ".env"
DATA_ROOT = Path(os.environ.get("DEEPREAD_DATA_ROOT", str(WORKSPACE / "Data"))).expanduser().resolve()

ALL_DATASETS = ["financebench", "hotpotqa", "syllabusqa"]

# 每个数据集需要的原始数据路径（相对 DATA_ROOT）
RAW_DATA_HINTS = {
    "financebench": ["FinanceBench/data/financebench_open_source.jsonl"],
    "hotpotqa": ["HotpotQA/hotpot_qa_100.json", "HotpotQA/hotpot_articles.json"],
    "syllabusqa": ["SyllabusQA/train.csv", "SyllabusQA/syllabi"],
}


def say(message: str) -> None:
    print(message, flush=True)


def run_step(dataset: str, script: str, extra: list[str]) -> None:
    command = [str(VENV_PYTHON), str(SCRIPTS / script), "--dataset", dataset, *extra]
    say(f"\n===== [{dataset}] {script} =====")
    result = subprocess.run(command, cwd=str(WORKSPACE))
    if result.returncode != 0:
        raise RuntimeError(
            f"阶段失败：[{dataset}] {script}（退出码 {result.returncode}）。"
            "修复问题后重新运行同一条 run_all 命令即可从断点继续。"
        )


def preflight(datasets: list[str]) -> None:
    problems: list[str] = []
    if not VENV_PYTHON.exists():
        problems.append(f"缺少统一环境 {VENV_PYTHON}；请先 cd ruc-ov-eval-zqy-DeepRead && uv sync")
    if not ENV_FILE.exists():
        problems.append(f"缺少 {ENV_FILE}；请 cp .env.example 后填入 VOLCENGINE_API_KEY")
    for dataset in datasets:
        for hint in RAW_DATA_HINTS[dataset]:
            if not (DATA_ROOT / hint).exists():
                problems.append(f"[{dataset}] 缺少数据 {DATA_ROOT / hint}")
    if problems:
        raise RuntimeError("预检未通过：\n- " + "\n- ".join(problems))
    say(f"[预检通过] 数据集：{', '.join(datasets)}；数据根：{DATA_ROOT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", default=",".join(ALL_DATASETS),
                        help="逗号分隔，可选：" + ",".join(ALL_DATASETS))
    parser.add_argument("--workers", type=int, default=None,
                        help="答题线程数（默认按 profile：financebench=1，其余=4）")
    parser.add_argument("--ingest-workers", type=int, default=None, help="入库线程数（默认同 --workers）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    datasets = [item.strip() for item in args.datasets.split(",") if item.strip()]
    unknown = [item for item in datasets if item not in ALL_DATASETS]
    if unknown:
        raise ValueError(f"未知数据集：{unknown}（可选：{ALL_DATASETS}）")

    preflight(datasets)
    worker_args = ["--workers", str(args.workers)] if args.workers else []
    ingest_args = ["--ingest-workers", str(args.ingest_workers)] if args.ingest_workers else []

    if args.dry_run:
        for dataset in datasets:
            run_step(dataset, "run_baseline.py", ["--dry-run"])
        say("[dry-run] 预检完成；未执行任何计费阶段。")
        return 0

    for dataset in datasets:
        if dataset != "financebench":
            run_step(dataset, "prepare_splits.py", [])
        run_step(dataset, "run_baseline.py", worker_args + ingest_args)
        run_step(dataset, "blind_reconstruction.py", [])
        run_step(dataset, "dev_ab.py", worker_args)
        run_step(dataset, "repair_round2.py", worker_args)
        run_step(dataset, "frozen_test61.py", worker_args)
        say(f"\n[数据集完成] {dataset}")

    say("\n[全部完成] 各数据集报告见 agentic_rag_tool_evolution/runs/ 与 ExperimentArtifacts/。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 重新运行同一条命令即可从断点继续。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
