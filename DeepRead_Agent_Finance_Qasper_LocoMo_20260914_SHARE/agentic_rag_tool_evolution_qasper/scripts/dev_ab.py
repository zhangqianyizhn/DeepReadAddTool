from __future__ import annotations

from pathlib import Path

from common import (
    RUNS_DIR,
    SPLIT_DIR,
    answer_map,
    candidate_policy,
    judge,
    load_candidate_module,
    load_env,
    load_json,
    load_jsonl,
    metrics,
    paired,
    require_inputs,
    run_arm,
    run_candidate_tests,
    validate_candidate,
)


RUN_ROOT = RUNS_DIR / "blind_qasper_seed20260822"


def write_report(
    path: Path,
    baseline: list[dict],
    candidate: list[dict],
    generated_tests: list[dict],
) -> None:
    before = metrics(baseline)
    after = metrics(candidate)
    comparison = paired(baseline, candidate)
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    gate = comparison["net_score"] > 0 and severe == 0
    lines = [
        "# Qasper 单一AI生成工具：Dev 20严格A/B",
        "",
        "## 实验边界",
        "",
        "- train/dev/test按论文ID隔离为60/20/80题。",
        "- 工具只由train轨迹生成；本轮首次读取dev；test仍未读取。",
        "- Baseline和Candidate的模型、索引、top-k、轮数相同；唯一变量是AI生成工具及其AI生成策略。",
        f"- 工具自生成测试：{len(generated_tests)}/{len(generated_tests)}通过。",
        "",
        "## 结果",
        "",
        "| 方案 | 归一化准确率 | 平均分(0-4) | 输入Token/题 | 输出Token/题 | 耗时/题 | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| AI生成单工具 | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"成对结果：**{comparison['wins']}胜 / {comparison['ties']}平 / {comparison['losses']}负**，净分 **{comparison['net_score']:+d}**。",
        f"预注册Dev门槛（净分>0且无单题-3/-4退化）：**{'通过' if gate else '未通过'}**。",
        "",
        "## 逐题变化",
        "",
        "| question_id | paper_id | Baseline | Candidate | 变化 | 问题 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in sorted(comparison["details"], key=lambda item: item["delta"], reverse=True):
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {row['case_id']} | {row['paper_id']} | {row['baseline_score']} | "
            f"{row['candidate_score']} | {row['delta']:+d} | {question} |"
        )
    lines += [
        "",
        "## 下一步规则",
        "",
        "- 通过门槛：冻结工具、策略和哈希，才允许打开test 80。",
        "- 未通过门槛：最多允许用这20题dev反馈自主修复一次；test继续封存。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    require_inputs()
    candidate_path = RUN_ROOT / "candidate_tool.py"
    candidate_json_path = RUN_ROOT / "candidate.json"
    if not candidate_path.exists() or not candidate_json_path.exists():
        raise RuntimeError("尚未完成train盲生成；先运行 .\\run_train_generate.ps1")
    candidate_json = load_json(candidate_json_path)
    validate_candidate(candidate_path)
    tests = run_candidate_tests(load_candidate_module(candidate_path), candidate_json)
    values = load_env()
    stage = RUN_ROOT / "dev_ab"
    baseline_output = run_arm(
        "baseline", stage, SPLIT_DIR / "dev.json", 20, values
    )
    candidate_output = run_arm(
        "generated_tool",
        stage,
        SPLIT_DIR / "dev.json",
        20,
        values,
        candidate_enabled=True,
        candidate_path=candidate_path,
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(SPLIT_DIR / "dev_questions.jsonl")
    baseline = judge(
        "dev_baseline", rows, answer_map(baseline_output), stage / "baseline_judge.json", values
    )
    candidate = judge(
        "dev_candidate", rows, answer_map(candidate_output), stage / "candidate_judge.json", values
    )
    report = stage / "DEV_AB_REPORT.md"
    write_report(report, baseline, candidate, tests)
    comparison = paired(baseline, candidate)
    print(
        f"[完成] Qasper dev20：{comparison['wins']}胜/{comparison['ties']}平/"
        f"{comparison['losses']}负，净分={comparison['net_score']:+d}"
    )
    print(f"[报告] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
