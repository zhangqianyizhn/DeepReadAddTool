"""通用 baseline 构建：为任一已 profile 化的数据集跑出 matched baseline artifact。

流程（blind_reconstruction.py 的输入依赖）：
  1. 校验原始数据（各数据集的完整性检查不同，见 profile validator）；
  2. 索引（store_index/*_corpus.json）不完整时先入库建索引；
  3. 以固定输出目录运行 ov_test/run.py --step all（生成 + 评分一次完成）；
  4. 校验三件套：generated_answers.json / qa_eval_detailed_results.json / deepread_run.log。

baseline 覆盖该数据集的完整实验集（FinanceBench 141 / HotpotQA 100 / SyllabusQA 抽样 200），
blind_reconstruction 只把 train split 的案例喂给 Analyzer，与原实验纪律一致。

数据根目录默认 <workspace>/Data，可用环境变量 DEEPREAD_DATA_ROOT 覆盖（服务器上数据位置不同）。
"""

from __future__ import annotations

import argparse
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

sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(OLD_EXPERIMENT / "scripts"))
import dataset_profiles as profiles  # noqa: E402
import run_pilot as legacy  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------- 数据校验

def validate_financebench(profile: "profiles.DatasetProfile") -> None:
    jsonl = profile.raw_data
    if not jsonl.exists():
        raise FileNotFoundError(
            f"缺少原始数据：{jsonl}\n"
            "请把 FinanceBench 原始数据集放到 Data/FinanceBench/（或用 DEEPREAD_DATA_ROOT 指定数据根）。"
        )
    rows = legacy.load_jsonl(jsonl)
    doc_names = {str(row.get("doc_name")) for row in rows}
    if len(rows) != profile.total_count or len(doc_names) != profile.doc_count:
        raise RuntimeError(
            f"数据校验失败：应为 {profile.total_count} 题 / {profile.doc_count} 文档，"
            f"实际 {len(rows)} 题 / {len(doc_names)} 文档。"
        )
    root = jsonl.parents[1]
    missing = [
        name
        for name in sorted(doc_names)
        if not (root / "markdown" / f"{name}.md").exists()
        and not (root / "pdfs" / f"{name}.pdf").exists()
    ]
    if missing:
        raise RuntimeError(f"以下 {len(missing)} 个文档既无 markdown 也无 pdf：{missing[:5]} ...")


def validate_hotpotqa(profile: "profiles.DatasetProfile") -> None:
    if not profile.raw_data.exists():
        raise FileNotFoundError(f"缺少原始数据：{profile.raw_data}")
    articles = profile.raw_data.parent / "hotpot_articles.json"
    if not articles.exists():
        raise FileNotFoundError(f"缺少文章库：{articles}")
    if not (profile.splits_dir / "SPLIT_MANIFEST.json").exists():
        raise FileNotFoundError("缺少划分：请先运行 prepare_splits.py --dataset hotpotqa")


def validate_syllabusqa(profile: "profiles.DatasetProfile") -> None:
    if not profile.raw_data.is_dir():
        raise FileNotFoundError(f"缺少原始数据目录：{profile.raw_data}")
    if not Path(profile.env_overrides["SYLLABUSQA_DOC_DIR"]).is_dir():
        raise FileNotFoundError(f"缺少大纲 docx 目录：{profile.env_overrides['SYLLABUSQA_DOC_DIR']}")
    if not (profile.splits_dir / "SPLIT_MANIFEST.json").exists():
        raise FileNotFoundError("缺少划分：请先运行 prepare_splits.py --dataset syllabusqa")
    if not profile.harness_full_file().exists():
        raise FileNotFoundError(f"缺少合并实验集：{profile.harness_full_file()}")


VALIDATORS = {
    "financebench": validate_financebench,
    "hotpotqa": validate_hotpotqa,
    "syllabusqa": validate_syllabusqa,
}


# ---------------------------------------------------------------- 主流程

