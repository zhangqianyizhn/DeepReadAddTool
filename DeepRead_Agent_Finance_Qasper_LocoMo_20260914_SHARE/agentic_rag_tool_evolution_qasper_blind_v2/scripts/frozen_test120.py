from __future__ import annotations

import json
import shutil
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
    save_json,
    sha256_file,
    validate_candidate,
)


RUN_ROOT = RUNS_DIR / "blind_v2_seed20260823"
DEV_ROOT = RUN_ROOT / "dev_ab"
FROZEN_ROOT = RUN_ROOT / "frozen_test120"
DEV_COUNT = 40
TEST_COUNT = 120


def verify_dev_gate() -> dict[str, Any]:
    baseline_path = DEV_ROOT / "baseline_judge.json"
    candidate_path = DEV_ROOT / "candidate_judge.json"
    if not baseline_path.exists() or not candidate_path.exists():
        raise RuntimeError("Dev A/B is incomplete; frozen test is not allowed.")
    baseline = load_json(baseline_path).get("results") or []
    candidate = load_json(candidate_path).get("results") or []
    if len(baseline) != DEV_COUNT or len(candidate) != DEV_COUNT:
        raise RuntimeError(f"Dev gate requires exactly {DEV_COUNT} paired cases.")
    comparison = paired(baseline, candidate)
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    if comparison["net_score"] <= 0 or severe:
        raise RuntimeError("The preregistered dev gate did not pass; test remains sealed.")
    return comparison


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def freeze(values: dict[str, str], dev_comparison: dict[str, Any]) -> dict[str, Any]:
    source_tool = RUN_ROOT / "candidate_tool.py"
    source_candidate = RUN_ROOT / "candidate.json"
    source_tests = RUN_ROOT / "candidate_test_results.json"
    required = [
        source_tool,
        source_candidate,
        source_tests,
        CANONICAL_UNITS,
        SPLIT_DIR / "SPLIT_MANIFEST.json",
        SPLIT_DIR / "test.json",
        SPLIT_DIR / "test_questions.jsonl",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing freeze input:\n" + "\n".join(missing))

    FROZEN_ROOT.mkdir(parents=True, exist_ok=True)
    snapshots = {
        "candidate_tool.py": source_tool,
        "candidate.json": source_candidate,
        "candidate_test_results.json": source_tests,
        "canonical_units.json": CANONICAL_UNITS,
        "SPLIT_MANIFEST.json": SPLIT_DIR / "SPLIT_MANIFEST.json",
        "test.json": SPLIT_DIR / "test.json",
        "test_questions.jsonl": SPLIT_DIR / "test_questions.jsonl",
    }
    manifest_path = FROZEN_ROOT / "FREEZE_MANIFEST.json"
    if not manifest_path.exists():
        for name, source in snapshots.items():
            copy_once(source, FROZEN_ROOT / "snapshot" / name)
        manifest = {
            "status": "frozen_before_test",
            "dataset": "Qasper canonical-text paper-disjoint test120",
            "dev_gate": {
                "wins": dev_comparison["wins"],
                "ties": dev_comparison["ties"],
                "losses": dev_comparison["losses"],
                "net_score": dev_comparison["net_score"],
            },
            "student_model": values["STUDENT_MODEL"],
            "judge_model": values["JUDGE_MODEL"],
            "hashes": {
                name: sha256_file(FROZEN_ROOT / "snapshot" / name)
                for name in snapshots
            },
            "rule": (
                "No Analyzer/Repair call and no candidate or policy mutation after "
                "this manifest is written. Test results are final evaluation only."
            ),
        }
        save_json(manifest_path, manifest)

    manifest = load_json(manifest_path)
    for name, expected in manifest["hashes"].items():
        actual = sha256_file(FROZEN_ROOT / "snapshot" / name)
        if actual != expected:
            raise RuntimeError(f"Frozen artifact hash mismatch: {name}")
    if manifest.get("student_model") != values["STUDENT_MODEL"]:
        raise RuntimeError("Student model changed after freeze.")
    if manifest.get("judge_model") != values["JUDGE_MODEL"]:
        raise RuntimeError("Judge model changed after freeze.")
    return manifest


def generated_tool_usage(log_path: Path) -> dict[str, int]:
    calls = 0
    query_ids: set[str] = set()
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                event.get("event") == "tool_call"
                and event.get("tool") == "generated_corpus_search"
            ):
                calls += 1
                query_ids.add(str(event.get("query_id") or ""))
    return {"calls": calls, "questions": len(query_ids)}


