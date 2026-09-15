from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import (
    ROOT,
    PDF_PAGES,
    RUNS_DIR,
    SPLIT_DIR,
    answer_map,
    judge,
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
    load_candidate_module,
    legacy,
)


RUN_ROOT = RUNS_DIR / "blind_qasper_seed20260822"

ANALYZER_SYSTEM = """You are the analysis agent in a blind, dataset-specific RAG tool-discovery experiment.
You receive only Qasper TRAIN questions, acceptable gold answers, baseline answers, scores, and raw tool trajectories.
You do not receive dev/test questions, previous FinanceBench tools, or human failure labels.

Find recurring causal failure mechanisms. Compare failures with successful controls. Separate document routing,
section routing, vocabulary mismatch, evidence composition, answer synthesis, and stopping. Select at most one
missing executable capability that can be implemented using only the question plus a read-only inventory of
document names and section headings. Do not propose mere prompt advice, benchmark memorization, or body-text access.

Return one JSON object with keys:
- evidence_summary
- failure_clusters: array of {name, count_estimate, causal_chain, trajectory_evidence, repairability}
- candidate_capabilities: array of {name, problem_solved, inputs, outputs, preconditions, expected_effect, risks}
- selected_capability: the single best capability or null
- selection_reason
- falsification_test
"""

ARCHITECT_SYSTEM = """You are the repair agent in a blind single-tool synthesis experiment.
Implement the analyzer's selected capability as one small, safe Python tool plus a usage policy.

Runtime contract:
- Define exactly one public function: run(question: str, corpus: list[dict], top_k: int = 5) -> dict.
- Each corpus item contains doc_id, source_name, sections, and pages.
- Each section contains node_id, title, paragraph_count, and token_count. No body text is available.
- Each page contains page_number and trusted read-only text extracted from the original paper PDF. This alternate
  representation may include table cell text that was absent from the normalized Qasper JSON.
- Return JSON-serializable data with a results list. Each result should include doc_id and may include node_id,
  page_number, title, score, text, and reasons. Return only short relevant excerpts, never a whole paper.
- Allowed imports: re, math, json, collections, typing, dataclasses.
- Forbidden: file/network/process/environment access, dynamic execution, third-party packages.
- Do not encode benchmark question IDs, gold answers, exact train paper titles, or a fixed domain entity list.
- The capability must be useful beyond the examples that generated it.

Return one JSON object with keys:
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: at least 3 generic tests, each {name, question, corpus, top_k, expected_top_doc_id,
  expected_top_node_id(optional)}
- novelty_claim: restrained wording; do not claim literature novelty
"""

ANALYZER_PDF_SYSTEM = """You are the analysis agent in the second capability-discovery pass of a blind RAG experiment.
The first pass correctly found that a question+heading-only tool could not repair recurring Qasper failures, especially
numeric values trapped in table images. The platform has now added one generic, trusted, read-only substrate: for each
paper, the tool may inspect page text extracted from the original PDF, alongside document and section metadata.
You still receive only TRAIN questions, golds, baseline answers, scores, and trajectories; dev/test remain hidden.

Reassess the same failures and select at most one executable capability that uses this substrate. Prefer a narrow,
falsifiable retrieval operation such as question-conditioned PDF table/page search if supported by the trajectories.
Do not encode train titles, question IDs, or answers. Return the same JSON keys as the first analysis and make
selected_capability non-null only if the new substrate addresses a recurring causal failure.
"""

