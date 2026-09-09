from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
SCRIPT_DIR = HERE.parent
sys.path.insert(0, str(SCRIPT_DIR))
import dev_ab as core  # noqa: E402
import dataset_profiles as profiles  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def freeze_candidate(
    repair_dir: Path, run_root: Path, env: dict[str, str], profile: "profiles.DatasetProfile"
) -> tuple[Path, dict[str, Any]]:
    source_tool = repair_dir / "candidate_tool.py"
    source_json = repair_dir / "candidate.json"
    frozen_tool = run_root / "frozen_candidate_tool.py"
    frozen_json = run_root / "frozen_candidate.json"
    manifest_path = run_root / "FROZEN_MANIFEST.json"
    expected = {
        "protocol": f"held_out_test{profile.test_count}_ab_v1",
        "dataset": profile.name,
        "source_repair_dir": str(repair_dir),
        "source_candidate_tool_sha256": sha256_file(source_tool),
        "source_candidate_json_sha256": sha256_file(source_json),
        "test_split_sha256": sha256_file(profile.harness_file("test")),
        "test_count": profile.test_count,
        "student_model": env["STUDENT_MODEL"],
        "student_base_url": env["STUDENT_BASE_URL"],
        "judge_model": env["JUDGE_MODEL"],
        "judge_base_url": env["JUDGE_BASE_URL"],
        "old_title_tool_enabled": False,
        "baseline_generated_tool_enabled": False,
        "candidate_generated_tool_enabled": True,
        "max_rounds": 50,
        "retrieval_topk": 1,
        "agent_topk_max": 1,
        "session_pagination": False,
        "test_feedback_may_repair_candidate": False,
    }
    if manifest_path.exists():
        frozen = core.load_json(manifest_path)
        for key, value in expected.items():
            if frozen.get(key) != value:
                raise RuntimeError(
                    f"冻结清单发生变化，禁止继续test：{key}: "
                    f"frozen={frozen.get(key)!r}, current={value!r}"
                )
        if not frozen_tool.exists() or not frozen_json.exists():
            raise RuntimeError("冻结清单存在，但冻结候选文件缺失。")
        if sha256_file(frozen_tool) != frozen["frozen_candidate_tool_sha256"]:
            raise RuntimeError("冻结候选代码已改变，禁止继续test。")
        if sha256_file(frozen_json) != frozen["frozen_candidate_json_sha256"]:
            raise RuntimeError("冻结候选策略已改变，禁止继续test。")
        say("[冻结复核] 候选、test划分和模型配置哈希未变化。")
        return frozen_tool, frozen

    frozen_tool.write_bytes(source_tool.read_bytes())
    frozen_json.write_bytes(source_json.read_bytes())
    manifest = dict(expected)
    manifest.update(
        {
            "frozen_at": datetime.now().isoformat(timespec="seconds"),
            "frozen_candidate_tool_sha256": sha256_file(frozen_tool),
            "frozen_candidate_json_sha256": sha256_file(frozen_json),
        }
    )
    core.save_json(manifest_path, manifest)
    say(f"[已冻结] {manifest_path}")
    return frozen_tool, manifest


