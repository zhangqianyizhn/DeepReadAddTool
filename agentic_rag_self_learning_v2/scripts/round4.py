from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import content2 as core  # noqa: E402
import round2 as paired_eval  # noqa: E402
import round3  # noqa: E402


ROOT = core.ROOT
ROUND3 = ROOT / "runs" / "round3"
ROUND4 = ROOT / "runs" / "round4"
DEV_RUN = ROUND4 / "dev_candidate"
TEST_RUN = ROOT / "runs" / "round4_frozen_test61"
POLICY_VERSION = "round4_trigger_aware_router_v1"

BROAD_TAGS = {"extraction", "temporal", "entity"}
DISCRIMINATIVE_TAGS = {
    "numerical",
    "calculation",
    "trend",
    "comparison",
    "unit",
    "rounding",
    "complete_set",
    "source_scope",
}
STOPWORDS = {
    "about",
    "after",
    "all",
    "also",
    "and",
    "answer",
    "apply",
    "asks",
    "any",
    "are",
    "available",
    "based",
    "before",
    "company",
    "content",
    "data",
    "document",
    "evidence",
    "explicitly",
    "expressed",
    "filing",
    "financial",
    "first",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "most",
    "only",
    "period",
    "question",
    "relevant",
    "report",
    "result",
    "requested",
    "search",
    "source",
    "sources",
    "specific",
    "specified",
    "statement",
    "that",
    "the",
    "their",
    "then",
    "this",
    "when",
    "where",
    "which",
    "with",
    "year",
}


