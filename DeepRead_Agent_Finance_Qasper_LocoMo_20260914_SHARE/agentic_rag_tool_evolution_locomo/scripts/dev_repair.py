from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import train_generate as train_core
from common import (
    CANONICAL_UNITS,
    RUNS_DIR,
    SPLIT_DIR,
    answer_map,
    candidate_policy,
    judge,
    legacy,
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
    say,
    validate_candidate,
)


RUN_ROOT = RUNS_DIR / "blind_locomo_single_tool_v1"

DEV_REPAIR_SYSTEM = """You are the autonomous Repair Agent in a single-tool LocoMo RAG experiment.
The Analyzer selected one capability from Train and a first tool implementation was evaluated on Dev. You receive
the original Train analysis, the first tool/spec/policy, and compact paired Dev evidence: gold answers, baseline and
tool answers, judge scores, and both retrieval trajectories.

Repair the SAME capability once. Diagnose whether errors come from extraction/ranking logic, the call policy, or
unsupported scope. Do not add a second tool, memorize cases, or encode benchmark question IDs, conversation IDs,
person names, gold answers, or fixed facts. Generalize from failure mechanisms such as temporal order, speaker/entity
resolution, session boundaries, lexical mismatch, and evidence sufficiency. A conservative fallback is allowed.

Runtime contract:
- Define exactly one public function: run(question: str, corpus: list[dict], top_k: int = 5) -> dict.
- Corpus items expose doc_id, source_name, title, sections and pages. Page units expose session_index, date_time,
  speaker, dia_id, section_name and text.
- Return JSON-serializable data with a bounded `results` list.
- Allowed imports: re, math, json, collections, typing, dataclasses.
- No file/network/process/environment access, dynamic execution, or third-party packages.

Return one JSON object with keys:
- repair_analysis: {what_worked, failure_mechanisms, scope_boundary}
- changes: array of concrete general changes
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete replacement Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: at least 4 generic synthetic tests with question, corpus, top_k, expected_top_doc_id and optional
  expected_top_node_id
- prediction: {expected_quality_effect, expected_cost_effect, falsification_test}
- novelty_claim: restrained wording
"""

SELF_REPAIR_SYSTEM = """Your repaired single tool failed an automated safety or synthetic-test contract.
Fix the general implementation from machine feedback. Keep the same single capability and do not weaken or
special-case the frozen tests. Do not encode any benchmark identity, name, answer, or fact. Return the complete
candidate JSON with code, tool_spec, usage_policy, tests, repair_analysis, changes, prediction and novelty_claim."""


def compact(text: Any, limit: int = 900) -> str:
    return train_core.clip(text, limit)


