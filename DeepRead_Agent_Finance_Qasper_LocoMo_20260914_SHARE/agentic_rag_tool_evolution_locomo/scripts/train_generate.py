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


RUN_ROOT = RUNS_DIR / "blind_locomo_single_tool_v1"

ANALYZER_SYSTEM = """You are the Analyzer in a blind autonomous single-tool LocoMo RAG experiment.
You receive only TRAIN questions, gold answers, baseline answers, judge scores, categories, and baseline retrieval
trajectories. You receive no test questions, prior tools, old reports, or human failure labels.

Infer recurring causal failure mechanisms and select exactly one missing executable corpus-navigation or evidence-
extraction capability with the largest plausible train-wide benefit. The runtime substrate is a read-only inventory of
all conversation documents. Each document exposes session index, session date/time, speaker, dialogue id, session
summary, and utterance text. Do not propose prompt-only advice, memorize names or answers, or assume access to golds.
If no single tool is justified, selected_capability may be null.

Return one JSON object with keys:
- evidence_summary
- failure_clusters: array of {name, count_estimate, causal_chain, trajectory_evidence, repairability}
- candidate_capabilities: array of {name, problem_solved, inputs, outputs, preconditions, expected_effect, risks}
- selected_capability: one capability or null
- selection_reason
- falsification_test
"""

ARCHITECT_SYSTEM = """You are the Repair Agent in a blind autonomous single-tool LocoMo synthesis experiment.
Implement only the Analyzer's selected capability as one safe Python tool and an explicit usage policy.

Runtime contract:
- Define exactly one public function: run(question: str, corpus: list[dict], top_k: int = 5) -> dict.
- Each corpus item contains doc_id, source_name, title, sections, and pages.
- Each pages item is a trusted canonical LocoMo text unit with unit_index/page_number, session_index, date_time,
  speaker, dia_id, section_name, and text. It is not a PDF page.
- Return JSON-serializable data with a bounded `results` list. Results may include doc_id, node_id, unit_index,
  page_number, title, score, text, source_name, and reasons.
- Allowed imports: re, math, json, collections, typing, dataclasses.
- Forbidden: file/network/process/environment access, dynamic execution, and third-party packages.
- Do not encode benchmark question IDs, gold answers, exact train conversation IDs, person-name lists, or fixed facts.
- The tool must generalize to unseen conversations.

Return one JSON object with keys:
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: at least 4 synthetic generic tests with name, question, corpus, top_k, expected_top_doc_id and optional
  expected_top_unit_index
- novelty_claim: restrained wording
"""

SELF_REPAIR_SYSTEM = """Autonomously debug the safe single Python tool you generated. Preserve the original frozen
tests and repair the implementation rather than weakening or special-casing tests. Do not add benchmark IDs, names,
gold answers, or fixed facts. Preserve exactly one public run(question, corpus, top_k) function and all sandbox rules.
Return the complete candidate JSON with tool_spec, code, usage_policy, tests, and novelty_claim."""


def clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def qid(question: str) -> str:
    return hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]


def compact_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return clip(result, 500)
    compact: dict[str, Any] = {"ok": result.get("ok")}
    for key in ("query", "scope", "doc_id", "title", "error"):
        if result.get(key) is not None:
            compact[key] = clip(result[key], 180)
    if isinstance(result.get("results"), list):
        compact["results"] = []
        for row in result["results"][:3]:
            if not isinstance(row, dict):
                compact["results"].append(clip(row, 300))
                continue
            item = {
                key: clip(row[key], 280)
                for key in (
                    "doc_id", "node_id", "unit_index", "page_number", "score",
                    "title", "text", "source_name", "reasons",
                )
                if row.get(key) is not None
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
                            event.get("reasoning_content") or event.get("content") or "", 700
                        ),
                        "tool_calls": event.get("tool_calls") or [],
                    }
                )
            elif kind == "tool_call":
                grouped[event_qid].append(
                    {"event": kind, "tool": event.get("tool"), "args": event.get("args") or {}}
                )
            elif kind == "tool_result":
                grouped[event_qid].append(
                    {"event": kind, "tool": event.get("tool"), "result": compact_result(event.get("result"))}
                )
    return grouped