def stem(token: str) -> str:
    aliases = {
        "percentage": "percent",
        "percentages": "percent",
        "percents": "percent",
    }
    if token in aliases:
        return aliases[token]
    for suffix in ("ingly", "ments", "ment", "ation", "ities", "ingly", "ing", "ies", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    return token


def content_tokens(text: str) -> set[str]:
    tokens = {
        stem(token)
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", str(text).lower())
        if token not in STOPWORDS
    }
    return {token for token in tokens if len(token) >= 3 and token not in STOPWORDS}


def trigger_overlap(row: dict[str, Any], experience: dict[str, Any]) -> set[str]:
    question_tokens = content_tokens(str(row.get("question") or ""))
    trigger_tokens = content_tokens(
        " ".join(
            [
                str(experience.get("trigger_description") or ""),
                str(experience.get("student_instruction") or ""),
            ]
        )
    )
    return question_tokens & trigger_tokens


def boundary_overlap(row: dict[str, Any], experience: dict[str, Any]) -> set[str]:
    question_tokens = content_tokens(str(row.get("question") or ""))
    boundary_tokens = content_tokens(str(experience.get("do_not_apply_when") or ""))
    return question_tokens & boundary_tokens


def load_adaptive_policy() -> dict[str, Any]:
    library_path = ROUND3 / "experience_library.json"
    outcomes_path = ROUND3 / "experience_outcomes.json"
    if not library_path.exists() or not outcomes_path.exists():
        raise RuntimeError("Round 3尚未完成，无法构造Round 4自适应策略。")
    library = core.load_json(library_path)
    outcomes = core.load_json(outcomes_path)
    active: list[dict[str, Any]] = []
    quarantined: list[str] = []
    for item in library.get("experiences", []):
        copied = dict(item)
        outcome = outcomes.get(item["experience_id"])
        recommendation = str((outcome or {}).get("recommendation") or "candidate")
        copied["round3_recommendation"] = recommendation
        if recommendation == "quarantine":
            quarantined.append(item["experience_id"])
            continue
        active.append(copied)
    if not active:
        raise RuntimeError("Round 3后没有可用经验。")
    return {
        "version": POLICY_VERSION,
        "source_library_version": library.get("version"),
        "quarantined_experiences": quarantined,
        "max_experiences_per_question": round3.MAX_EXPERIENCES_PER_QUESTION,
        "experiences": active,
    }


def select_experiences_v2(
    row: dict[str, Any], experiences: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], int]]:
    tags = round3.classify_question(row)
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
        # Execute the Teacher's negative boundary in the router instead of
        # relying on the Student to interpret it as a soft instruction.
        if boundary_overlap(row, item):
            continue

        matched_tags = (required | any_matches) & tags
        discriminative = matched_tags & DISCRIMINATIVE_TAGS
        if not discriminative:
            continue

        overlap = trigger_overlap(row, item)
        operator = str(item.get("repair_operator") or "")
        # Answer formatting guards can be safely routed by precise calculation,
        # trend, unit, or rounding tags. Retrieval/workflow repairs additionally
        # require lexical evidence that the narrow trigger is present.
        if operator != "ANSWER_GUARD" and not overlap:
            continue

        score = (
            5 * len(required & DISCRIMINATIVE_TAGS)
            + 3 * len(any_matches & DISCRIMINATIVE_TAGS)
            + 2 * min(3, len(overlap))
            + round3.CONFIDENCE_SCORE.get(str(item.get("confidence")), 1)
            + (2 if item.get("round3_recommendation") == "retain" else 0)
            - len(matched_tags & BROAD_TAGS)
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
        if len(selected) == round3.MAX_EXPERIENCES_PER_QUESTION:
            break
    return selected


def pair_evaluate_dev(
    candidate_answers: dict[str, dict[str, Any]], output_path: Path
) -> list[dict[str, Any]]:
    """Judge changed answers only; exact Baseline fallbacks reuse Round 3 scores."""
    env = core.legacy.load_experiment_env()
    rows = core.load_jsonl(core.SPLIT_DIR / "dev.jsonl")
    baseline_answers = core.baseline_answers("dev")
    saved = paired_eval.load_saved_pairs(output_path, env["JUDGE_MODEL"])
    round3_pairs_path = ROUND3 / "dev_candidate" / "paired_judgment.json"
    round3_payload = core.load_json(round3_pairs_path)
    if str(round3_payload.get("judge_model") or "") != env["JUDGE_MODEL"]:
        raise RuntimeError("Judge模型已变化，不能复用Round 3的Baseline评分。")
    round3_pairs = {
        item["case_id"]: item
        for item in round3_payload.get("results", [])
    }
    results: list[dict[str, Any]] = []
    changed_index = 0
    changed_total = sum(
        baseline_answers[row["question"]].get("llm", {}).get("final_answer", "")
        != candidate_answers[row["question"]].get("llm", {}).get("final_answer", "")
        for row in rows
    )
    for row in rows:
        case_id = row["financebench_id"]
        if case_id in saved:
            results.append(saved[case_id])
            continue
        before = baseline_answers[row["question"]]
        after = candidate_answers[row["question"]]
        baseline_text = before.get("llm", {}).get("final_answer", "")
        candidate_text = after.get("llm", {}).get("final_answer", "")
        if baseline_text == candidate_text:
            reference = round3_pairs.get(case_id)
            if reference is None:
                raise RuntimeError(f"Round 3缺少Baseline参考评分：{case_id}")
            score = int(reference["baseline_score"])
            judged = {
                "baseline_score": score,
                "candidate_score": score,
                "relation": "tie",
                "rounding_equivalent": True,
                "reasoning": "Candidate exactly reuses the frozen title-routing Baseline answer.",
            }
        else:
            changed_index += 1
            core.say(f"[Round4成对Judge:changed] {changed_index}/{changed_total}")
            judged = paired_eval.call_pair_judge(
                env, row["question"], row["answer"], baseline_text, candidate_text
            )
        record = {
            "case_id": case_id,
            "split": "dev",
            "question_type": row.get("question_type"),
            "question": row["question"],
            "gold_answer": row["answer"],
            "baseline_answer": baseline_text,
            "candidate_answer": candidate_text,
            "baseline_input_tokens": int(before.get("token_usage", {}).get("total_input_tokens", 0)),
            "candidate_input_tokens": int(after.get("token_usage", {}).get("total_input_tokens", 0)),
            "baseline_output_tokens": int(before.get("token_usage", {}).get("llm_output_tokens", 0)),
            "candidate_output_tokens": int(after.get("token_usage", {}).get("llm_output_tokens", 0)),
            "baseline_latency_sec": float(before.get("retrieval", {}).get("latency_sec", 0)),
            "candidate_latency_sec": float(after.get("retrieval", {}).get("latency_sec", 0)),
            **judged,
        }
        results.append(record)
        core.save_json(output_path, {"judge_model": env["JUDGE_MODEL"], "results": results})
    return results


def write_report(
    policy: dict[str, Any],
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    outcomes: dict[str, Any],
    passed: bool,
) -> None:
    value = paired_eval.pair_metrics(records)
    routed_count = sum(not item["fallback_to_baseline"] for item in manifest["routes"])
    lines = [
        "# 研究内容2：Round 4 触发条件感知路由",
        "",
        "Round 4是开发集上的第二次算法迭代。它复用Round 3训练轨迹生成的经验库，自动隔离Round 3中净负收益或出现严重回归的经验；宽泛标签不能单独触发检索，非ANSWER_GUARD经验还必须与具体trigger description存在词项重合。61题测试集仍未打开。",
        "",
        f"已隔离经验：{', '.join(f'`{item}`' for item in policy['quarantined_experiences']) or '无'}。",
        "",
        "## 开发集总体结果",
        "",
        "| Baseline准确率 | 候选准确率 | 胜/平/负 | 净得分 | 严重退步 | 输入Token变化 | 命中经验题数 | 通过门槛 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['large_regressions']} | {value['input_token_change_percent']:+.1f}% | {routed_count}/20 | {'是' if passed else '否'} |",
        "",
        "## 逐经验结果",
        "",
        "| 经验 | 应用题数 | 胜/平/负 | 净得分 | 严重退步 | 建议 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for experience_id, stats in sorted(outcomes.items()):
        lines.append(
            f"| `{experience_id}` | {stats['applied_questions']} | {stats['wins']}/{stats['ties']}/{stats['losses']} | {stats['score_delta']:+d} | {stats['large_regressions']} | {stats['recommendation']} |"
        )
    lines.extend(["", "## 自动决策", ""])
    if passed:
        lines.append("完整触发条件感知策略通过开发集硬门槛，已冻结；可以运行一次61题独立测试。")
    else:
        lines.append("策略仍未通过门槛，因此继续拒绝打开61题测试集。")
    lines.extend(
        [
            "",
            "注意：Round 4是在查看Round 3开发集结果后进行的迭代，不能把Round 4开发集分数当作无偏测试结论。最终泛化能力只能由尚未打开的61题测试集判断。",
            "",
        ]
    )
    (ROUND4 / "ROUND4_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_round4() -> None:
    policy = load_adaptive_policy()
    ROUND4.mkdir(parents=True, exist_ok=True)
    core.save_json(ROUND4 / "adaptive_policy.json", policy)
    answers, manifest = round3.run_routed(
        "dev", policy, DEV_RUN, selector=select_experiences_v2
    )
    records = pair_evaluate_dev(answers, DEV_RUN / "paired_judgment.json")
    value = paired_eval.pair_metrics(records)
    passed = paired_eval.passes_gate(value)
    outcomes = round3.experience_outcomes(manifest, records)
    core.save_json(ROUND4 / "experience_outcomes.json", outcomes)
    core.save_json(ROUND4 / "gate.json", {"passed": passed, "metrics": value})
    if passed:
        core.save_json(ROUND4 / "frozen_policy.json", policy)
    write_report(policy, manifest, records, outcomes, passed)
    core.say(f"[完成] Round 4：{ROUND4 / 'ROUND4_REPORT.md'}")


def run_test61() -> None:
    gate_path = ROUND4 / "gate.json"
    frozen_path = ROUND4 / "frozen_policy.json"
    if not gate_path.exists() or not frozen_path.exists() or not core.load_json(gate_path).get("passed"):
        raise RuntimeError("Round 4策略没有通过开发集门槛，拒绝打开测试集。")
    metadata = TEST_RUN / "metadata.json"
    if metadata.exists() and core.load_json(metadata).get("completed"):
        core.say(f"[已完成] Round 4测试集不会重复运行：{TEST_RUN}")
        return
    policy = core.load_json(frozen_path)
    TEST_RUN.mkdir(parents=True, exist_ok=True)
    core.save_json(metadata, {"completed": False, "questions": 61, "policy_version": policy["version"]})
    answers, manifest = round3.run_routed(
        "test", policy, TEST_RUN / "candidate", selector=select_experiences_v2
    )
    records = paired_eval.pair_evaluate(
        "round4_test61",
        "test",
        answers,
        TEST_RUN / "paired_judgment.json",
    )
    value = paired_eval.pair_metrics(records)
    routed_count = sum(not item["fallback_to_baseline"] for item in manifest["routes"])
    lines = [
        "# Round 4：61题独立测试",
        "",
        f"冻结策略：`{policy['version']}`；命中经验题数：{routed_count}/61。",
        "",
        "| Baseline准确率 | 候选准确率 | 胜/平/负 | 净得分 | 输入Token变化 | 耗时变化 |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['input_token_change_percent']:+.1f}% | {value['latency_change_percent']:+.1f}% |",
        "",
    ]
    (TEST_RUN / "TEST61_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    core.save_json(metadata, {"completed": True, "questions": 61, "policy_version": policy["version"]})
    core.say(f"[完成] Round 4独立测试：{TEST_RUN / 'TEST61_REPORT.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic RAG Round 4 trigger-aware experience routing")
    parser.add_argument("command", choices=("route", "round4", "test"))
    args = parser.parse_args()
    if args.command == "route":
        policy = load_adaptive_policy()
        ROUND4.mkdir(parents=True, exist_ok=True)
        core.save_json(
            ROUND4 / "route_preview_dev.json",
            round3.build_route_manifest("dev", policy, selector=select_experiences_v2),
        )
        core.say(f"[完成] Round 4路由预览：{ROUND4 / 'route_preview_dev.json'}")
    elif args.command == "round4":
        run_round4()
    else:
        run_test61()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        core.say("\n[已停止] 已完成答案和Judge评分均保留；重新运行同一命令即可继续。")
        raise SystemExit(130)
    except Exception as exc:
        core.say(f"\n[失败] {exc}")
        raise SystemExit(1)
