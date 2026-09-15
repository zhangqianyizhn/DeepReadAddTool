from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import (
    CANONICAL_UNITS,
    RUNS_DIR,
    SPLIT_DIR,
    answer_map,
    judge,
    legacy,
    load_candidate_module,
    load_env,
    load_json,
    load_jsonl,
    require_inputs,
    run_arm,
    run_candidate_tests,
    run_index,
    save_json,
    say,
    validate_candidate,
)


RUN_ROOT = RUNS_DIR / "blind_v2_seed20260823"
EXPECTED = {"train": 100, "dev": 40, "test": 120}

ANALYZER_SYSTEM = """You are the Analyzer in a blind autonomous single-tool RAG experiment.
You receive only TRAIN questions, acceptable gold answers, baseline answers, automatic judge scores, and raw
baseline tool trajectories. You do not receive dev/test questions, old experiment tools or reports, or human
failure labels and diagnoses.

Infer recurring causal failure mechanisms from the supplied evidence and successful controls. Decide whether one
missing executable capability is justified. The only allowed runtime substrate is the complete question plus a
read-only corpus inventory containing document identifiers, source names, section metadata, and canonical normalized
text units from the dataset JSON. There are no PDFs. Do not give prompt-only advice, memorize examples, or assume
access to gold answers at runtime. You may return selected_capability=null if no single capability is justified.

Return one JSON object with keys:
- evidence_summary
- failure_clusters: array of {name, count_estimate, causal_chain, trajectory_evidence, repairability}
- candidate_capabilities: array of {name, problem_solved, inputs, outputs, preconditions, expected_effect, risks}
- selected_capability: the single best capability or null
- selection_reason
- falsification_test
"""

ARCHITECT_SYSTEM = """You are the Repair Agent in a blind autonomous single-tool synthesis experiment.
Implement only the Analyzer's selected capability as one safe Python tool and an explicit usage policy. Do not add
capabilities that the Analyzer did not justify.

Runtime contract:
- Define exactly one public function: run(question: str, corpus: list[dict], top_k: int = 5) -> dict.
- Each corpus item contains doc_id, source_name, sections, and pages.
- Each section contains node_id, title, paragraph_count, and token_count.
- `pages` is a legacy field name. In this experiment every item is a canonical Qasper JSON text unit with
  page_number/unit_index, section_name, and trusted read-only text. It is not a PDF page.
- Return JSON-serializable data with a `results` list. Results may contain doc_id, node_id, unit_index/page_number,
  title, score, text, and reasons. Keep returned evidence bounded.
- Allowed imports: re, math, json, collections, typing, dataclasses.
- Forbidden: file/network/process/environment access, dynamic execution, and third-party packages.
- Do not encode benchmark question IDs, gold answers, exact train paper titles, or a fixed domain entity list.
- The tool must be generic beyond the supplied examples.

Return one JSON object with keys:
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: at least 3 synthetic generic tests, each with name, question, corpus, top_k,
  expected_top_doc_id and optionally expected_top_node_id or expected_top_unit_index
- novelty_claim: restrained wording; do not claim literature novelty
"""

SELF_REPAIR_SYSTEM = """You are autonomously debugging the single safe Python tool you generated.
You receive your current complete candidate, the original frozen synthetic tests, and exact validation results.
Repair the implementation defect without weakening, deleting, replacing, or special-casing the tests. Do not add
benchmark IDs, exact paper titles, gold answers, or domain entity lists. Preserve exactly one public
run(question, corpus, top_k) function, the allowed-import list, and the no-file/network/process/environment rule.
Return the complete candidate JSON with tool_spec, code, usage_policy, tests, and novelty_claim.
"""


def clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def qid(question: str) -> str:
    return hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]


