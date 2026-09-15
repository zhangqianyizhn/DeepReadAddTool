from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import run_pilot as core  # noqa: E402


FULL_ROOT = core.PROJECT_DIR / "data" / "generated" / "full141"
FULL_INDEX = FULL_ROOT / "DeepRead" / "store_index"
FULL_PROCESSED = FULL_ROOT / "DeepRead" / "processed_docs"
FULL_MANIFEST = FULL_ROOT / "full141_manifest.json"


def configure_full_paths() -> None:
    # Reuse the thoroughly tested pilot runner while redirecting every generated
    # artifact to the full141 experiment area. SOURCE_JSONL remains read-only.
    core.PILOT_ROOT = FULL_ROOT
    core.PILOT_JSONL = core.SOURCE_JSONL
    core.PILOT_INDEX = FULL_INDEX
    core.PILOT_PROCESSED = FULL_PROCESSED
    core.PILOT_MANIFEST = FULL_MANIFEST


def find_completed_pilot() -> Path:
    sessions = sorted(
        (path for path in core.RUNS_DIR.glob("pilot_*") if (path / "RESULT_SUMMARY.md").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        raise RuntimeError("找不到已完成的20题 Pilot；141题不会在 Pilot 失败时启动。")
    return sessions[0]


def load_best_candidate(pilot_session: Path) -> dict[str, Any]:
    comparison = core.load_json(pilot_session / "comparison.json")
    candidates = core.load_json(pilot_session / "teacher_candidates.json").get("candidates", [])
    best_id = comparison.get("best_candidate_id")
    for candidate in candidates:
        if candidate.get("candidate_id") == best_id:
            return candidate
    raise RuntimeError(f"找不到 Pilot 选出的最佳提示词：{best_id}")


def prepare_full_manifest(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 141:
        raise RuntimeError(f"FinanceBench 应为141题，实际读到 {len(rows)} 题。")
    FULL_PROCESSED.mkdir(parents=True, exist_ok=True)
    splits = {row["financebench_id"]: "full" for row in rows}
    core.save_json(FULL_MANIFEST, {
        "source": str(core.SOURCE_JSONL),
        "source_is_read_only": True,
        "evaluation_scope": "descriptive_full141_includes_pilot_questions",
        "question_count": len(rows),
        "document_count": len({row["doc_name"] for row in rows}),
        "splits": splits,
    })


def find_full_session(candidate_id: str) -> Path | None:
    sessions = sorted(
        (path for path in core.RUNS_DIR.glob("full141_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for session in sessions:
        metadata_path = session / "run_metadata.json"
        if not metadata_path.exists():
            continue
        metadata = core.load_json(metadata_path)
        if metadata.get("candidate_id") != candidate_id:
            continue
        if (session / "FULL141_RESULT_SUMMARY.md").exists():
            core.say(f"[141题] 已有完整结果，直接复用：{session}")
            return session
        return session
    return None


def write_full_report(
    session: Path,
    pilot_session: Path,
    candidate: dict[str, Any],
    records: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    value = core.metrics(records)
    lines = [
        "# FinanceBench 141题：优化提示词完整运行结果",
        "",
        "## 实验范围说明",
        "",
        "本次将20题 Pilot 选出的最佳 Agent 指令冻结后，应用到 FinanceBench 全部141题。由于141题包含参与 Pilot 学习与选择的20题，因此该结果是描述性全量结果，不是严格独立的 held-out 测试结果。",
        "",
        "## 使用的提示词",
        "",
        f"候选：`{candidate.get('candidate_id')}`（{candidate.get('strategy')}）",
        "",
        *[f"- {instruction}" for instruction in candidate.get("instructions", [])],
        "",
        "## 全量指标",
        "",
        "| 题数 | 平均得分(0-4) | 归一化准确率 | Evidence Recall | 平均输入Token | 平均耗时(s) |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {int(value['count'])} | {value['average_score']:.3f} | {value['normalized_accuracy']:.2%} | {value['average_recall']:.2%} | {value['average_input_tokens']:.0f} | {value['average_latency_sec']:.1f} |",
        "",
        "## 结果位置",
        "",
        f"- 20题 Pilot：`{pilot_session}`",
        f"- 141题完整输出：`{output_dir}`",
        "",
    ]
    (session / "FULL141_RESULT_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    core.save_json(session / "full141_metrics.json", {
        "scope": "descriptive_full141_includes_pilot_questions",
        "candidate_id": candidate.get("candidate_id"),
        "metrics": value,
        "output_dir": str(output_dir),
    })


def ensure_consistent_judge(session: Path, output_dir: Path, env: dict[str, str]) -> None:
    """Never mix scores from different judge models in one result file."""
    metadata_path = session / "run_metadata.json"
    metadata = core.load_json(metadata_path)
    previous_model = str(metadata.get("judge_model") or "unknown")
    current_model = env["JUDGE_MODEL"]
    if previous_model == current_model:
        return

    judged_path = output_dir / "judged_results.json"
    if judged_path.exists():
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", previous_model)
        backup_path = output_dir / f"judged_results.backup_{safe_name}.json"
        if backup_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = output_dir / f"judged_results.backup_{safe_name}_{timestamp}.json"
        shutil.move(str(judged_path), str(backup_path))
        core.say(f"[Judge切换] 已备份旧评分：{backup_path.name}")

    metadata["previous_judge_model"] = previous_model
    metadata["judge_model"] = current_model
    metadata["judge_changed_at"] = datetime.now().isoformat()
    core.save_json(metadata_path, metadata)
    core.say(f"[Judge切换] {previous_model} -> {current_model}；将从第1题统一重新评分，141份Student答案不会重跑。")


def main() -> int:
    core.validate_layout()
    env = core.load_experiment_env()
    configure_full_paths()
    rows = core.load_jsonl(core.SOURCE_JSONL)
    prepare_full_manifest(rows)

    pilot_session = find_completed_pilot()
    candidate = load_best_candidate(pilot_session)
    candidate_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(candidate["candidate_id"]))

    session = find_full_session(candidate_id)
    if session is not None and (session / "FULL141_RESULT_SUMMARY.md").exists():
        return 0
    if session is None:
        session = core.RUNS_DIR / datetime.now().strftime("full141_%Y%m%d_%H%M%S")
        session.mkdir(parents=True, exist_ok=False)
        core.save_json(session / "run_metadata.json", {
            "started_at": datetime.now().isoformat(),
            "scope": "descriptive_full141_includes_pilot_questions",
            "candidate_id": candidate_id,
            "student_model": env["STUDENT_MODEL"],
            "judge_model": env["JUDGE_MODEL"],
            "source_data_modified": False,
        })
    else:
        core.say(f"[141题断点续跑] 继续：{session.name}")

    output_dir = core.run_student(
        session,
        f"optimized_{candidate_id}",
        candidate["instructions"],
        env,
        rows,
        allow_ingest=True,
    )
    ensure_consistent_judge(session, output_dir, env)
    records = core.judge_output(output_dir, rows, env)
    write_full_report(session, pilot_session, candidate, records, output_dir)
    core.say("\n[完成] 优化提示词的 FinanceBench 141题运行与评分已完成。")
    core.say(f"结果摘要：{session / 'FULL141_RESULT_SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        core.say("\n[已停止] 重新运行通宵脚本会继续复用已有索引、答案和评分。")
        raise SystemExit(130)
    except Exception as exc:
        core.say(f"\n[失败] {exc}")
        raise SystemExit(1)
