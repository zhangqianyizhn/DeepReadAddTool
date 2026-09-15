from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import content2 as core  # noqa: E402
import round2 as paired_eval  # noqa: E402


ROOT = core.ROOT
ROUND3 = ROOT / "runs" / "round3"
BATCH_DIR = ROUND3 / "experience_batches"
LIBRARY_PATH = ROUND3 / "experience_library.json"
ROUTE_PREVIEW = ROUND3 / "route_preview_dev.json"
DEV_RUN = ROUND3 / "dev_candidate"
TEST_RUN = ROOT / "runs" / "round3_frozen_test61"
MAX_EXPERIENCES = 12
MAX_EXPERIENCES_PER_QUESTION = 2

FAILURE_STAGES = {
    "title_routing",
    "document_commitment",
    "content_query",
    "section_selection",
    "evidence_coverage",
    "numerical_reasoning",
    "qualitative_reasoning",
    "temporal_or_unit_alignment",
    "answer_completeness",
    "search_loop_or_cost",
    "gold_or_judge_ambiguity",
}
REPAIR_OPERATORS = {
    "QUERY_POLICY",
    "EVIDENCE_GUARD",
    "COMPARISON_GUARD",
    "ANSWER_GUARD",
    "STOP_RULE",
    "WORKFLOW_POLICY",
}
ROUTING_TAGS = {
    "numerical",
    "calculation",
    "trend",
    "comparison",
    "entity",
    "extraction",
    "temporal",
    "unit",
    "rounding",
    "complete_set",
    "source_scope",
}
SPECIFIC_TAGS = ROUTING_TAGS - {"extraction"}
CONFIDENCE_SCORE = {"high": 3, "medium": 2, "low": 1}


def stable_id(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def teacher_case(record: dict[str, Any]) -> dict[str, Any]:
    """Keep the causal evidence that Round 1 previously discarded before repair."""
    return {
        "case_id": record["case_id"],
        "question_type": record.get("question_type"),
        "question_reasoning": record.get("question_reasoning"),
        "question": record.get("question"),
        "gold_answer": record.get("gold_answer"),
        "student_answer": record.get("student_answer"),
        "judge_score": record.get("judge_score"),
        "judge_reasoning": record.get("judge_reasoning"),
        "evidence_recall": record.get("evidence_recall"),
        "title_rank": record.get("title_rank"),
        "gold_evidence": record.get("gold_evidence", [])[:3],
        "retrieved_snippets": record.get("retrieved_snippets", [])[:4],
        "trajectory": record.get("trajectory", {}),
    }


def normalized_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip().lower() for item in value if str(item).strip().lower() in ROUTING_TAGS})


