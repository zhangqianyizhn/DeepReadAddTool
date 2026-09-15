from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import run_pilot as core  # noqa: E402
import run_full141 as full  # noqa: E402


def find_or_create_session(env: dict[str, str]) -> Path:
    sessions = sorted(
        (path for path in core.RUNS_DIR.glob("baseline141_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for session in sessions:
        metadata_path = session / "run_metadata.json"
        if not metadata_path.exists():
            continue
        metadata = core.load_json(metadata_path)
        if (
            metadata.get("student_model") == env["STUDENT_MODEL"]
            and metadata.get("judge_model") == env["JUDGE_MODEL"]
        ):
            return session

    session = core.RUNS_DIR / datetime.now().strftime("baseline141_%Y%m%d_%H%M%S")
    session.mkdir(parents=True, exist_ok=False)
    core.save_json(session / "run_metadata.json", {
        "started_at": datetime.now().isoformat(),
        "group": "baseline",
        "agent_instructions": [],
        "student_model": env["STUDENT_MODEL"],
        "judge_model": env["JUDGE_MODEL"],
        "source_data_modified": False,
        "reuses_full141_index": True,
    })
    return session


def find_optimized_results() -> tuple[Path, list[dict[str, Any]]]:
    sessions = sorted(
        (path for path in core.RUNS_DIR.glob("full141_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for session in sessions:
        metrics_path = session / "full141_metrics.json"
        if not metrics_path.exists():
            continue
        metrics = core.load_json(metrics_path)
        output_dir = Path(metrics["output_dir"])
        judged_path = output_dir / "judged_results.json"
        if judged_path.exists():
            records = core.load_json(judged_path).get("results", [])
            if len(records) == 141:
                return session, records
    raise RuntimeError("找不到已完成的优化组141题统一评分结果。")


def percent_change(new: float, old: float) -> float | None:
    return None if old == 0 else (new / old - 1) * 100


def paired_summary(baseline: list[dict[str, Any]], optimized: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_by_id = {row["financebench_id"]: row for row in baseline}
    optimized_by_id = {row["financebench_id"]: row for row in optimized}
    if set(baseline_by_id) != set(optimized_by_id):
        raise RuntimeError("Baseline与优化组的financebench_id集合不一致，拒绝错误比较。")

    pairs = []
    for financebench_id in sorted(baseline_by_id):
        before = baseline_by_id[financebench_id]
        after = optimized_by_id[financebench_id]
        pairs.append({
            "financebench_id": financebench_id,
            "question_type": before.get("question_type"),
            "question": before["question"],
            "gold_answer": before["gold_answer"],
            "baseline_answer": before["student_answer"],
            "optimized_answer": after["student_answer"],
            "baseline_score": before["judge_score"],
            "optimized_score": after["judge_score"],
            "score_delta": after["judge_score"] - before["judge_score"],
            "baseline_judge_reasoning": before["judge_reasoning"],
            "optimized_judge_reasoning": after["judge_reasoning"],
            "baseline_recall": before["retrieval_recall"],
            "optimized_recall": after["retrieval_recall"],
            "baseline_input_tokens": before["input_tokens"],
            "optimized_input_tokens": after["input_tokens"],
            "baseline_output_tokens": before["output_tokens"],
            "optimized_output_tokens": after["output_tokens"],
            "baseline_latency_sec": before["latency_sec"],
            "optimized_latency_sec": after["latency_sec"],
        })

    baseline_metrics = core.metrics(baseline)
    optimized_metrics = core.metrics(optimized)
    return {
        "baseline_metrics": baseline_metrics,
        "optimized_metrics": optimized_metrics,
        "accuracy_absolute_percentage_points": (
            optimized_metrics["normalized_accuracy"] - baseline_metrics["normalized_accuracy"]
        ) * 100,
        "accuracy_relative_percent": percent_change(
            optimized_metrics["normalized_accuracy"], baseline_metrics["normalized_accuracy"]
        ),
        "input_token_change_percent": percent_change(
            optimized_metrics["average_input_tokens"], baseline_metrics["average_input_tokens"]
        ),
        "latency_change_percent": percent_change(
            optimized_metrics["average_latency_sec"], baseline_metrics["average_latency_sec"]
        ),
        "wins": sum(pair["score_delta"] > 0 for pair in pairs),
        "ties": sum(pair["score_delta"] == 0 for pair in pairs),
        "losses": sum(pair["score_delta"] < 0 for pair in pairs),
        "net_score_change": sum(pair["score_delta"] for pair in pairs),
        "pairs": pairs,
    }


def write_report(session: Path, comparison: dict[str, Any], optimized_session: Path, output_dir: Path) -> None:
    baseline = comparison["baseline_metrics"]
    optimized = comparison["optimized_metrics"]
    acc_rel = comparison["accuracy_relative_percent"]
    acc_rel_text = "N/A" if acc_rel is None else f"{acc_rel:+.2f}%"
    token_change = comparison["input_token_change_percent"]
    latency_change = comparison["latency_change_percent"]
    lines = [
        "# FinanceBench 141题：Baseline与自学习提示词正式对照",
        "",
        "两组使用同一141题、同一Student、同一Judge、同一索引和检索配置；唯一实验变量为是否注入Teacher生成的 `minimal_patch` Agent指令。",
        "",
        "## 总体结果",
        "",
        "| 指标 | Baseline | 优化提示词 | 变化 |",
        "|---|---:|---:|---:|",
        f"| 平均得分（0–4） | {baseline['average_score']:.3f} | {optimized['average_score']:.3f} | {optimized['average_score'] - baseline['average_score']:+.3f} |",
        f"| 归一化准确率 | {baseline['normalized_accuracy']:.2%} | {optimized['normalized_accuracy']:.2%} | {comparison['accuracy_absolute_percentage_points']:+.2f}个百分点（相对{acc_rel_text}） |",
        f"| Evidence Recall | {baseline['average_recall']:.2%} | {optimized['average_recall']:.2%} | {(optimized['average_recall']-baseline['average_recall'])*100:+.2f}个百分点 |",
        f"| 平均输入Token/题 | {baseline['average_input_tokens']:.0f} | {optimized['average_input_tokens']:.0f} | {token_change:+.2f}% |",
        f"| 平均耗时/题 | {baseline['average_latency_sec']:.1f}s | {optimized['average_latency_sec']:.1f}s | {latency_change:+.2f}% |",
        "",
        "## 逐题配对",
        "",
        f"- 优化组胜：{comparison['wins']}题",
        f"- 持平：{comparison['ties']}题",
        f"- 优化组负：{comparison['losses']}题",
        f"- 141题总得分净变化：{comparison['net_score_change']:+d}分",
        "",
        "完整的逐题问题、Gold、前后回答、Judge理由和成本已保存到 `paired_comparison.json`，可据此补充Failure Case章节。",
        "",
        "## 结果位置",
        "",
        f"- Baseline输出：`{output_dir}`",
        f"- 优化组：`{optimized_session}`",
        "",
    ]
    (session / "BASELINE_VS_OPTIMIZED_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    core.validate_layout()
    env = core.load_experiment_env()
    full.configure_full_paths()
    rows = core.load_jsonl(core.SOURCE_JSONL)
    full.prepare_full_manifest(rows)

    session = find_or_create_session(env)
    if (session / "BASELINE_VS_OPTIMIZED_REPORT.md").exists():
        core.say(f"[已完成] Baseline及正式对照已经存在：{session}")
        return 0

    core.say(f"[Baseline141] 会话：{session.name}")
    output_dir = core.run_student(
        session,
        "baseline_no_instructions",
        [],
        env,
        rows,
        allow_ingest=False,
    )
    baseline_records = core.judge_output(output_dir, rows, env)
    optimized_session, optimized_records = find_optimized_results()
    comparison = paired_summary(baseline_records, optimized_records)
    core.save_json(session / "paired_comparison.json", comparison)
    write_report(session, comparison, optimized_session, output_dir)
    core.say("\n[完成] 141题Baseline与优化组的正式成对比较已完成。")
    core.say(f"结果：{session / 'BASELINE_VS_OPTIMIZED_REPORT.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        core.say("\n[已停止] 再次运行同一命令会复用索引、已生成答案和已完成评分。")
        raise SystemExit(130)
    except Exception as exc:
        core.say(f"\n[失败] {exc}")
        raise SystemExit(1)