def relative_change(after: float, before: float) -> float:
    return (after / before - 1) if before else 0.0


def write_report(
    path: Path,
    manifest: dict[str, Any],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    usage: dict[str, int],
) -> None:
    before = metrics(baseline)
    after = metrics(candidate)
    comparison = paired(baseline, candidate)
    lines = [
        "# Qasper canonical-text autonomous single tool: frozen Test 120",
        "",
        "## Protocol",
        "",
        "- Candidate code, policy, canonical inventory, test split, Student, and Judge were frozen after dev passed.",
        "- Test papers are disjoint from train and dev papers.",
        "- No Analyzer or Repair Agent is called in this stage.",
        "- Test is evaluated once; results are not development feedback.",
        f"- Candidate SHA-256: `{manifest['hashes']['candidate_tool.py']}`",
        "",
        "## Results",
        "",
        "| Arm | Normalized accuracy | Mean score (0-4) | Input tokens/q | Output tokens/q | Latency/q | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| Frozen autonomous tool | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"Paired: **{comparison['wins']} wins / {comparison['ties']} ties / {comparison['losses']} losses**, net score **{comparison['net_score']:+d}**.",
        f"Generated-tool use: **{usage['calls']} calls across {usage['questions']}/{TEST_COUNT} questions**.",
        f"Accuracy change: **{after['accuracy'] - before['accuracy']:+.2%}**.",
        f"Input-token change: **{relative_change(after['average_input_tokens'], before['average_input_tokens']):+.2%}**.",
        f"Output-token change: **{relative_change(after['average_output_tokens'], before['average_output_tokens']):+.2%}**.",
        f"Latency change: **{relative_change(after['average_latency_sec'], before['average_latency_sec']):+.2%}**.",
        f"Recall change: **{after['average_recall'] - before['average_recall']:+.2%}**.",
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
        "## Interpretation rule",
        "",
        "This is the final held-out result. Any future modification requires a new split or dataset; this test cannot be used to repair the candidate.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    require_inputs()
    dev_comparison = verify_dev_gate()
    values = load_env()
    manifest = freeze(values, dev_comparison)
    snapshot = FROZEN_ROOT / "snapshot"
    tool_path = snapshot / "candidate_tool.py"
    candidate_json = load_json(snapshot / "candidate.json")
    validate_candidate(tool_path)
    tests = run_candidate_tests(load_candidate_module(tool_path), candidate_json)
    expected_tests = len(candidate_json.get("tests") or [])
    if expected_tests < 3 or len(tests) != expected_tests:
        raise RuntimeError("Frozen candidate did not pass all original synthetic tests.")

    print(
        f"[Frozen] candidate={manifest['hashes']['candidate_tool.py'][:16]}...; "
        f"test={TEST_COUNT}; Analyzer/Repair=disabled."
    )
    baseline_output = run_arm(
        "baseline", FROZEN_ROOT, snapshot / "test.json", TEST_COUNT, values
    )
    candidate_output = run_arm(
        "generated_tool",
        FROZEN_ROOT,
        snapshot / "test.json",
        TEST_COUNT,
        values,
        candidate_enabled=True,
        candidate_path=tool_path,
        inventory_path=snapshot / "canonical_units.json",
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(snapshot / "test_questions.jsonl")
    if len(rows) != TEST_COUNT:
        raise RuntimeError(f"Frozen test must contain exactly {TEST_COUNT} questions.")
    baseline = judge(
        "blind_v2_test120_baseline",
        rows,
        answer_map(baseline_output),
        FROZEN_ROOT / "baseline_judge.json",
        values,
    )
    candidate = judge(
        "blind_v2_test120_candidate",
        rows,
        answer_map(candidate_output),
        FROZEN_ROOT / "candidate_judge.json",
        values,
    )
    usage = generated_tool_usage(candidate_output / "deepread_run.log")
    report = FROZEN_ROOT / "FROZEN_TEST120_REPORT.md"
    write_report(report, manifest, baseline, candidate, usage)
    comparison = paired(baseline, candidate)
    print(
        f"[TEST FINAL] {comparison['wins']} wins/{comparison['ties']} ties/"
        f"{comparison['losses']} losses; net={comparison['net_score']:+d}; "
        f"tool_calls={usage['calls']} across {usage['questions']}/{TEST_COUNT}."
    )
    print(f"[REPORT] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