SELF_REPAIR_SYSTEM = """You are debugging the single safe Python tool that you generated in a blind RAG experiment.
You receive the current complete candidate JSON and the exact results of its own generic unit tests. Fix the actual
algorithmic defect; do not weaken, delete, or special-case the tests. Do not insert benchmark question IDs, exact
paper titles, gold answers, or a domain entity list. Preserve the runtime contract and safety restrictions:
exactly one public run(question, corpus, top_k) function; only re, math, json, collections, typing, dataclasses;
no file/network/process/environment access. Return the same complete JSON object schema as the original candidate,
including tool_spec, code, usage_policy, tests, and novelty_claim.
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
    """Accept common JSON wrappers without silently accepting missing code."""
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
            item = {}
            for key in ("score", "title", "text", "source_name"):
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
                        "reasoning": clip(event.get("reasoning_content") or event.get("content") or "", 1000),
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
        key=lambda row: score_by_id[str(row["question_id"])]["score"],
    )[:16]
    controls = [row for row in rows if score_by_id[str(row["question_id"])]["score"] == 4][:4]
    selected = failures + controls
    trajectory_map = trajectories(log_file, {qid(row["question"]) for row in selected})
    packet = []
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
    if not failures:
        raise RuntimeError("训练集没有score<=2的失败案例，无法进行工具发现。")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    require_inputs()
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    if manifest.get("question_counts") != {"train": 60, "dev": 20, "test": 80}:
        raise RuntimeError("划分清单不是预注册的60/20/80。")
    if args.dry_run:
        print("[DryRun通过] 路径、环境文件、60/20/80论文级划分均存在；未调用API。")
        return 0

    values = load_env()
    run_index(values)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    baseline = run_arm(
        "train_baseline",
        RUN_ROOT,
        SPLIT_DIR / "train.json",
        60,
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
        say("[复用] 第一轮Analyzer结果，不重复调用API。")
    else:
        say(
            f"[Analyzer] 只读取train：{sum(row['score'] <= 2 for row in packet)}个失败 + "
            f"{sum(row['score'] == 4 for row in packet)}个成功对照……"
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
            max_tokens=7000,
        )
        save_json(analysis_path, analysis)
    if not analysis.get("selected_capability"):
        if not PDF_PAGES.exists():
            raise RuntimeError("标题结构能力被自主否决，且PDF页语料尚未准备。")
        second_path = RUN_ROOT / "analysis_pdf_pages.json"
        if second_path.exists():
            analysis = load_json(second_path)
            say("[复用] PDF页能力Analyzer结果。")
        else:
            say("[Analyzer第二轮] 根据第一轮自主发现，开放只读PDF页文本后重新选择一个能力……")
            analysis = legacy.model_json_call(
                values["TEACHER_BASE_URL"],
                values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
                values["TEACHER_MODEL"],
                [
                    {"role": "system", "content": ANALYZER_PDF_SYSTEM},
                    {"role": "user", "content": json.dumps({"first_analysis": load_json(analysis_path), "train_packet": packet}, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=7000,
            )
            save_json(second_path, analysis)
        if not analysis.get("selected_capability"):
            raise RuntimeError("开放PDF页文本后Analyzer仍未选出能力；不强迫生成无效工具。")
    candidate_json_path = RUN_ROOT / "candidate.json"
    if candidate_json_path.exists():
        candidate = load_json(candidate_json_path)
        say("[复用] 已生成的候选工具；先重放其自生成测试。")
    else:
        say("[Repair Agent] 正在生成一个Qasper专用候选工具和调用策略……")
        candidate = legacy.model_json_call(
            values["TEACHER_BASE_URL"],
            values.get("TEACHER_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["TEACHER_MODEL"],
            [
                {"role": "system", "content": ARCHITECT_SYSTEM},
                {"role": "user", "content": json.dumps(analysis, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=10000,
        )
        save_json(candidate_json_path, candidate)

    frozen_tests = candidate.get("tests") or []
    if not frozen_tests:
        raise RuntimeError("候选工具没有自生成测试，不能进入自主调试。")
    save_json(RUN_ROOT / "candidate_frozen_tests.json", frozen_tests)
    candidate_path = RUN_ROOT / "candidate_tool.py"
    tests: list[dict[str, Any]] = []
    pending_response_error: str | None = None
    for attempt in range(1, 4):
        save_json(RUN_ROOT / f"candidate_proposal_attempt{attempt}.json", candidate)
        code = str(candidate.get("code") or "").strip()
        if code.startswith("```"):
            code = re.sub(r"^```(?:python)?\s*", "", code)
            code = re.sub(r"\s*```$", "", code)
        candidate_path.write_text(code + "\n", encoding="utf-8")
        validation_error = pending_response_error
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
        if attempt >= 3:
            raise RuntimeError(
                "候选工具自主修复两次后仍未通过验收："
                + json.dumps(feedback, ensure_ascii=False)
            )
        save_json(RUN_ROOT / f"candidate_attempt{attempt}.json", candidate)
        (RUN_ROOT / f"candidate_tool_attempt{attempt}.py").write_text(
            code + "\n", encoding="utf-8"
        )
        say(f"[自主调试] 第{attempt}版未通过完整验收，Repair Agent正在修复……")
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
            max_tokens=10000,
        )
        save_json(RUN_ROOT / f"repair_raw_response_attempt{attempt}.json", raw_repair)
        candidate, pending_response_error = normalize_candidate_response(
            raw_repair, candidate
        )
        # The repair agent may rewrite code/spec/policy, but it cannot move the
        # goalposts after seeing failures. Always restore the original tests.
        candidate["tests"] = frozen_tests
    print(f"[完成] AI自主生成单工具：{candidate_path}")
    print(f"[完成] 自生成测试：{len(tests)}/{len(tests)}通过；dev/test尚未读取。")
    print(f"[下一步] 运行 .\\run_dev_ab.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