def index_is_complete(profile: "profiles.DatasetProfile") -> bool:
    if not profile.index_dir.is_dir():
        return False
    expected = profile.doc_count or 0
    return len(list(profile.index_dir.glob("*_corpus.json"))) >= expected


def make_config(profile: "profiles.DatasetProfile", path: Path, *, skip_ingestion: bool) -> None:
    config = {
        "project_name": f"{profile.display_name}MatchedBaseline",
        "dataset_name": profile.baseline_dataset_name,
        "adapter": {
            "module": profile.adapter_module,
            "class_name": profile.adapter_class,
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
            # matched baseline 的定义：两组均关闭旧标题工具
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
            "max_queries": profile.total_count,
            "skip_ingestion": skip_ingestion,
        },
        "paths": {
            "raw_data": str(profile.harness_full_file()),
            "doc_output_dir": str(profile.processed_dir),
            "vector_store": str(profile.index_dir),
            "output_dir": str(profile.baseline_dir),
            # 固定输出目录：可断点续跑，且与 blind_reconstruction 的读取路径一致
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


def verify_artifacts(profile: "profiles.DatasetProfile") -> None:
    problems: list[str] = []
    generated = profile.baseline_dir / "generated_answers.json"
    evaluated = profile.baseline_dir / "qa_eval_detailed_results.json"
    log = profile.baseline_dir / "deepread_run.log"
    if not generated.exists():
        problems.append(f"缺少 {generated.name}")
    else:
        count = len(legacy.load_json(generated).get("results", []))
        if count != profile.total_count:
            problems.append(f"{generated.name} 只有 {count} 条结果（应为 {profile.total_count}）")
    if not evaluated.exists():
        problems.append(f"缺少 {evaluated.name}")
    if not log.exists() or log.stat().st_size == 0:
        problems.append(f"缺少或非空：{log.name}")
    if problems:
        raise RuntimeError("baseline 产物不完整：" + "；".join(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="financebench", choices=sorted(profiles.PROFILES))
    parser.add_argument("--dry-run", action="store_true", help="只校验数据与环境，不调用 API")
    args = parser.parse_args()
    profile = profiles.get_profile(args.dataset)

    required = [HARNESS, OLD_EXPERIMENT / ".env"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少运行所需文件：\n" + "\n".join(missing))

    VALIDATORS[profile.name](profile)
    have_index = index_is_complete(profile)
    say(
        f"[数据就绪] {profile.display_name} {profile.total_count} 题 / {profile.doc_count} 文档；"
        f"索引{'已完整，将跳过入库' if have_index else '缺失，本轮将先入库建索引'}。"
    )
    if args.dry_run:
        say(f"[DryRun 完成] 输出目录将是 {profile.baseline_dir}；未调用 API。")
        return 0

    env_values = legacy.load_experiment_env()
    config_path = profile.baseline_dir.parent / "rebuild_baseline_config.yaml"
    make_config(profile, config_path, skip_ingestion=have_index)

    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env.update(profile.env_overrides)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env.setdefault("EMBEDDING_API_KEY", env_values["VOLCENGINE_API_KEY"])
    process_env.setdefault("EMBEDDING_BASE_URL", env_values.get("ARK_BASE_URL", ""))
    process_env["PYTHONUTF8"] = "1"

    say(
        f"[Baseline] {profile.total_count} 题，模型={env_values['STUDENT_MODEL']}；"
        f"输出={profile.baseline_dir}"
    )
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "all"],
        cwd=str(REPO / "ov_test"),
        env=process_env,
    )
    if result.returncode != 0:
        raise RuntimeError("Baseline 运行失败；修复后可重新运行本脚本断点续跑。")

    verify_artifacts(profile)
    say(f"[完成] baseline 三件套已就绪：{profile.baseline_dir}")
    say(f"[下一步] ./run_blind_reconstruction.sh --dataset {profile.name}")
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
