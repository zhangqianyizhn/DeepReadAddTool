from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
SCRIPT_DIR = HERE.parent
sys.path.insert(0, str(SCRIPT_DIR))
import dev_ab as core  # noqa: E402


REPAIR_SYSTEM = """You are the autonomous repair agent in a closed-loop RAG tool-evolution experiment.
An earlier agent independently diagnosed a missing document-selection capability and generated a Python tool.
That frozen tool has now been evaluated on a development set. You receive the original analysis, code,
usage policy, paired baseline/candidate scores, and compact candidate trajectories.

Diagnose the observed behavior from the evidence yourself. Do not assume that the human experiment runner
knows the bug. Decide which problems are in parsing/ranking code, which are in the usage policy, and which are
outside this tool's scope. Repair the existing capability conservatively. Do not encode benchmark answers,
question IDs, dataset company names, or a hand-written alias list for observed companies. Prefer general
normalization, acronym, tokenization, date, period, and metadata rules that can transfer to other corpora.
Do not add a second incompatible tool in this round.

The executable contract remains exactly:
    run(question: str, documents: list[dict[str, str]], top_k: int = 5) -> dict
Documents contain only doc_id and source_name. Return JSON-serializable data with ranked results.
Allowed imports: re, math, json, collections, typing, dataclasses.
Forbidden: file/network/process/environment access, dynamic execution, third-party packages.

Return one JSON object with keys:
- repair_analysis: {what_worked, failure_mechanisms, scope_boundary}
- changes: array of concrete general changes
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete repaired Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: at least 6 generic test objects with {name, question, documents, top_k, expected_top_doc_id}
- prediction: {expected_quality_effect, expected_cost_effect, falsification_test}
- novelty_claim: restrained; do not claim literature novelty
"""


CORRECTION_SYSTEM = """You are continuing an autonomous RAG tool-repair attempt.
Your previous candidate was rejected by an automated, generic validation gate. Repair the candidate from the
machine feedback without hard-coding the failing test, benchmark companies, question IDs, or expected document
IDs. Preserve improvements that already passed. Return a complete replacement JSON object with the same keys
and the same run(question, documents, top_k) contract. Include at least 6 generic tests using
expected_top_doc_id. The corrected code must remain safe and generalizable.
"""


def say(message: str) -> None:
    print(message, flush=True)


def clip(value: Any, limit: int = 900) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_log_events(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = str(event.get("query_id") or "")
            kind = str(event.get("event") or "")
            if not qid:
                continue
            if kind == "llm_response":
                grouped[qid].append(
                    {
                        "event": kind,
                        "round": event.get("round"),
                        "reasoning": clip(event.get("reasoning_content") or event.get("content") or "", 700),
                        "tools": [item.get("name") for item in (event.get("tool_calls") or [])],
                    }
                )
            elif kind == "tool_call":
                grouped[qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "args": event.get("args") or {},
                    }
                )
            elif kind == "tool_result":
                result = event.get("result")
                if event.get("tool") == "document_inventory_search" and isinstance(result, dict):
                    compact_result = {
                        "query_parsed": result.get("query_parsed"),
                        "results": (result.get("results") or [])[:5],
                        "coverage": result.get("coverage"),
                    }
                elif isinstance(result, dict):
                    compact_result = {
                        "ok": result.get("ok"),
                        "error": result.get("error"),
                        "preview": clip(result, 650),
                    }
                else:
                    compact_result = {"preview": clip(result, 650)}
                grouped[qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "result": compact_result,
                    }
                )
    return grouped


def question_id(question: str) -> str:
    import hashlib

    return hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]


def make_feedback_packet(blind_run: Path) -> dict[str, Any]:
    dev_run = blind_run / "dev_ab"
    baseline = core.load_json(dev_run / "baseline_judged.json").get("results", [])
    candidate = core.load_json(dev_run / "generated_tool_judged.json").get("results", [])
    dev_rows = core.load_jsonl(dev_run / "dev_input.jsonl")
    by_id = {row["financebench_id"]: row for row in dev_rows}
    baseline_by_id = {row["case_id"]: row for row in baseline}
    candidate_by_id = {row["case_id"]: row for row in candidate}
    log_path = next((dev_run / "generated_tool").glob("output_*/deepread_run.log"), None)
    if log_path is None:
        raise RuntimeError("缺少候选组dev轨迹。")
    trajectories = load_log_events(log_path)

    cases: list[dict[str, Any]] = []
    for case_id, row in by_id.items():
        before = baseline_by_id[case_id]
        after = candidate_by_id[case_id]
        gold_sources = sorted(
            {
                str(item.get("doc_name"))
                for item in (row.get("evidence") or [])
                if isinstance(item, dict) and item.get("doc_name")
            }
        )
        cases.append(
            {
                "case_id": case_id,
                "question": row["question"],
                "gold_evidence_sources": gold_sources,
                "baseline_score": before["score"],
                "candidate_score": after["score"],
                "score_delta": after["score"] - before["score"],
                "candidate_judge_reason": after.get("judge_reasoning"),
                "candidate_answer": clip(after.get("student_answer"), 1200),
                "candidate_input_tokens": after.get("input_tokens"),
                "candidate_latency_sec": after.get("latency_sec"),
                "trajectory": trajectories.get(question_id(row["question"]), [])[:35],
            }
        )

    comparison = core.paired(baseline, candidate)
    baseline_metrics = core.metrics(baseline)
    candidate_metrics = core.metrics(candidate)
    return {
        "experiment": "autonomous_tool_repair_round2",
        "data_policy": {
            "tool_generation_source": "train only",
            "repair_feedback_source": "dev only",
            "test_access": False,
            "human_failure_labels": False,
        },
        "aggregate": {
            "paired": {key: comparison[key] for key in ("wins", "ties", "losses", "net_score")},
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
        },
        "cases": cases,
    }