def locate_log(stage: Path, label: str) -> Path:
    candidates = sorted(
        (stage / label).glob("output*/deepread_run.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"Missing Dev trajectory log for {label}.")
    return candidates[0]


def feedback_packet() -> dict[str, Any]:
    stage = RUN_ROOT / "dev_ab"
    rows = load_jsonl(SPLIT_DIR / "dev_questions.jsonl")
    baseline = load_json(stage / "baseline_judge.json").get("results") or []
    candidate = load_json(stage / "candidate_judge.json").get("results") or []
    before = {str(row["case_id"]): row for row in baseline}
    after = {str(row["case_id"]): row for row in candidate}
    row_by_id = {str(row["question_id"]): row for row in rows}

    changes = []
    unchanged_failures = []
    for case_id, old in before.items():
        new = after[case_id]
        item = (new["score"] - old["score"], case_id)
        if item[0] != 0:
            changes.append(item)
        elif old["score"] <= 2:
            unchanged_failures.append(item)
    changes.sort(key=lambda item: (-abs(item[0]), item[0], item[1]))
    unchanged_failures.sort(key=lambda item: (before[item[1]]["score"], item[1]))
    selected_ids = [case_id for _, case_id in (changes + unchanged_failures)[:18]]
    if not selected_ids:
        selected_ids = [str(row["case_id"]) for row in baseline[:8]]

    wanted = {
        train_core.qid(row_by_id[case_id]["question"])
        for case_id in selected_ids
    }
    baseline_traces = train_core.trajectories(locate_log(stage, "baseline"), wanted)
    candidate_traces = train_core.trajectories(locate_log(stage, "generated_tool"), wanted)
    cases = []
    for case_id in selected_ids:
        source = row_by_id[case_id]
        old, new = before[case_id], after[case_id]
        trace_id = train_core.qid(source["question"])
        cases.append(
            {
                "case_id_hash": train_core.qid(case_id),
                "category": source.get("category"),
                "question": source["question"],
                "gold_answers": source["gold_answers"],
                "baseline": {
                    "answer": compact(old.get("student_answer"), 1000),
                    "score": old["score"],
                    "judge_reasoning": compact(old.get("judge_reasoning"), 500),
                    "trajectory": baseline_traces.get(trace_id, [])[:24],
                },
                "tool_v1": {
                    "answer": compact(new.get("student_answer"), 1000),
                    "score": new["score"],
                    "delta": new["score"] - old["score"],
                    "judge_reasoning": compact(new.get("judge_reasoning"), 500),
                    "trajectory": candidate_traces.get(trace_id, [])[:24],
                },
            }
        )
    return {
        "protocol": {
            "source": "Dev only",
            "test_access": False,
            "human_failure_labels": False,
            "repair_rounds": 1,
            "same_capability_only": True,
        },
        "aggregate_v1": {
            "paired": {
                key: paired(baseline, candidate)[key]
                for key in ("wins", "ties", "losses", "net_score")
            },
            "baseline": metrics(baseline),
            "tool_v1": metrics(candidate),
        },
        "cases": cases,
    }


def normalize(response: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    return train_core.normalize_repair(response, previous)


def generate_repaired(values: dict[str, str], packet: dict[str, Any]) -> tuple[Path, Path]:
    repair_dir = RUN_ROOT / "dev_repair"
    repair_dir.mkdir(parents=True, exist_ok=True)
    packet_path = repair_dir / "dev_feedback_packet.json"
    save_json(packet_path, packet)
    previous = load_json(RUN_ROOT / "candidate.json")
    original_tests = load_json(RUN_ROOT / "candidate_frozen_tests.json")
    response_path = repair_dir / "candidate.json"
    completed_tests_path = repair_dir / "candidate_test_results.json"
    proposal_paths = sorted(
        repair_dir.glob("proposal_attempt*.json"),
        key=lambda path: int(path.stem.replace("proposal_attempt", "")),
    )
    if completed_tests_path.exists() and response_path.exists():
        candidate = load_json(response_path)
        say("[REUSE] Validated Dev-repaired candidate exists; replaying its contracts.")
        resume_attempt = len(proposal_paths) or 1
    elif proposal_paths:
        latest = proposal_paths[-1]
        candidate = load_json(latest)
        resume_attempt = int(latest.stem.replace("proposal_attempt", ""))
        say(f"[RESUME] Replaying the latest AI-generated repair: attempt {resume_attempt}.")
    elif response_path.exists():
        candidate = load_json(response_path)
        resume_attempt = 1
        say("[RESUME] Replaying the first Dev-repair proposal.")
    else:
        payload = {
            "train_analysis": load_json(RUN_ROOT / "analysis.json"),
            "tool_v1": previous,
            "dev_feedback": packet,
        }
        say("[Repair Agent] Reading paired Dev feedback and repairing the same single capability once.")
        candidate = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": DEV_REPAIR_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=12000,
        )
        save_json(response_path, candidate)
        resume_attempt = 1

    repair_tests_path = repair_dir / "repair_generated_tests.json"
    if repair_tests_path.exists():
        repair_tests = load_json(repair_tests_path)
    else:
        repair_tests = candidate.get("tests") or []
        save_json(repair_tests_path, repair_tests)
    if len(repair_tests) < 4:
        raise RuntimeError("Dev Repair generated fewer than four generic tests.")
    frozen_tests = original_tests + repair_tests
    tool_path = repair_dir / "candidate_tool.py"
    # Five total proposals are allowed. A resumed run starts by validating the
    # latest saved proposal instead of silently reverting to the first response.
    for attempt in range(resume_attempt, 6):
        candidate["tests"] = frozen_tests
        save_json(repair_dir / f"proposal_attempt{attempt}.json", candidate)
        tool_path.write_text(
            train_core.strip_code_fence(str(candidate.get("code") or "")) + "\n",
            encoding="utf-8",
        )
        error: str | None = None
        tests: list[dict[str, Any]] = []
        try:
            validate_candidate(tool_path)
            tests = run_candidate_tests(load_candidate_module(tool_path), candidate, strict=False)
            if not tests or not all(row["passed"] for row in tests):
                error = f"Synthetic contract failures: {tests}"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        feedback = {"attempt": attempt, "error": error, "test_results": tests}
        save_json(repair_dir / f"contract_feedback_attempt{attempt}.json", feedback)
        if error is None:
            save_json(response_path, candidate)
            save_json(repair_dir / "candidate_test_results.json", tests)
            return tool_path, response_path
        if attempt == 5:
            raise RuntimeError("Dev-repaired candidate failed autonomous contracts: " + error)
        say(f"[SELF-REPAIR] repaired tool attempt {attempt} failed; fixing from machine feedback.")
        response = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": SELF_REPAIR_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"candidate": candidate, "frozen_tests": frozen_tests, "machine_feedback": feedback},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
            max_tokens=12000,
        )
        save_json(repair_dir / f"self_repair_response_attempt{attempt}.json", response)
        candidate = normalize(response, candidate)
    raise AssertionError("unreachable")


def selection_key(comparison: dict[str, Any], records: list[dict[str, Any]]) -> tuple:
    severe = sum(row["delta"] <= -3 for row in comparison["details"])
    mean_tokens = metrics(records)["average_input_tokens"]
    return (
        comparison["net_score"],
        -severe,
        -comparison["losses"],
        -mean_tokens,
    )


def write_report(
    path: Path,
    baseline: list[dict[str, Any]],
    v1: list[dict[str, Any]],
    v2: list[dict[str, Any]],
    selected: str,
) -> None:
    rows = []
    for label, records in (("tool_v1_train_only", v1), ("tool_v2_dev_repaired", v2)):
        result = paired(baseline, records)
        value = metrics(records)
        rows.append(
            f"| {label} | {value['accuracy']:.2%} | {result['wins']} | {result['ties']} | "
            f"{result['losses']} | {result['net_score']:+d} | {value['average_input_tokens']:.0f} |"
        )
    base = metrics(baseline)
    lines = [
        "# LocoMo single-tool Dev repair and selection",
        "",
        "- Tool v1 was generated from Train only.",
        "- The Repair Agent then received paired Dev answers, scores and trajectories exactly once.",
        "- v2 must preserve the same selected capability; this is iterative repair, not a second competing tool.",
        "- Dev is therefore development data and may be overfit. Test was not read and is the final evidence.",
        "",
        "| Variant | Accuracy | Wins | Ties | Losses | Net | Input tokens/q |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| baseline | {base['accuracy']:.2%} | - | - | - | - | {base['average_input_tokens']:.0f} |",
        *rows,
        "",
        f"Selected and frozen for Test: **{selected}**.",
        "Selection order: higher Dev net score, fewer severe regressions, fewer losses, then lower input tokens.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    require_inputs()
    stage = RUN_ROOT / "dev_ab"
    required = [stage / "baseline_judge.json", stage / "candidate_judge.json"]
    if any(not path.exists() for path in required):
        raise RuntimeError("Run the initial Dev A/B before Dev-guided repair.")
    values = load_env()
    packet = feedback_packet()
    save_json(RUN_ROOT / "dev_repair" / "dev_feedback_packet.json", packet)
    tool_path, json_path = generate_repaired(values, packet)
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    dev_count = int(manifest["question_counts"]["dev"])
    candidate = load_json(json_path)
    repaired_output = run_arm(
        "repaired_tool",
        stage,
        SPLIT_DIR / "dev.json",
        dev_count,
        values,
        candidate_enabled=True,
        candidate_path=tool_path,
        inventory_path=CANONICAL_UNITS,
        instructions=candidate_policy(candidate),
    )
    rows = load_jsonl(SPLIT_DIR / "dev_questions.jsonl")
    repaired = judge(
        "locomo_dev_repaired",
        rows,
        answer_map(repaired_output),
        stage / "repaired_judge.json",
        values,
    )
    baseline = load_json(stage / "baseline_judge.json").get("results") or []
    v1 = load_json(stage / "candidate_judge.json").get("results") or []
    v1_pair, v2_pair = paired(baseline, v1), paired(baseline, repaired)
    selected = "tool_v2_dev_repaired" if selection_key(v2_pair, repaired) > selection_key(v1_pair, v1) else "tool_v1_train_only"
    if selected == "tool_v2_dev_repaired":
        selected_tool, selected_json = tool_path, json_path
        selected_tests = RUN_ROOT / "dev_repair" / "candidate_test_results.json"
    else:
        selected_tool, selected_json = RUN_ROOT / "candidate_tool.py", RUN_ROOT / "candidate.json"
        selected_tests = RUN_ROOT / "candidate_test_results.json"
    selection = {
        "selected": selected,
        "tool_path": str(selected_tool),
        "candidate_json_path": str(selected_json),
        "test_results_path": str(selected_tests),
        "test_access": False,
        "repair_rounds": 1,
        "v1": {key: v1_pair[key] for key in ("wins", "ties", "losses", "net_score")},
        "v2": {key: v2_pair[key] for key in ("wins", "ties", "losses", "net_score")},
    }
    save_json(RUN_ROOT / "DEV_SELECTION.json", selection)
    report = stage / "DEV_REPAIR_SELECTION_REPORT.md"
    write_report(report, baseline, v1, repaired, selected)
    print(
        f"[DEV REPAIR FINAL] selected={selected}; "
        f"v1_net={v1_pair['net_score']:+d}; v2_net={v2_pair['net_score']:+d}; report={report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
