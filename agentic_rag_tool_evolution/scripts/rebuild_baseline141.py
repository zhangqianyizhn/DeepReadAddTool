"""从零重建 FinanceBench 141 题 matched baseline（跨平台，替代原 PowerShell 入口）。

用途：blind_reconstruction.py 需要读取
  ExperimentArtifacts/FinanceBenchFull141/Output/deepread_matched_baseline_141_0001/
    ├─ qa_eval_detailed_results.json   （Judge 逐题评分）
    └─ deepread_run.log                （Student 原始工具轨迹）
本脚本在缺少该 artifact 时，从原始数据集重新跑出完全一致的一份：
  1. 校验 Data/FinanceBench（141 题 / 82 文档 / markdown 或 pdf 齐全）；
  2. 如 82 文档索引（store_index/*_corpus.json）不存在，先入库建索引；
  3. 以固定输出目录运行 ov_test/run.py --step all（生成 + 评分一次完成）；
  4. 校验三件套产物齐全。

与原 Windows 流程的差异：输出目录关闭自动递增（auto_increment_output: false），
目录名固定为 blind_reconstruction 硬编码读取的 deepread_matched_baseline_141_0001，
中断后重新运行可在同一目录断点续跑。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
REPO = WORKSPACE / "ruc-ov-eval-zqy-DeepRead"
HARNESS = REPO / "ov_test" / "run.py"
OLD_EXPERIMENT = WORKSPACE / "agentic_rag_self_learning"

SOURCE_ROOT = WORKSPACE / "Data" / "FinanceBench"
SOURCE_JSONL = SOURCE_ROOT / "data" / "financebench_open_source.jsonl"
SOURCE_MARKDOWN = SOURCE_ROOT / "markdown"
SOURCE_PDFS = SOURCE_ROOT / "pdfs"

FULL_INDEX = OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "store_index"
FULL_PROCESSED = OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "processed_docs"

OUTPUT_DIR = (
    WORKSPACE
    / "ExperimentArtifacts"
    / "FinanceBenchFull141"
    / "Output"
    / "deepread_matched_baseline_141_0001"
)
EXPECTED_QUESTIONS = 141
EXPECTED_DOCS = 82

sys.path.insert(0, str(OLD_EXPERIMENT / "scripts"))
import run_pilot as legacy  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


def validate_source_data() -> list[dict[str, Any]]:
    """复刻原 run_full141_matched_baseline.ps1 的数据校验。"""
    if not SOURCE_JSONL.exists():
        raise FileNotFoundError(
            f"缺少原始数据：{SOURCE_JSONL}\n"
            "请把 FinanceBench 原始数据集放到工作区根的 Data/FinanceBench/ 下。"
        )
    rows = legacy.load_jsonl(SOURCE_JSONL)
    doc_names = {str(row.get("doc_name")) for row in rows}
    if len(rows) != EXPECTED_QUESTIONS or len(doc_names) != EXPECTED_DOCS:
        raise RuntimeError(
            f"数据校验失败：应为 {EXPECTED_QUESTIONS} 题 / {EXPECTED_DOCS} 文档，"
            f"实际 {len(rows)} 题 / {len(doc_names)} 文档。"
        )
    missing = [
        name
        for name in sorted(doc_names)
        if not (SOURCE_MARKDOWN / f"{name}.md").exists()
        and not (SOURCE_PDFS / f"{name}.pdf").exists()
    ]
    if missing:
        raise RuntimeError(
            f"以下 {len(missing)} 个文档既无 markdown 也无 pdf：{missing[:5]} ..."
        )
    return rows


def index_is_complete() -> bool:
    if not FULL_INDEX.is_dir():
        return False
    return len(list(FULL_INDEX.glob("*_corpus.json"))) == EXPECTED_DOCS


def make_config(path: Path, *, skip_ingestion: bool) -> None:
    config = {
        "project_name": "FinanceBenchFull141MatchedBaseline",
        "dataset_name": "FinanceBenchFull141MatchedBaseline",
        "adapter": {
            "module": "src.adapters.finance_bench_adapter",
            "class_name": "FinanceBenchAdapter",
        },
        "store": {
            "type": "DeepRead",
            "enable_vector": True,
            "enable_hybrid": False,
            "enable_semantic": False,
            "neighbor_window": "1,-1",
            "max_rounds": 50,
            "use_pymupdf": True,
            "source_header_enabled": True,
            "enable_session_pagination": False,
            "preload_directory_structure": False,
            #  matched baseline 的定义：两组均关闭旧标题工具
            "enable_document_title_search": False,
            "enable_structure_title_search": False,
            "agent_topk_max": 1,
            "pagination_candidate_limit": 1,
            "embedding_api_key": "${EMBEDDING_API_KEY}",
            "embedding_base_url": "${EMBEDDING_BASE_URL}",
            "embedding_model": "${EMBEDDING_MODEL_NAME}",
        },
        "execution": {
            "max_workers": 1,
            "ingest_workers": 1,
            "retrieval_topk": 1,
            "max_queries": EXPECTED_QUESTIONS,
            "skip_ingestion": skip_ingestion,
        },
        "paths": {
            "raw_data": str(SOURCE_JSONL),
            "doc_output_dir": str(FULL_PROCESSED),
            "vector_store": str(FULL_INDEX),
            "output_dir": str(OUTPUT_DIR),
            # 固定输出目录：可断点续跑，且与 blind_reconstruction.py 的硬编码路径一致
            "auto_increment_output": False,
        },
        # 生成与评测共用同一模型配置（与原实验 STUDENT=JUDGE 的设置一致）
        "llm": {
            "model": "${LLM_MODEL}",
            "temperature": 0,
            "base_url": "${LLM_BASE_URL}",
            "api_key": "${LLM_API_KEY}",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def verify_artifacts() -> None:
    problems: list[str] = []
    generated = OUTPUT_DIR / "generated_answers.json"
    evaluated = OUTPUT_DIR / "qa_eval_detailed_results.json"
    log = OUTPUT_DIR / "deepread_run.log"
    if not generated.exists():
        problems.append(f"缺少 {generated.name}")
    else:
        count = len(legacy.load_json(generated).get("results", []))
        if count != EXPECTED_QUESTIONS:
            problems.append(f"{generated.name} 只有 {count} 条结果（应为 {EXPECTED_QUESTIONS}）")
    if not evaluated.exists():
        problems.append(f"缺少 {evaluated.name}")
    if not log.exists() or log.stat().st_size == 0:
        problems.append(f"缺少或非空：{log.name}")
    if problems:
        raise RuntimeError("baseline 产物不完整：" + "；".join(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只校验数据与环境，不调用 API")
    args = parser.parse_args()

    required = [HARNESS, OLD_EXPERIMENT / ".env"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少运行所需文件：\n" + "\n".join(missing))

    rows = validate_source_data()
    have_index = index_is_complete()
    say(
        f"[数据就绪] {len(rows)} 题 / {EXPECTED_DOCS} 文档；"
        f"索引{'已完整，将跳过入库' if have_index else '缺失，本轮将先入库建索引'}。"
    )
    if args.dry_run:
        say(f"[DryRun 完成] 输出目录将是 {OUTPUT_DIR}；未调用 API。")
        return 0

    env_values = legacy.load_experiment_env()
    config_path = OUTPUT_DIR.parent / "rebuild_baseline_config.yaml"
    make_config(config_path, skip_ingestion=have_index)

    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env.setdefault("EMBEDDING_API_KEY", env_values["VOLCENGINE_API_KEY"])
    process_env.setdefault("EMBEDDING_BASE_URL", env_values.get("ARK_BASE_URL", ""))
    process_env["PYTHONUTF8"] = "1"

    say(f"[Baseline] {EXPECTED_QUESTIONS} 题，模型={env_values['STUDENT_MODEL']}；输出={OUTPUT_DIR}")
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "all"],
        cwd=str(REPO / "ov_test"),
        env=process_env,
    )
    if result.returncode != 0:
        raise RuntimeError("Baseline 运行失败；修复后可重新运行本脚本断点续跑。")

    verify_artifacts()
    say(f"[完成] baseline 三件套已就绪：{OUTPUT_DIR}")
    say("[下一步] cd agentic_rag_tool_evolution && ./run_blind_reconstruction.sh")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 重新运行本脚本会在同一输出目录断点续跑。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