def normalize_experience(item: Any, allowed_case_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    stage = str(item.get("failure_stage") or "").strip()
    operator = str(item.get("repair_operator") or "").strip().upper()
    required = normalized_tags(item.get("required_tags"))
    any_tags = normalized_tags(item.get("any_tags"))
    excluded = normalized_tags(item.get("excluded_tags"))
    instruction = re.sub(r"\s+", " ", str(item.get("student_instruction") or "")).strip()
    trigger = re.sub(r"\s+", " ", str(item.get("trigger_description") or "")).strip()
    boundary = re.sub(r"\s+", " ", str(item.get("do_not_apply_when") or "")).strip()
    evidence = re.sub(r"\s+", " ", str(item.get("causal_evidence") or "")).strip()
    support = sorted(
        {
            str(case_id)
            for case_id in (item.get("supporting_case_ids") or [])
            if str(case_id) in allowed_case_ids
        }
    )
    confidence = str(item.get("confidence") or "low").strip().lower()
    if confidence not in CONFIDENCE_SCORE:
        confidence = "low"
    if stage not in FAILURE_STAGES or operator not in REPAIR_OPERATORS:
        return None
    if (
        not instruction
        or len(instruction.split()) > 90
        or len(instruction) > 700
        or not trigger
        or len(trigger) > 600
        or len(boundary) > 600
        or not evidence
        or len(evidence) > 1600
        or not support
    ):
        return None
    if not required and not any_tags:
        return None
    if not (set(required) | set(any_tags)) & SPECIFIC_TAGS:
        return None
    signature = "|".join(
        [operator, stage, ",".join(required), ",".join(any_tags), instruction.lower()]
    )
    return {
        "experience_id": f"exp_{stable_id(signature)}",
        "failure_stage": stage,
        "repair_operator": operator,
        "required_tags": required,
        "any_tags": any_tags,
        "excluded_tags": excluded,
        "trigger_description": trigger,
        "student_instruction": instruction,
        "do_not_apply_when": boundary,
        "supporting_case_ids": support,
        "causal_evidence": evidence,
        "confidence": confidence,
        "status": "candidate",
    }


def assert_no_student_leak(experiences: list[dict[str, Any]]) -> None:
    companies = {
        str(row.get("company") or "").strip()
        for row in core.load_jsonl(core.SOURCE_JSONL)
        if len(str(row.get("company") or "").strip()) >= 3
    }
    student_text = "\n".join(
        f"{item['student_instruction']} {item.get('do_not_apply_when', '')}"
        for item in experiences
    )
    leaked = sorted(
        name
        for name in companies
        if name and re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", student_text)
    )
    forbidden = bool(re.search(r"financebench_id|\$\s*\d|\b20\d{2}\b", student_text, flags=re.I))
    if leaked or forbidden:
        raise RuntimeError(
            "经验库包含疑似个案泄漏，已拒绝：" + ", ".join(leaked[:5] or ["case-specific value"])
        )


def build_experience_library() -> dict[str, Any]:
    core.prepare()
    if LIBRARY_PATH.exists():
        core.say("[Round3 Teacher] 复用已生成的结构化经验库。")
        return core.load_json(LIBRARY_PATH)

    records = core.load_jsonl(core.TRAJECTORY_FILE)
    cases = core.select_teacher_cases(records, limit=30)
    if any(item.get("split") != "train" for item in cases):
        raise RuntimeError("Teacher输入包含非训练集记录，已停止。")
    prompt = (ROOT / "prompts" / "experience_extractor.md").read_text(encoding="utf-8")
    env = core.legacy.load_experiment_env()
    experiences: list[dict[str, Any]] = []
    batch_size = 5
    for offset in range(0, len(cases), batch_size):
        batch = cases[offset : offset + batch_size]
        batch_no = offset // batch_size + 1
        output_path = BATCH_DIR / f"batch_{batch_no:02d}.json"
        if output_path.exists():
            result = core.load_json(output_path)
            core.say(f"[Round3 Teacher] 复用第{batch_no}批经验。")
        else:
            core.say(f"[Round3 Teacher] 第{batch_no}批，共{len(batch)}例……")
            result = core.model_call(
                env,
                "teacher",
                prompt,
                {"cases": [teacher_case(item) for item in batch]},
                8192,
            )
            core.save_json(output_path, result)
        raw = result.get("experiences") or result.get("experience_records") or []
        if not isinstance(raw, list):
            raise RuntimeError(f"Round3 Teacher第{batch_no}批没有返回experiences数组。")
        allowed = {str(item["case_id"]) for item in batch}
        for item in raw:
            normalized = normalize_experience(item, allowed)
            if normalized is not None:
                experiences.append(normalized)

    deduplicated: dict[str, dict[str, Any]] = {}
    for item in experiences:
        experience_id = item["experience_id"]
        if experience_id not in deduplicated:
            deduplicated[experience_id] = item
            continue
        previous = deduplicated[experience_id]
        previous["supporting_case_ids"] = sorted(
            set(previous["supporting_case_ids"]) | set(item["supporting_case_ids"])
        )
        if CONFIDENCE_SCORE[item["confidence"]] > CONFIDENCE_SCORE[previous["confidence"]]:
            previous["confidence"] = item["confidence"]

    ranked = sorted(
        deduplicated.values(),
        key=lambda item: (
            len(item["supporting_case_ids"]),
            CONFIDENCE_SCORE[item["confidence"]],
            len(item["required_tags"]),
            -len(item["student_instruction"]),
        ),
        reverse=True,
    )[:MAX_EXPERIENCES]
    if not ranked:
        raise RuntimeError("Teacher未生成任何通过结构和泄漏检查的经验记录。")
    assert_no_student_leak(ranked)
    library = {
        "version": "round3_trace_grounded_routed_v1",
        "teacher_visibility": "train_only",
        "source_cases": [item["case_id"] for item in cases],
        "max_experiences_per_question": MAX_EXPERIENCES_PER_QUESTION,
        "experiences": ranked,
    }
    core.save_json(LIBRARY_PATH, library)
    return library


def classify_question(row: dict[str, Any]) -> set[str]:
    question = str(row.get("question") or "").lower()
    reasoning = str(row.get("question_reasoning") or "").lower()
    tags: set[str] = set()

    if "numerical" in reasoning or re.search(
        r"\b(calculate|compute|ratio|margin|percentage|percent|how much|amount|revenue growth|per share|ebitda|capex)\b",
        question,
    ):
        tags.add("numerical")
    if re.search(r"\b(calculate|compute|formula|defined as|divided by|less|growth rate|ratio)\b", question):
        tags.add("calculation")
    if re.search(r"\b(improv|trend|accelerat|decelerat|increase|decrease|declin|grew|growth|change)\w*\b", question):
        tags.add("trend")
    if re.search(r"\b(compare|versus|vs\.?|higher|lower|highest|lowest|largest|smallest|most|least|greater)\b", question):
        tags.add("comparison")
    if re.search(r"\b(which|who|whose|identity|named|name of|key agenda|issuer|executive|ceo|segment|region)\b", question):
        tags.add("entity")
    if re.search(r"\b(what|which|who|how much|how many|state|identify|key agenda)\b", question):
        tags.add("extraction")
    if re.search(r"\b(fy\s?\d{2,4}|20\d{2}|quarter|q[1-4]|year|period|as of|dated)\b", question):
        tags.add("temporal")
    if re.search(r"\b(unit|units|percent|percentage|million|billion|thousand|usd|dollars?|basis points?|bps)\b", question):
        tags.add("unit")
    if re.search(r"\b(round|decimal places?|nearest|precision)\b", question):
        tags.add("rounding")
    if re.search(r"\b(highest|lowest|largest|smallest|most|least|all (?:segments|regions|years|categories))\b", question):
        tags.add("complete_set")
    if re.search(r"\b(only has access|only use|primarily within|based only|statement of|according to)\b", question):
        tags.add("source_scope")
    return tags


def select_experiences(
    row: dict[str, Any], experiences: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], int]]:
    tags = classify_question(row)
    candidates: list[tuple[dict[str, Any], int]] = []
    for item in experiences:
        required = set(item.get("required_tags", []))
        any_tags = set(item.get("any_tags", []))
        excluded = set(item.get("excluded_tags", []))
        if not required.issubset(tags) or excluded & tags:
            continue
        any_matches = any_tags & tags
        if any_tags and not any_matches:
            continue
        score = (
            4 * len(required)
            + 2 * len(any_matches)
            + CONFIDENCE_SCORE.get(str(item.get("confidence")), 1)
            + min(2, len(item.get("supporting_case_ids", [])))
        )
        candidates.append((item, score))
    candidates.sort(key=lambda pair: (pair[1], pair[0]["experience_id"]), reverse=True)
    selected: list[tuple[dict[str, Any], int]] = []
    seen_operators: set[str] = set()
    for item, score in candidates:
        operator = str(item["repair_operator"])
        if operator in seen_operators:
            continue
        selected.append((item, score))
        seen_operators.add(operator)
        if len(selected) == MAX_EXPERIENCES_PER_QUESTION:
            break
    return selected