def normalize_candidate_response(
    response: dict[str, Any], previous: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(response, dict):
        return previous, "repair response is not a JSON object"
    for key in ("candidate", "repaired_candidate", "result"):
        nested = response.get(key)
        if isinstance(nested, dict) and str(nested.get("code") or "").strip():
            return nested, None
    if str(response.get("code") or "").strip():
        return response, None
    for key in ("repaired_code", "tool_code", "python_code"):
        code = response.get(key)
        if isinstance(code, str) and code.strip():
            normalized = dict(previous)
            normalized["code"] = code
            for optional in ("tool_spec", "usage_policy", "novelty_claim"):
                if response.get(optional) is not None:
                    normalized[optional] = response[optional]
            return normalized, None
    return previous, "repair response contains no complete candidate code"


def compact_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return clip(result, 700)
    compact: dict[str, Any] = {"ok": result.get("ok")}
    for key in ("query", "scope", "doc_id", "title", "error"):
        if result.get(key) is not None:
            compact[key] = clip(result[key], 250)
    if isinstance(result.get("results"), list):
        compact["results"] = []
        for row in result["results"][:3]:
            if not isinstance(row, dict):
                compact["results"].append(clip(row, 450))
                continue
            item: dict[str, Any] = {}
            for key in (
                "doc_id",
                "node_id",
                "unit_index",
                "page_number",
                "score",
                "title",
                "text",
                "source_name",
                "reasons",
            ):
                if row.get(key) is not None:
                    item[key] = clip(row[key], 350)
            if isinstance(row.get("ref"), dict):
                item["ref"] = {
                    key: row["ref"].get(key)
                    for key in ("doc_id", "node_id")
                    if row["ref"].get(key) is not None
                }
            compact["results"].append(item)
    return compact


def trajectories(log_file: Path, wanted: set[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_qid = str(event.get("query_id") or "")
            if event_qid not in wanted:
                continue
            kind = event.get("event")
            if kind == "llm_response":
                grouped[event_qid].append(
                    {
                        "round": event.get("round"),
                        "event": kind,
                        "reasoning": clip(
                            event.get("reasoning_content") or event.get("content") or "",
                            1000,
                        ),
                        "tool_calls": event.get("tool_calls") or [],
                    }
                )
            elif kind == "tool_call":
                grouped[event_qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "args": event.get("args") or {},
                    }
                )
            elif kind == "tool_result":
                grouped[event_qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "result": compact_result(event.get("result")),
                    }
                )
    return grouped


def build_packet(
    rows: list[dict[str, Any]], judged: list[dict[str, Any]], log_file: Path
) -> list[dict[str, Any]]:
    score_by_id = {str(row["case_id"]): row for row in judged}
    failures = sorted(
        [row for row in rows if score_by_id[str(row["question_id"])]["score"] <= 2],
        key=lambda row: score_by_id[str(row["question_id"])]["score"],
    )[:24]
    controls = [
        row for row in rows if score_by_id[str(row["question_id"])]["score"] == 4
    ][:6]
    if not failures:
        raise RuntimeError("Train has no score<=2 failures; autonomous discovery cannot proceed.")
    selected = failures + controls
    trajectory_map = trajectories(log_file, {qid(row["question"]) for row in selected})
    packet: list[dict[str, Any]] = []
    for row in selected:
        judged_row = score_by_id[str(row["question_id"])]
        packet.append(
            {
                "case_id": row["question_id"],
                "paper_id_hash": hashlib.sha1(row["paper_id"].encode()).hexdigest()[:10],
                "question": row["question"],
                "gold_answers": row["gold_answers"],
                "baseline_answer": judged_row["student_answer"],
                "score": judged_row["score"],
                "judge_reasoning": judged_row["judge_reasoning"],
                "trajectory": trajectory_map.get(qid(row["question"]), []),
            }
        )
    return packet


def strip_code_fence(code: str) -> str:
    clean = code.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:python)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    return clean


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    require_inputs()
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    if manifest.get("question_counts") != EXPECTED:
        raise RuntimeError("Split is not the preregistered 100/40/120 split.")
    if manifest.get("representation_rule") != "Only canonical Qasper JSON text; no PDF files or PDF text extraction.":
        raise RuntimeError("Representation preregistration is missing.")
    if not CANONICAL_UNITS.exists():
        raise FileNotFoundError("Canonical inventory has not been prepared.")
    if args.dry_run:
        print("[DRY RUN] paths/env file/split/canonical inventory are present; API not called.")
        return 0

    values = load_env()
    run_index(values)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    baseline = run_arm(
        "train_baseline",
        RUN_ROOT,
        SPLIT_DIR / "train.json",
        EXPECTED["train"],
        values,
    )
    train_rows = load_jsonl(SPLIT_DIR / "train_questions.jsonl")
    judged = judge(
        "train_baseline",
        train_rows,
        answer_map(baseline),
        RUN_ROOT / "train_baseline_judge.json",
        values,
    )
    packet = build_packet(train_rows, judged, baseline / "deepread_run.log")
    save_json(RUN_ROOT / "blind_train_packet.json", packet)

    analysis_path = RUN_ROOT / "analysis.json"
    if analysis_path.exists():
        analysis = load_json(analysis_path)
        say("[REUSE] Analyzer result already exists.")
    else:
        say(
            f"[Analyzer] train-only packet: "
            f"{sum(row['score'] <= 2 for row in packet)} failures + "
            f"{sum(row['score'] == 4 for row in packet)} controls."
        )
        analysis = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": ANALYZER_SYSTEM},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=8000,
        )
        save_json(analysis_path, analysis)
    if not analysis.get("selected_capability"):
        save_json(
            RUN_ROOT / "AUTONOMOUS_NO_TOOL_DECISION.json",
            {
                "status": "stopped_before_tool_generation",
                "reason": analysis.get("selection_reason"),
                "analysis": analysis,
                "dev_and_test_read": False,
            },
        )
        raise RuntimeError(
            "Analyzer autonomously selected no executable capability. This is a valid blind result; dev/test remain sealed."
        )

    candidate_json_path = RUN_ROOT / "candidate.json"
    if candidate_json_path.exists():
        candidate = load_json(candidate_json_path)
        say("[REUSE] Candidate exists; replaying frozen self-tests.")
    else:
        say("[Repair Agent] Synthesizing one tool from the Analyzer decision.")
        candidate = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": ARCHITECT_SYSTEM},
                {"role": "user", "content": json.dumps(analysis, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=11000,
        )
        save_json(candidate_json_path, candidate)

    frozen_tests = candidate.get("tests") or []
    if len(frozen_tests) < 3:
        raise RuntimeError("Candidate did not generate at least three synthetic tests.")
    save_json(RUN_ROOT / "candidate_frozen_tests.json", frozen_tests)
    candidate_path = RUN_ROOT / "candidate_tool.py"
    tests: list[dict[str, Any]] = []
    pending_error: str | None = None
    for attempt in range(1, 4):
        save_json(RUN_ROOT / f"candidate_proposal_attempt{attempt}.json", candidate)
        code = strip_code_fence(str(candidate.get("code") or ""))
        candidate_path.write_text(code + "\n", encoding="utf-8")
        validation_error = pending_error
        tests = []
        if validation_error is None:
            try:
                validate_candidate(candidate_path)
                tests = run_candidate_tests(
                    load_candidate_module(candidate_path), candidate, strict=False
                )
            except Exception as exc:
                validation_error = f"{type(exc).__name__}: {exc}"
        feedback = {
            "attempt": attempt,
            "static_or_runtime_error": validation_error,
            "frozen_unit_test_results": tests,
        }
        save_json(RUN_ROOT / f"candidate_attempt{attempt}_feedback.json", feedback)
        if validation_error is None and tests and all(row["passed"] for row in tests):
            save_json(candidate_json_path, candidate)
            save_json(RUN_ROOT / "candidate_test_results.json", tests)
            break
        if attempt == 3:
            raise RuntimeError(
                "Candidate failed autonomous repair after two retries: "
                + json.dumps(feedback, ensure_ascii=False)
            )
        (RUN_ROOT / f"candidate_tool_attempt{attempt}.py").write_text(
            code + "\n", encoding="utf-8"
        )
        say(f"[SELF-REPAIR] Proposal {attempt} failed validation; autonomous repair continues.")
        raw_repair = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": SELF_REPAIR_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidate": candidate,
                            "frozen_tests": frozen_tests,
                            "validation_feedback": feedback,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
            max_tokens=11000,
        )
        save_json(RUN_ROOT / f"repair_raw_response_attempt{attempt}.json", raw_repair)
        candidate, pending_error = normalize_candidate_response(raw_repair, candidate)
        candidate["tests"] = frozen_tests

    print(f"[DONE] Autonomous single tool: {candidate_path}")
    print(f"[DONE] Frozen synthetic tests: {len(tests)}/{len(tests)} passed; dev/test unread.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