def build_packet(
    rows: list[dict[str, Any]], judged: list[dict[str, Any]], log_file: Path
) -> list[dict[str, Any]]:
    score_by_id = {str(row["case_id"]): row for row in judged}
    failures = sorted(
        [row for row in rows if score_by_id[str(row["question_id"])]["score"] <= 2],
        key=lambda row: (score_by_id[str(row["question_id"])]["score"], row["question_id"]),
    )[:18]
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
                "conversation_hash": hashlib.sha1(row["sample_id"].encode()).hexdigest()[:10],
                "category": row.get("category"),
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


def normalize_repair(response: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return previous
    for key in ("candidate", "repaired_candidate", "result"):
        if isinstance(response.get(key), dict) and str(response[key].get("code") or "").strip():
            return response[key]
    if str(response.get("code") or "").strip():
        return response
    for key in ("repaired_code", "tool_code", "python_code"):
        if str(response.get(key) or "").strip():
            result = dict(previous)
            result["code"] = response[key]
            return result
    return previous


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    require_inputs()
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    train_count = int(manifest["question_counts"]["train"])
    if manifest.get("split_unit") != "conversation/sample_id":
        raise RuntimeError("Conversation-disjoint preregistration is missing.")
    if not CANONICAL_UNITS.exists():
        raise FileNotFoundError("Canonical LocoMo inventory has not been prepared.")
    if args.dry_run:
        print(f"[DRY RUN] train={train_count}; paths/env/split/inventory ready; API not called.")
        return 0

    values = load_env()
    run_index(values)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    baseline = run_arm(
        "train_baseline", RUN_ROOT, SPLIT_DIR / "train.json", train_count, values
    )
    train_rows = load_jsonl(SPLIT_DIR / "train_questions.jsonl")
    judged = judge(
        "locomo_train_baseline",
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
            f"[Analyzer] train only: {sum(row['score'] <= 2 for row in packet)} failures + "
            f"{sum(row['score'] == 4 for row in packet)} controls; test unread."
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
            {"status": "no_tool", "analysis": analysis, "test_read": False},
        )
        raise RuntimeError("Analyzer selected no executable single capability; test remains sealed.")

    candidate_json_path = RUN_ROOT / "candidate.json"
    if candidate_json_path.exists():
        candidate = load_json(candidate_json_path)
        say("[REUSE] Candidate exists; replaying frozen self-tests.")
    else:
        say("[Repair Agent] Implementing exactly one selected LocoMo capability.")
        candidate = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": ARCHITECT_SYSTEM},
                {"role": "user", "content": json.dumps(analysis, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=12000,
        )
        save_json(candidate_json_path, candidate)
    frozen_tests = candidate.get("tests") or []
    if len(frozen_tests) < 4:
        raise RuntimeError("Candidate generated fewer than four frozen self-tests.")
    save_json(RUN_ROOT / "candidate_frozen_tests.json", frozen_tests)
    candidate_path = RUN_ROOT / "candidate_tool.py"
    tests: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        candidate["tests"] = frozen_tests
        save_json(RUN_ROOT / f"candidate_proposal_attempt{attempt}.json", candidate)
        candidate_path.write_text(strip_code_fence(str(candidate.get("code") or "")) + "\n", encoding="utf-8")
        error: str | None = None
        try:
            validate_candidate(candidate_path)
            tests = run_candidate_tests(load_candidate_module(candidate_path), candidate, strict=False)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        feedback = {"attempt": attempt, "error": error, "frozen_test_results": tests}
        save_json(RUN_ROOT / f"candidate_attempt{attempt}_feedback.json", feedback)
        if error is None and tests and all(row["passed"] for row in tests):
            save_json(candidate_json_path, candidate)
            save_json(RUN_ROOT / "candidate_test_results.json", tests)
            break
        if attempt == 3:
            raise RuntimeError("Candidate failed autonomous repair: " + json.dumps(feedback, ensure_ascii=False))
        say(f"[SELF-REPAIR] attempt {attempt} failed; autonomous repair continues.")
        repaired = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": SELF_REPAIR_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"candidate": candidate, "frozen_tests": frozen_tests, "feedback": feedback},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
            max_tokens=12000,
        )
        save_json(RUN_ROOT / f"repair_raw_response_attempt{attempt}.json", repaired)
        candidate = normalize_repair(repaired, candidate)

    print(f"[DONE] Train baseline={train_count}; autonomous single tool={candidate_path}")
    print(f"[DONE] Frozen self-tests={len(tests)}/{len(tests)}; test remains unread.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

