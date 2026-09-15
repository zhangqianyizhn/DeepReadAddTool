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


RUN_ROOT = RUNS_DIR / "blind_locomo_single_tool_v1"


def tool_usage(log_path: Path) -> dict[str, int]:
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
    usage: dict[str, int],
) -> None:
    before, after = metrics(baseline), metrics(candidate)
    comparison = paired(baseline, candidate)
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    gate = comparison["net_score"] > 0 and severe == 0
    lines = [
        "# LocoMo autonomous single tool: initial Dev A/B",
        "",
        "- Analyzer and Repair saw Train only.",
        "- This is the initial Dev measurement; its paired feedback will drive exactly one autonomous repair.",
        "- Test remains sealed.",
        "",
        "| Arm | Accuracy | Mean score | Input tokens/q | Latency/q | Recall |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| Tool | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"Paired: **{comparison['wins']}W/{comparison['ties']}T/{comparison['losses']}L**, net **{comparison['net_score']:+d}**.",
        f"Tool calls: **{usage['calls']} across {usage['questions']}/{len(candidate)} questions**.",
        f"Initial diagnostic gate (net>0 and no delta<=-3): **{'PASS' if gate else 'FAIL'}**.",
        "",
        "| case_id | conversation | Baseline | Tool | Delta | Question |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in sorted(comparison["details"], key=lambda item: item["delta"], reverse=True):
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {row['case_id']} | {row['paper_id']} | {row['baseline_score']} | "
            f"{row['candidate_score']} | {row['delta']:+d} | {question} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    require_inputs()
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    dev_count = int(manifest["question_counts"]["dev"])
    candidate_path = RUN_ROOT / "candidate_tool.py"
    candidate_json_path = RUN_ROOT / "candidate.json"
    if not candidate_path.exists() or not candidate_json_path.exists():
        raise RuntimeError("Train-only tool generation is incomplete.")
    candidate_json = load_json(candidate_json_path)
    validate_candidate(candidate_path)
    run_candidate_tests(load_candidate_module(candidate_path), candidate_json)
    values = load_env()
    stage = RUN_ROOT / "dev_ab"
    baseline_output = run_arm("baseline", stage, SPLIT_DIR / "dev.json", dev_count, values)
    candidate_output = run_arm(
        "generated_tool",
        stage,
        SPLIT_DIR / "dev.json",
        dev_count,
        values,
        candidate_enabled=True,
        candidate_path=candidate_path,
        inventory_path=CANONICAL_UNITS,
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(SPLIT_DIR / "dev_questions.jsonl")
    baseline = judge(
        "locomo_dev_baseline", rows, answer_map(baseline_output), stage / "baseline_judge.json", values
    )
    candidate = judge(
        "locomo_dev_candidate", rows, answer_map(candidate_output), stage / "candidate_judge.json", values
    )
    usage = tool_usage(candidate_output / "deepread_run.log")
    report = stage / "DEV_REPORT.md"
    write_report(report, baseline, candidate, usage)
    comparison = paired(baseline, candidate)
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    status = "PASS" if comparison["net_score"] > 0 and severe == 0 else "FAIL"
    print(
        f"[DEV FINAL] gate={status}; {comparison['wins']}W/{comparison['ties']}T/"
        f"{comparison['losses']}L; net={comparison['net_score']:+d}; report={report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
