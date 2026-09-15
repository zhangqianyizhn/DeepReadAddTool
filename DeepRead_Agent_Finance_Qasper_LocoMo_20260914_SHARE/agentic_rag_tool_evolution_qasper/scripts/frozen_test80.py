from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from common import (
    PDF_PAGES,
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


RUN_ROOT = RUNS_DIR / "blind_qasper_seed20260822"
DEV_ROOT = RUN_ROOT / "dev_ab"
FROZEN_ROOT = RUN_ROOT / "frozen_test80"


def verify_dev_gate() -> dict[str, Any]:
    baseline_path = DEV_ROOT / "baseline_judge.json"
    candidate_path = DEV_ROOT / "candidate_judge.json"
    if not baseline_path.exists() or not candidate_path.exists():
        raise RuntimeError("Dev A/B is incomplete; frozen test is not allowed.")
    baseline = load_json(baseline_path).get("results") or []
    candidate = load_json(candidate_path).get("results") or []
    if len(baseline) != 20 or len(candidate) != 20:
        raise RuntimeError("Dev gate requires exactly 20 paired cases.")
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
        PDF_PAGES,
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
        "pdf_pages.json": PDF_PAGES,
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
            "dataset": "Qasper paper-disjoint test80",
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
            "rule": "No Analyzer/Repair call and no candidate mutation after this manifest is written.",
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


def write_report(
    path: Path,
    manifest: dict[str, Any],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> None:
    before = metrics(baseline)
    after = metrics(candidate)
    comparison = paired(baseline, candidate)
    input_change = (after["average_input_tokens"] / before["average_input_tokens"] - 1) if before["average_input_tokens"] else 0
    latency_change = (after["average_latency_sec"] / before["average_latency_sec"] - 1) if before["average_latency_sec"] else 0
    lines = [
        "# Qasper AI-generated single tool: frozen Test 80",
        "",
        "## Protocol",
        "",
        "- The candidate, policy, PDF-page inventory, test split, Student, and Judge were frozen after dev passed.",
        "- Test papers are disjoint from train and dev papers.",
        "- No Analyzer or Repair Agent is called in this stage.",
        "- Test is evaluated once; results must not be used to modify the candidate.",
        f"- Candidate SHA-256: `{manifest['hashes']['candidate_tool.py']}`",
        "",
        "## Results",
        "",
        "| Arm | Normalized accuracy | Mean score (0-4) | Input tokens/q | Output tokens/q | Latency/q | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| Frozen AI tool | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"Paired: **{comparison['wins']} wins / {comparison['ties']} ties / {comparison['losses']} losses**, net score **{comparison['net_score']:+d}**.",
        f"Input-token change: **{input_change:+.2%}**; latency change: **{latency_change:+.2%}**.",
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
        "This is the final held-out result. Any future modification requires a new dataset split or a new dataset; this test cannot become development feedback.",
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
    if len(tests) != 3:
        raise RuntimeError("Frozen candidate must pass the original three tests.")

    print(
        f"[Frozen] candidate={manifest['hashes']['candidate_tool.py'][:16]}...; "
        "test=80; Analyzer/Repair=disabled."
    )
    baseline_output = run_arm(
        "baseline",
        FROZEN_ROOT,
        snapshot / "test.json",
        80,
        values,
    )
    candidate_output = run_arm(
        "generated_tool",
        FROZEN_ROOT,
        snapshot / "test.json",
        80,
        values,
        candidate_enabled=True,
        candidate_path=tool_path,
        inventory_path=snapshot / "pdf_pages.json",
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(snapshot / "test_questions.jsonl")
    baseline = judge(
        "test80_baseline",
        rows,
        answer_map(baseline_output),
        FROZEN_ROOT / "baseline_judge.json",
        values,
    )
    candidate = judge(
        "test80_candidate",
        rows,
        answer_map(candidate_output),
        FROZEN_ROOT / "candidate_judge.json",
        values,
    )
    report = FROZEN_ROOT / "FROZEN_TEST80_REPORT.md"
    write_report(report, manifest, baseline, candidate)
    comparison = paired(baseline, candidate)
    print(
        f"[FINAL] Test80: {comparison['wins']} wins/{comparison['ties']} ties/"
        f"{comparison['losses']} losses; net={comparison['net_score']:+d}"
    )
    print(f"[REPORT] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