def tool_counts(output: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    log_path = output / "deepread_run.log"
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "tool_call":
                continue
            name = str(event.get("tool") or "unknown")
            counts[name] = counts.get(name, 0) + 1
    return counts


def write_test_report(
    path: Path,
    manifest: dict[str, Any],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    baseline_output: Path,
    candidate_output: Path,
    profile: "profiles.DatasetProfile",
) -> None:
    before = core.metrics(baseline)
    after = core.metrics(candidate)
    paired = core.paired(baseline, candidate)
    token_change = (after["average_input_tokens"] / before["average_input_tokens"] - 1) if before["average_input_tokens"] else 0
    latency_change = (after["average_latency_sec"] / before["average_latency_sec"] - 1) if before["average_latency_sec"] else 0
    score_change = after["accuracy"] - before["accuracy"]
    lines = [
        f"# AI自主生成并修复工具：冻结Test {profile.test_count}最终A/B（{profile.display_name}）",
        "",
        "## 实验纪律",
        "",
        "- 工具与策略在查看test结果前冻结，并由SHA-256清单校验。",
        f"- test共{profile.test_count}题；Repair Agent从未读取test反馈。",
        "- Baseline关闭旧标题工具；Candidate只开启冻结的AI生成工具与AI生成策略。",
        "- 两组Student、Judge、索引、轮数、top-k和其他检索工具完全一致。",
        "- 本结果只用于最终泛化评估，禁止再用test反馈修改候选。",
        "",
        "## 冻结信息",
        "",
        f"- Student：`{manifest['student_model']}`",
        f"- Judge：`{manifest['judge_model']}`",
        f"- 候选代码SHA-256：`{manifest['frozen_candidate_tool_sha256']}`",
        f"- test划分SHA-256：`{manifest['test_split_sha256']}`",
        "",
        "## 总体结果",
        "",
        "| 方案 | 准确率 | 平均分(0-4) | 输入Token/题 | 输出Token/题 | 耗时/题 | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| 冻结AI工具 | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"- 准确率变化：**{score_change:+.2%}**",
        f"- 成对结果：**{paired['wins']}胜 / {paired['ties']}平 / {paired['losses']}负**，净分 **{paired['net_score']:+d}**",
        f"- 平均输入Token变化：**{token_change:+.2%}**",
        f"- 平均耗时变化：**{latency_change:+.2%}**",
        f"- Baseline工具调用：`{json.dumps(tool_counts(baseline_output), ensure_ascii=False)}`",
        f"- Candidate工具调用：`{json.dumps(tool_counts(candidate_output), ensure_ascii=False)}`",
        "",
        "## 逐题变化",
        "",
        "| case_id | Baseline | Candidate | 变化 | 问题 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in sorted(paired["details"], key=lambda item: item["delta"], reverse=True):
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {row['case_id']} | {row['baseline_score']} | {row['candidate_score']} | {row['delta']:+d} | {question} |"
        )
    lines += [
        "",
        "## 最终解释约束",
        "",
        "该test结果只能用于报告泛化能力，不能再回流到Repair Agent。如果需要继续研发，必须换用新的开发集或新的数据集。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="financebench", choices=sorted(profiles.PROFILES))
    parser.add_argument("--workers", type=int, default=None,
                        help="答题线程数（默认：financebench=1 对齐历史，其余=4）")
    args = parser.parse_args()
    profile = profiles.get_profile(args.dataset)
    workers = args.workers or profiles.DEFAULT_WORKERS[profile.name]

    blind_run = core.latest_blind_run(profile)
    repair_dir = blind_run / "repair_round2"
    test_harness_file = profile.harness_file("test")
    required = [repair_dir / "candidate_tool.py", repair_dir / "candidate.json", test_harness_file]
    missing = [str(item) for item in required if not item.exists()]
    if missing:
        raise FileNotFoundError("冻结test缺少输入：\n" + "\n".join(missing))
    test_rows = profile.load_split_rows("test")
    if len(test_rows) != profile.test_count:
        raise RuntimeError(f"test题数必须为{profile.test_count}，实际为{len(test_rows)}。")

    env = core.legacy.load_experiment_env()
    run_root = repair_dir / "frozen_test61"
    run_root.mkdir(parents=True, exist_ok=True)
    frozen_tool, manifest = freeze_candidate(repair_dir, run_root, env, profile)
    frozen_candidate = core.load_json(run_root / "frozen_candidate.json")
    core.validate_candidate(frozen_tool)
    tests = core.run_generated_tests(core.load_candidate_module(frozen_tool), frozen_candidate)
    say(f"[冻结候选复核] 自生成测试 {len(tests)}/{len(tests)} 通过。")
    say(
        f"[最终Test] {profile.display_name} {profile.test_count}题严格A/B；Student={env['STUDENT_MODEL']}；"
        f"Judge={env['JUDGE_MODEL']}；test结果禁止回流修复。"
    )

    baseline_output = core.run_arm(
        "baseline",
        run_root,
        test_harness_file,
        profile.test_count,
        frozen_tool,
        False,
        [],
        env,
        profile,
        workers,
    )
    candidate_output = core.run_arm(
        "frozen_generated_tool",
        run_root,
        test_harness_file,
        profile.test_count,
        frozen_tool,
        True,
        core.generated_policy(frozen_candidate),
        env,
        profile,
        workers,
    )
    baseline = core.judge(
        "test_baseline",
        test_rows,
        core.answer_map(baseline_output),
        run_root / "baseline_judged.json",
        env,
        profile.judge_system,
    )
    candidate = core.judge(
        "test_frozen_generated_tool",
        test_rows,
        core.answer_map(candidate_output),
        run_root / "frozen_generated_tool_judged.json",
        env,
        profile.judge_system,
    )
    report = run_root / "FROZEN_TEST61_REPORT.md"
    write_test_report(report, manifest, baseline, candidate, baseline_output, candidate_output, profile)
    paired = core.paired(baseline, candidate)
    before = core.metrics(baseline)
    after = core.metrics(candidate)
    say(
        f"[最终完成] Test61：{paired['wins']}胜/{paired['ties']}平/"
        f"{paired['losses']}负，净分={paired['net_score']:+d}；"
        f"准确率 {before['accuracy']:.2%} -> {after['accuracy']:.2%}"
    )
    say(f"[最终报告] {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 冻结清单、完整阶段与Judge断点均保留；重新运行同一命令继续。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