def validate_no_case_leakage(code: str, blind_run: Path) -> None:
    tree = ast.parse(code)
    string_literals = {
        re.sub(r"[^a-z0-9]+", "", node.value.lower())
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    company_names: set[str] = set()
    for split in ("train", "dev"):
        split_path = WORKSPACE / "agentic_rag_self_learning_v2" / "data" / "splits" / f"{split}.jsonl"
        for row in core.load_jsonl(split_path):
            company = re.sub(r"[^a-z0-9]+", "", str(row.get("company") or "").lower())
            if len(company) >= 3 and company not in {"block"}:
                company_names.add(company)
    leaked = sorted(company_names & string_literals)
    if leaked or "financebench_id" in code.lower():
        raise RuntimeError(
            "修复代码疑似硬编码训练/dev个案，已拒绝接入："
            + ", ".join(leaked[:8] or ["financebench_id"])
        )


def generate_repair(blind_run: Path, feedback: dict[str, Any], dry_run: bool) -> Path:
    repair_dir = blind_run / "repair_round2"
    repair_dir.mkdir(parents=True, exist_ok=True)
    packet_path = repair_dir / "repair_feedback_packet.json"
    if not packet_path.exists():
        core.save_json(packet_path, feedback)
    if dry_run:
        return repair_dir

    candidate_path = repair_dir / "candidate.json"
    tool_path = repair_dir / "candidate_tool.py"
    if candidate_path.exists() and tool_path.exists():
        say(f"[复用] 已生成Round 2候选：{candidate_path}")
        return repair_dir

    original = core.load_json(blind_run / "candidate.json")
    payload = {
        "original_analysis": core.load_json(blind_run / "analysis.json"),
        "original_tool_spec": original.get("tool_spec"),
        "original_code": (blind_run / "candidate_tool.py").read_text(encoding="utf-8"),
        "original_usage_policy": original.get("usage_policy"),
        "development_feedback": feedback,
    }
    env = core.legacy.load_experiment_env()
    prior_candidate: dict[str, Any] | None = None
    validation_feedback = ""
    last_error: Exception | None = None
    for attempt in range(1, 4):
        if attempt == 1:
            say(f"[Repair Agent] {env['TEACHER_MODEL']} 正在自主分析dev反馈并修复工具……")
            messages = [
                {"role": "system", "content": REPAIR_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        else:
            say(f"[自动纠错] Repair Agent 正在根据第{attempt - 1}版的机器测试失败重写候选……")
            correction_payload = {
                "rejected_candidate": prior_candidate,
                "automated_validation_feedback": validation_feedback,
                "instruction": (
                    "Fix the general algorithm, not the individual example. Return the complete candidate."
                ),
            }
            messages = [
                {"role": "system", "content": CORRECTION_SYSTEM},
                {"role": "user", "content": json.dumps(correction_payload, ensure_ascii=False)},
            ]

        repaired = core.legacy.model_json_call(
            env["TEACHER_BASE_URL"],
            env.get("TEACHER_API_KEY") or env["VOLCENGINE_API_KEY"],
            env["TEACHER_MODEL"],
            messages,
            temperature=0,
            max_tokens=9000,
        )
        prior_candidate = repaired
        core.save_json(repair_dir / f"candidate_attempt_{attempt}.json", repaired)
        code = str(repaired.get("code") or "")
        attempt_tool = repair_dir / f"candidate_tool_attempt_{attempt}.py"
        attempt_tool.write_text(code, encoding="utf-8")
        try:
            core.validate_candidate(attempt_tool)
            validate_no_case_leakage(code, blind_run)
            module = core.load_candidate_module(attempt_tool)
            tests = core.run_generated_tests(module, repaired)
            repaired["generated_test_results"] = tests
            repaired["static_safety_problems"] = []
            tool_path.write_text(code, encoding="utf-8")
            core.save_json(candidate_path, repaired)
            say(
                f"[Repair Agent完成] 第{attempt}版通过安全、泄漏与"
                f"{len(tests)}项自生成测试。"
            )
            return repair_dir
        except Exception as exc:
            last_error = exc
            validation_feedback = str(exc)
            core.save_json(
                repair_dir / f"candidate_attempt_{attempt}_rejection.json",
                {
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                    "automated_feedback": validation_feedback,
                },
            )
            say(f"[自动门禁] 第{attempt}版未通过：{validation_feedback}")

    raise RuntimeError(
        "Repair Agent连续3版未通过自动门禁；所有候选与机器反馈均已保存。"
        f"最后错误：{last_error}"
    )


def tool_call_summary(log_path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    query_ids: set[str] = set()
    rounds = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "tool_call":
                counts[str(event.get("tool"))] += 1
            if event.get("event") == "llm_response":
                rounds += 1
                query_ids.add(str(event.get("query_id")))
    return {"questions": len(query_ids), "rounds": rounds, "tool_calls": dict(counts)}


def append_round2_report(
    report_path: Path,
    repaired: dict[str, Any],
    original_report: Path,
    candidate_output: Path,
) -> None:
    base_text = report_path.read_text(encoding="utf-8")
    summary = tool_call_summary(candidate_output / "deepread_run.log")
    additions = [
        "",
        "## Round 2自主修复说明",
        "",
        "本轮Repair Agent只获得原候选、dev成对结果和原始轨迹；未提供人工故障结论，未访问test。",
        "",
        "### Agent自主诊断",
        "",
        "```json",
        json.dumps(repaired.get("repair_analysis"), ensure_ascii=False, indent=2),
        "```",
        "",
        "### Agent自主修改",
        "",
        "```json",
        json.dumps(repaired.get("changes"), ensure_ascii=False, indent=2),
        "```",
        "",
        f"- 原Round 1报告：`{original_report}`",
        f"- 修复组总轮数：{summary['rounds']}",
        f"- 修复组工具调用：`{json.dumps(summary['tool_calls'], ensure_ascii=False)}`",
        "",
    ]
    report_path.write_text(base_text + "\n" + "\n".join(additions), encoding="utf-8")


def evaluate_repair(blind_run: Path, repair_dir: Path) -> Path:
    original_dev = blind_run / "dev_ab"
    baseline_path = original_dev / "baseline_judged.json"
    rows_file = original_dev / "dev_input.jsonl"
    baseline = core.load_json(baseline_path).get("results", [])
    rows = core.load_jsonl(rows_file)
    repaired = core.load_json(repair_dir / "candidate.json")
    env = core.legacy.load_experiment_env()
    dev_run = repair_dir / "dev_ab"
    dev_run.mkdir(parents=True, exist_ok=True)

    output = core.run_arm(
        "repaired_generated_tool",
        dev_run,
        rows_file,
        len(rows),
        repair_dir / "candidate_tool.py",
        True,
        core.generated_policy(repaired),
        env,
    )
    judged = core.judge(
        "repaired_generated_tool",
        rows,
        core.answer_map(output),
        dev_run / "repaired_generated_tool_judged.json",
        env,
    )
    report = dev_run / "ROUND2_DEV_AB_REPORT.md"
    core.write_report(
        report,
        repair_dir,
        baseline,
        judged,
        repaired.get("generated_test_results") or [],
    )
    append_round2_report(report, repaired, original_dev / "DEV_AB_REPORT.md", output)
    comparison = core.paired(baseline, judged)
    say(
        f"[完成] Round 2 vs原Baseline：{comparison['wins']}胜/"
        f"{comparison['ties']}平/{comparison['losses']}负，净分={comparison['net_score']:+d}"
    )
    say(f"[报告] {report}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    blind_run = core.latest_blind_run()
    required = [
        blind_run / "candidate.json",
        blind_run / "candidate_tool.py",
        blind_run / "analysis.json",
        blind_run / "dev_ab" / "baseline_judged.json",
        blind_run / "dev_ab" / "generated_tool_judged.json",
        blind_run / "dev_ab" / "dev_input.jsonl",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Round 2缺少输入：\n" + "\n".join(missing))
    feedback = make_feedback_packet(blind_run)
    say(
        f"[反馈就绪] dev={len(feedback['cases'])}题；"
        f"test访问={feedback['data_policy']['test_access']}；人工故障标签={feedback['data_policy']['human_failure_labels']}"
    )
    repair_dir = generate_repair(blind_run, feedback, args.dry_run)
    if args.dry_run:
        say(f"[DryRun完成] 反馈包已生成：{repair_dir / 'repair_feedback_packet.json'}；未调用API。")
        return 0
    evaluate_repair(blind_run, repair_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 已生成候选、答案和Judge评分均保留，重新运行同一命令继续。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
