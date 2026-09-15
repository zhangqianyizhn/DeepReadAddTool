from __future__ import annotations

import json
import shutil
from collections import defaultdict
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


RUN_ROOT = RUNS_DIR / "blind_locomo_single_tool_v1"
FROZEN_ROOT = RUN_ROOT / "frozen_test"


def verify_dev_selection() -> tuple[dict[str, Any], dict[str, Any]]:
    stage = RUN_ROOT / "dev_ab"
    baseline_path = stage / "baseline_judge.json"
    repaired_path = stage / "repaired_judge.json"
    selection_path = RUN_ROOT / "DEV_SELECTION.json"
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    expected = int(manifest["question_counts"]["dev"])
    if not baseline_path.exists() or not repaired_path.exists() or not selection_path.exists():
        raise RuntimeError("Dev-guided repair and selection are incomplete; Test remains sealed.")
    baseline = load_json(baseline_path).get("results") or []
    selection = load_json(selection_path)
    candidate_file = stage / (
        "repaired_judge.json"
        if selection.get("selected") == "tool_v2_dev_repaired"
        else "candidate_judge.json"
    )
    candidate = load_json(candidate_file).get("results") or []
    if len(baseline) != expected or len(candidate) != expected:
        raise RuntimeError("Dev selection does not contain the preregistered paired cases.")
    comparison = paired(baseline, candidate)
    return comparison, selection


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def freeze(
    values: dict[str, str], test_count: int, dev_comparison: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    selected_tool = Path(selection["tool_path"])
    selected_json = Path(selection["candidate_json_path"])
    selected_tests = Path(selection["test_results_path"])
    sources = {
        "candidate_tool.py": selected_tool,
        "candidate.json": selected_json,
        "candidate_test_results.json": selected_tests,
        "canonical_units.json": CANONICAL_UNITS,
        "SPLIT_MANIFEST.json": SPLIT_DIR / "SPLIT_MANIFEST.json",
        "test.json": SPLIT_DIR / "test.json",
        "test_questions.jsonl": SPLIT_DIR / "test_questions.jsonl",
    }
    missing = [str(path) for path in sources.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing freeze input:\n" + "\n".join(missing))
    manifest_path = FROZEN_ROOT / "FREEZE_MANIFEST.json"
    if not manifest_path.exists():
        for name, source in sources.items():
            copy_once(source, FROZEN_ROOT / "snapshot" / name)
        save_json(
            manifest_path,
            {
                "status": "frozen_before_test",
                "dataset": "LocoMo conversation-disjoint test",
                "test_count": test_count,
                "selected_variant": selection["selected"],
                "dev_repair_rounds": selection["repair_rounds"],
                "dev_gate": {
                    key: dev_comparison[key]
                    for key in ("wins", "ties", "losses", "net_score")
                },
                "student_model": values["STUDENT_MODEL"],
                "judge_model": values["JUDGE_MODEL"],
                "hashes": {
                    name: sha256_file(FROZEN_ROOT / "snapshot" / name)
                    for name in sources
                },
                "rule": (
                    "Exactly one Dev-guided autonomous repair occurred before selection. "
                    "No Analyzer/Repair/dev feedback is allowed after freeze. "
                    "Test is a one-time final A/B."
                ),
            },
        )
    manifest = load_json(manifest_path)
    for name, expected in manifest["hashes"].items():
        if sha256_file(FROZEN_ROOT / "snapshot" / name) != expected:
            raise RuntimeError(f"Frozen artifact hash mismatch: {name}")
    if manifest["student_model"] != values["STUDENT_MODEL"]:
        raise RuntimeError("Student model changed after freeze.")
    if manifest["judge_model"] != values["JUDGE_MODEL"]:
        raise RuntimeError("Judge model changed after freeze.")
    return manifest


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


def relative_change(after: float, before: float) -> float:
    return after / before - 1 if before else 0.0


def category_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[str(row.get("category") or "unknown")].append(row)
    return {name: metrics(rows) for name, rows in sorted(groups.items())}


def write_report(
    path: Path,
    manifest: dict[str, Any],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    usage: dict[str, int],
) -> None:
    before, after = metrics(baseline), metrics(candidate)
    comparison = paired(baseline, candidate)
    before_categories, after_categories = category_metrics(baseline), category_metrics(candidate)
    lines = [
        "# LocoMo autonomous single tool: frozen conversation-disjoint Test",
        "",
        "## Protocol",
        "",
        "- Conversation documents were split 6/2/2 across Train/Dev/Test.",
        "- Every question searched the same complete ten-conversation corpus.",
        "- Analyzer generated one capability from Train; Repair used Dev feedback once to revise that same tool.",
        "- Dev selected v1 or v2; one tool, its usage policy, Student, Judge, inventory and Test split were then frozen.",
        f"- Selected variant: `{manifest['selected_variant']}`",
        f"- Candidate SHA-256: `{manifest['hashes']['candidate_tool.py']}`",
        "",
        "## Overall results",
        "",
        "| Arm | Accuracy | Mean score | Input tokens/q | Output tokens/q | Latency/q | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {before['accuracy']:.2%} | {before['average_score']:.3f} | {before['average_input_tokens']:.0f} | {before['average_output_tokens']:.0f} | {before['average_latency_sec']:.1f}s | {before['average_recall']:.2%} |",
        f"| Frozen autonomous tool | {after['accuracy']:.2%} | {after['average_score']:.3f} | {after['average_input_tokens']:.0f} | {after['average_output_tokens']:.0f} | {after['average_latency_sec']:.1f}s | {after['average_recall']:.2%} |",
        "",
        f"Paired: **{comparison['wins']} wins / {comparison['ties']} ties / {comparison['losses']} losses**, net **{comparison['net_score']:+d}**.",
        f"Tool use: **{usage['calls']} calls across {usage['questions']}/{len(candidate)} questions**.",
        f"Accuracy change: **{after['accuracy'] - before['accuracy']:+.2%}**.",
        f"Input-token change: **{relative_change(after['average_input_tokens'], before['average_input_tokens']):+.2%}**.",
        f"Latency change: **{relative_change(after['average_latency_sec'], before['average_latency_sec']):+.2%}**.",
        "",
        "## Results by official LocoMo category",
        "",
        "| Category | Questions | Baseline | Tool | Change |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, values in before_categories.items():
        newer = after_categories[category]
        lines.append(
            f"| {category} | {int(values['count'])} | {values['accuracy']:.2%} | "
            f"{newer['accuracy']:.2%} | {newer['accuracy'] - values['accuracy']:+.2%} |"
        )
    lines += [
        "",
        "## Per-question changes",
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
    lines += [
        "",
        "## Interpretation rule",
        "",
        "This frozen Test cannot be used to repair this candidate. Any later modification requires a new held-out split or dataset.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    require_inputs()
    split_manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    test_count = int(split_manifest["question_counts"]["test"])
    dev_comparison, selection = verify_dev_selection()
    values = load_env()
    manifest = freeze(values, test_count, dev_comparison, selection)
    snapshot = FROZEN_ROOT / "snapshot"
    tool_path = snapshot / "candidate_tool.py"
    candidate_json = load_json(snapshot / "candidate.json")
    validate_candidate(tool_path)
    tests = run_candidate_tests(load_candidate_module(tool_path), candidate_json)
    if len(tests) < 4:
        raise RuntimeError("Frozen candidate did not replay all self-tests.")
    print(
        f"[FROZEN] candidate={manifest['hashes']['candidate_tool.py'][:16]}...; "
        f"test={test_count}; Analyzer/Repair=disabled."
    )
    baseline_output = run_arm(
        "baseline", FROZEN_ROOT, snapshot / "test.json", test_count, values
    )
    candidate_output = run_arm(
        "generated_tool",
        FROZEN_ROOT,
        snapshot / "test.json",
        test_count,
        values,
        candidate_enabled=True,
        candidate_path=tool_path,
        inventory_path=snapshot / "canonical_units.json",
        instructions=candidate_policy(candidate_json),
    )
    rows = load_jsonl(snapshot / "test_questions.jsonl")
    baseline = judge(
        "locomo_test_baseline",
        rows,
        answer_map(baseline_output),
        FROZEN_ROOT / "baseline_judge.json",
        values,
    )
    candidate = judge(
        "locomo_test_candidate",
        rows,
        answer_map(candidate_output),
        FROZEN_ROOT / "candidate_judge.json",
        values,
    )
    usage = tool_usage(candidate_output / "deepread_run.log")
    report = FROZEN_ROOT / "FROZEN_TEST_REPORT.md"
    write_report(report, manifest, baseline, candidate, usage)
    comparison = paired(baseline, candidate)
    print(
        f"[TEST FINAL] {comparison['wins']} wins/{comparison['ties']} ties/"
        f"{comparison['losses']} losses; net={comparison['net_score']:+d}; "
        f"tool_calls={usage['calls']} across {usage['questions']}/{test_count}."
    )
    print(f"[REPORT] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
