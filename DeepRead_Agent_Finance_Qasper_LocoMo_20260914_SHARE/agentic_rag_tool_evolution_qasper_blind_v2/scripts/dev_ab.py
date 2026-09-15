from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import (
    CANONICAL_UNITS,
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


RUN_ROOT = RUNS_DIR / "blind_v2_seed20260823"
DEV_COUNT = 40


def generated_tool_usage(log_path: Path) -> dict[str, int]:
    calls = 0
    query_ids: set[str] = set()
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "tool_call" and event.get("tool") == "generated_corpus_search":
                calls += 1
                query_ids.add(str(event.get("query_id") or ""))
    return {"calls": calls, "questions": len(query_ids)}


def write_report(
    path: Path,
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    usage: dict[str, int],
) -> None:
    before = metrics(baseline)
    after = metrics(candidate)
    comparison = paired(baseline, candidate)
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    gate = comparison["net_score"] > 0 and severe == 0
    lines = [
        "# Qasper canonical-text autonomous single tool: Dev 40 A/B",
        "",
        "## Protocol",
        "",
        "- New official Qasper train-v0.3 papers; old experiment artifacts were not prompt inputs.",
        "- Paper-disjoint 100/40/120 split.",
        "- Canonical Qasper JSON only; no PDF or PDF extraction.",
        "- Analyzer and Repair saw train trajectories only. Dev is evaluation-only and is not used for repair.",
        "- The model autonomously selected, implemented, tested, and repaired exactly one tool.",
        f"- Frozen synthetic tests: {len(tests)}/{len(tests)} passed.",
        "",
        "## Results",
        "",
        "| Arm | Normalized accuracy | Mean score | Input tokens/q | Output tokens/q | Latency/q | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| Autonomous tool | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"Paired: **{comparison['wins']} wins / {comparison['ties']} ties / {comparison['losses']} losses**, net **{comparison['net_score']:+d}**.",
        f"Generated-tool use: **{usage['calls']} calls across {usage['questions']}/{DEV_COUNT} questions**.",
        f"Preregistered dev gate (net>0 and no -3/-4 case): **{'PASS' if gate else 'FAIL'}**.",
        "",
        "## Per-question changes",
        "",
        "| question_id | paper_id | Baseline | Tool | Delta | Question |",
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
        "## Decision",
        "",
        "A passing dev gate permits artifact freezing and one sealed test120 run. A failed gate ends this replication; dev feedback must not repair the tool.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    require_inputs()
    candidate_path = RUN_ROOT / "candidate_tool.py"
    candidate_json_path = RUN_ROOT / "candidate.json"
    if not candidate_path.exists() or not candidate_json_path.exists():
        raise RuntimeError("Train-only autonomous generation is incomplete.")
    candidate_json = load_json(candidate_json_path)
    validate_candidate(candidate_path)
    tests = run_candidate_tests(load_candidate_module(candidate_path), candidate_json)
    values = load_env()
    stage = RUN_ROOT / "dev_ab"
    baseline_output = run_arm(
        "baseline", stage, SPLIT_DIR / "dev.json", DEV_COUNT, values
    )
    candidate_output = run_arm(
        "generated_tool",
        stage,
        SPLIT_DIR / "dev.json",
        DEV_COUNT,
        values,
        candidate_enabled=True,
        candidate_path=candidate_path,
        inventory_path=CANONICAL_UNITS,
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(SPLIT_DIR / "dev_questions.jsonl")
    baseline = judge(
        "blind_v2_dev_baseline",
        rows,
        answer_map(baseline_output),
        stage / "baseline_judge.json",
        values,
    )
    candidate = judge(
        "blind_v2_dev_candidate",
        rows,
        answer_map(candidate_output),
        stage / "candidate_judge.json",
        values,
    )
    usage = generated_tool_usage(candidate_output / "deepread_run.log")
    report = stage / "DEV40_REPORT.md"
    write_report(report, baseline, candidate, tests, usage)
    comparison = paired(baseline, candidate)
    print(
        f"[DEV FINAL] {comparison['wins']} wins/{comparison['ties']} ties/"
        f"{comparison['losses']} losses; net={comparison['net_score']:+d}; "
        f"tool_calls={usage['calls']} across {usage['questions']}/{DEV_COUNT}."
    )
    print(f"[REPORT] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