def routed_instruction(item: dict[str, Any]) -> str:
    instruction = str(item["student_instruction"]).strip()
    boundary = str(item.get("do_not_apply_when") or "").strip()
    if boundary:
        clean_boundary = boundary.rstrip(".")
        return f"{instruction} Do not apply this rule when {clean_boundary}."
    return instruction


def build_route_manifest(
    split: str,
    library: dict[str, Any],
    selector: Any = None,
) -> dict[str, Any]:
    rows = core.load_jsonl(core.SPLIT_DIR / f"{split}.jsonl")
    experiences = list(library.get("experiences", []))
    selector = selector or select_experiences
    routed: list[dict[str, Any]] = []
    for row in rows:
        selected = selector(row, experiences)
        routed.append(
            {
                "case_id": row["financebench_id"],
                "question": row["question"],
                "tags": sorted(classify_question(row)),
                "selected_experiences": [item["experience_id"] for item, _ in selected],
                "scores": {item["experience_id"]: score for item, score in selected},
                "fallback_to_baseline": not selected,
            }
        )
    return {
        "split": split,
        "library_version": library["version"],
        "max_experiences_per_question": MAX_EXPERIENCES_PER_QUESTION,
        "routes": routed,
    }


def run_student_rows(rows: list[dict[str, Any]], route_id: str, instructions: list[str], run_root: Path) -> Path:
    stage = run_root / route_id
    stage.mkdir(parents=True, exist_ok=True)
    completed = core.find_complete_output(stage, len(rows))
    if completed is not None:
        core.say(f"[Round3 Student] 复用已完成路由：{route_id}（{len(rows)}题）")
        return completed
    raw_data = stage / "input.jsonl"
    core.save_jsonl(raw_data, rows)
    config = core.make_config(raw_data, stage / "output", instructions, len(rows))
    config["project_name"] = "AgenticRAGSelfLearningV2Round3"
    config["dataset_name"] = f"FinanceBenchRound3_{route_id}"
    config_path = stage / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    env_values = core.legacy.load_experiment_env()
    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env["PYTHONUTF8"] = "1"
    core.say(f"[Round3 Student] 运行路由 {route_id}（{len(rows)}题，{len(instructions)}条经验）……")
    result = subprocess.run(
        [sys.executable, str(core.HARNESS), "--config", str(config_path), "--step", "gen", "--skip-ingest"],
        cwd=str(core.REPO / "ov_test"),
        env=process_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Round3 Student运行失败：{route_id}")
    completed = core.find_complete_output(stage, len(rows))
    if completed is None:
        raise RuntimeError(f"Round3 Student没有生成完整答案：{route_id}")
    return completed


def run_routed(
    split: str,
    library: dict[str, Any],
    run_root: Path,
    selector: Any = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rows = core.load_jsonl(core.SPLIT_DIR / f"{split}.jsonl")
    by_case = {row["financebench_id"]: row for row in rows}
    by_experience = {item["experience_id"]: item for item in library["experiences"]}
    manifest = build_route_manifest(split, library, selector)
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for route in manifest["routes"]:
        key = tuple(route["selected_experiences"])
        if key:
            groups[key].append(by_case[route["case_id"]])

    answers = core.baseline_answers(split)
    for experience_ids, group_rows in groups.items():
        membership = "|".join(sorted(str(row["financebench_id"]) for row in group_rows))
        route_signature = "|".join(
            [str(library.get("version") or "unknown"), *experience_ids, membership]
        )
        route_id = "route_" + stable_id(route_signature, 10)
        instructions = [routed_instruction(by_experience[item_id]) for item_id in experience_ids]
        output = run_student_rows(group_rows, route_id, instructions, run_root / "routes")
        answers.update(core.generated_answers(output))

    if len(answers) != len(rows):
        raise RuntimeError(f"Round3合并答案数量错误：预期{len(rows)}，实际{len(answers)}。")
    ordered = [answers[row["question"]] for row in rows]
    core.save_json(run_root / "combined_generated_answers.json", {"results": ordered})
    core.save_json(run_root / "route_manifest.json", manifest)
    return answers, manifest


def experience_outcomes(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    routes = {item["case_id"]: item for item in manifest["routes"]}
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "applied_questions": 0,
            "wins": 0,
            "ties": 0,
            "losses": 0,
            "large_regressions": 0,
            "score_delta": 0,
            "input_token_delta": 0,
        }
    )
    for record in records:
        route = routes[record["case_id"]]
        delta = int(record["candidate_score"]) - int(record["baseline_score"])
        for experience_id in route["selected_experiences"]:
            value = stats[experience_id]
            value["applied_questions"] += 1
            value["wins"] += delta > 0
            value["ties"] += delta == 0
            value["losses"] += delta < 0
            value["large_regressions"] += delta <= -2
            value["score_delta"] += delta
            value["input_token_delta"] += int(record["candidate_input_tokens"]) - int(record["baseline_input_tokens"])
    for value in stats.values():
        applied = value["applied_questions"]
        value["average_input_token_delta"] = value.pop("input_token_delta") / applied if applied else 0
        if value["large_regressions"] or value["losses"] > value["wins"]:
            value["recommendation"] = "quarantine"
        elif value["wins"] > value["losses"]:
            value["recommendation"] = "retain"
        else:
            value["recommendation"] = "unproven"
    return dict(stats)


def write_round3_report(
    library: dict[str, Any],
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    outcomes: dict[str, Any],
    passed: bool,
) -> None:
    value = paired_eval.pair_metrics(records)
    routed_count = sum(not item["fallback_to_baseline"] for item in manifest["routes"])
    lines = [
        "# 研究内容2：Round 3 结构化经验路由",
        "",
        "本轮不再把全部训练经验压缩成一套全局提示词。Teacher从训练轨迹中生成带适用标签、反例边界和因果证据的经验记录；程序对每道题进行确定性分类，只注入Top-2匹配经验。没有可靠命中的题直接复用标题路由Baseline。61题测试集仍未打开。",
        "",
        "## 开发集总体结果",
        "",
        "| Baseline准确率 | 路由候选准确率 | 胜/平/负 | 净得分 | 严重退步 | 输入Token变化 | 命中经验题数 | 通过门槛 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['large_regressions']} | {value['input_token_change_percent']:+.1f}% | {routed_count}/20 | {'是' if passed else '否'} |",
        "",
        "## 逐经验回归统计",
        "",
        "| 经验 | 修复层级 | 应用题数 | 胜/平/负 | 净得分 | 严重退步 | 建议 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    by_id = {item["experience_id"]: item for item in library["experiences"]}
    for experience_id, stats in sorted(outcomes.items()):
        item = by_id[experience_id]
        lines.append(
            f"| `{experience_id}` | {item['repair_operator']} | {stats['applied_questions']} | {stats['wins']}/{stats['ties']}/{stats['losses']} | {stats['score_delta']:+d} | {stats['large_regressions']} | {stats['recommendation']} |"
        )
    lines.extend(["", "## 自动决策", ""])
    if passed:
        lines.append("路由策略通过与Round 2相同的硬门槛，已冻结，可以单独运行61题测试。冻结的是本轮实际评测过的完整经验库和路由器，不会根据测试结果再次修改。")
    else:
        lines.append("路由策略未通过硬门槛，因此不打开61题测试。逐经验统计仅用于下一轮训练设计，不能在同一开发集上删除规则后直接宣称提升。")
    lines.extend(
        [
            "",
            "## 本轮解决的算法问题",
            "",
            "- Repair阶段直接保留训练轨迹中的因果证据，不再只接收二次压缩后的全局摘要。",
            "- 每条经验都有适用标签和不适用边界，避免一条规则污染所有题目。",
            "- 未命中经验时回退到已经验证有效的标题路由Baseline，控制Token和负迁移。",
            "- 每条经验分别记录胜负和成本，形成可保留、隔离或继续观察的经验状态。",
            "- 开发集仍只负责冻结策略；测试集不会参与经验生成、路由或筛选。",
            "",
        ]
    )
    (ROUND3 / "ROUND3_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_round3() -> None:
    library = build_experience_library()
    answers, manifest = run_routed("dev", library, DEV_RUN)
    records = paired_eval.pair_evaluate(
        "round3_routed_experience",
        "dev",
        answers,
        DEV_RUN / "paired_judgment.json",
    )
    value = paired_eval.pair_metrics(records)
    passed = paired_eval.passes_gate(value)
    outcomes = experience_outcomes(manifest, records)
    core.save_json(ROUND3 / "experience_outcomes.json", outcomes)
    core.save_json(ROUND3 / "gate.json", {"passed": passed, "metrics": value})
    if passed:
        core.save_json(
            ROUND3 / "frozen_policy.json",
            {
                "library_version": library["version"],
                "max_experiences_per_question": MAX_EXPERIENCES_PER_QUESTION,
                "experiences": library["experiences"],
            },
        )
    write_round3_report(library, manifest, records, outcomes, passed)
    core.say(f"[完成] Round 3：{ROUND3 / 'ROUND3_REPORT.md'}")


def run_test61() -> None:
    gate_path = ROUND3 / "gate.json"
    frozen_path = ROUND3 / "frozen_policy.json"
    if not gate_path.exists() or not frozen_path.exists() or not core.load_json(gate_path).get("passed"):
        raise RuntimeError("Round 3路由策略没有通过开发集门槛，拒绝打开测试集。")
    metadata = TEST_RUN / "metadata.json"
    if metadata.exists() and core.load_json(metadata).get("completed"):
        core.say(f"[已完成] Round 3测试集不会重复运行：{TEST_RUN}")
        return
    policy = core.load_json(frozen_path)
    TEST_RUN.mkdir(parents=True, exist_ok=True)
    core.save_json(metadata, {"completed": False, "questions": 61, "library_version": policy["library_version"]})
    answers, manifest = run_routed("test", policy, TEST_RUN / "candidate")
    records = paired_eval.pair_evaluate(
        "round3_test61",
        "test",
        answers,
        TEST_RUN / "paired_judgment.json",
    )
    value = paired_eval.pair_metrics(records)
    routed_count = sum(not item["fallback_to_baseline"] for item in manifest["routes"])
    lines = [
        "# Round 3：结构化经验路由61题独立测试",
        "",
        f"冻结经验库：`{policy['library_version']}`；命中经验的题为{routed_count}/61。",
        "",
        "| Baseline准确率 | 路由候选准确率 | 胜/平/负 | 净得分 | 输入Token变化 | 耗时变化 |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['input_token_change_percent']:+.1f}% | {value['latency_change_percent']:+.1f}% |",
        "",
    ]
    (TEST_RUN / "TEST61_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    core.save_json(metadata, {"completed": True, "questions": 61, "library_version": policy["library_version"]})
    core.say(f"[完成] Round 3独立测试：{TEST_RUN / 'TEST61_REPORT.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic RAG Round 3: trace-grounded routed experience")
    parser.add_argument("command", choices=("learn", "route", "round3", "test"))
    args = parser.parse_args()
    if args.command == "learn":
        build_experience_library()
        core.say(f"[完成] 结构化经验库：{LIBRARY_PATH}")
    elif args.command == "route":
        library = build_experience_library()
        core.save_json(ROUTE_PREVIEW, build_route_manifest("dev", library))
        core.say(f"[完成] 开发集路由预览：{ROUTE_PREVIEW}")
    elif args.command == "round3":
        run_round3()
    else:
        run_test61()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        core.say("\n[已停止] 已完成的Teacher批次、路由答案和Judge评分均保留；重新运行同一命令即可继续。")
        raise SystemExit(130)
    except Exception as exc:
        core.say(f"\n[失败] {exc}")
        raise SystemExit(1)
