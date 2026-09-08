from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import content2 as core  # noqa: E402


ROOT = core.ROOT
ROUND1 = core.RUN_DIR
ROUND2 = ROOT / "runs" / "round2"
ROUND1_ADJUDICATION = ROUND2 / "round1_adjudication"
ROUND2_DEV = ROUND2 / "dev_candidates"
ROUND2_TEST = ROOT / "runs" / "round2_frozen_test61"
ROUND1_SKILLS = ("r1_minimal_repair", "r1_retrieval_recovery", "r1_typed_reasoning")
ROUND2_STRATEGIES = ("answer_guard", "conditional_recovery")


def pair_prompt(question: str, gold: str, baseline: str, candidate: str) -> str:
    return f'''Evaluate two answers to the same FinanceBench question in one paired judgment.

Scoring rubric (0–4):
4: Fully captures the gold answer with no core factual error.
3: Correct but slightly incomplete or less clearly formatted.
2: Relevant but misses a core fact, or has a minor secondary factual error.
1: Contains a core factual error.
0: Wrong, unsupported, or refuses despite an available answer.

Numerical-equivalence rule:
- Treat mathematically equivalent unit conversions and ordinary rounding as the same fact.
- If the gold is a whole number of USD millions, a decimal value that conventionally rounds to that
  whole number is numerically correct unless the question explicitly requests finer precision.
- Do not turn a harmless display-precision difference into a core factual error.
- Still penalize wrong sign, period, unit, formula, or materially different magnitude.

Judge each answer independently against the gold, then compare them. Do not prefer an answer merely
because it is longer.

Question: {question}
Gold answer: {gold}

Baseline answer:
{baseline}

Candidate answer:
{candidate}

Return JSON only:
{{"baseline_score": 0, "candidate_score": 0, "relation": "baseline_better|tie|candidate_better", "rounding_equivalent": false, "reasoning": "one concise explanation"}}'''


def call_pair_judge(
    env: dict[str, str], question: str, gold: str, baseline: str, candidate: str
) -> dict[str, Any]:
    result = core.legacy.model_json_call(
        env["JUDGE_BASE_URL"],
        env.get("JUDGE_API_KEY") or env["VOLCENGINE_API_KEY"],
        env["JUDGE_MODEL"],
        [
            {
                "role": "system",
                "content": "You are a strict paired financial-QA evaluator. Apply the numerical-equivalence rule consistently.",
            },
            {"role": "user", "content": pair_prompt(question, gold, baseline, candidate)},
        ],
        temperature=0,
        max_tokens=2048,
    )
    baseline_score = max(0, min(4, int(result.get("baseline_score", 0))))
    candidate_score = max(0, min(4, int(result.get("candidate_score", 0))))
    relation = "tie"
    if candidate_score > baseline_score:
        relation = "candidate_better"
    elif candidate_score < baseline_score:
        relation = "baseline_better"
    return {
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "relation": relation,
        "rounding_equivalent": bool(result.get("rounding_equivalent", False)),
        "reasoning": str(result.get("reasoning", "")),
    }


def load_saved_pairs(path: Path, judge_model: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    saved = core.load_json(path)
    saved_model = str(saved.get("judge_model") or "")
    if saved_model and saved_model != judge_model:
        backup = path.with_name(path.stem + f".backup_{re.sub(r'[^A-Za-z0-9_.-]', '_', saved_model)}.json")
        if backup.exists():
            backup = path.with_name(path.stem + ".backup_previous.json")
        path.replace(backup)
        core.say(f"[成对Judge] 模型变化，旧结果已备份：{backup.name}")
        return {}
    return {item["case_id"]: item for item in saved.get("results", [])}


def round1_adjudicate() -> dict[str, Any]:
    core.prepare()
    if not (ROUND1 / "comparison.json").exists():
        raise RuntimeError("Round 1尚未完成。")
    env = core.legacy.load_experiment_env()
    baseline = {
        item["case_id"]: item
        for item in core.load_json(ROUND1 / "baseline_dev_rejudged.json").get("results", [])
    }
    if len(baseline) != 20:
        raise RuntimeError("Round 1 Baseline评分不完整。")
    ROUND1_ADJUDICATION.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"judge_model": env["JUDGE_MODEL"], "skills": {}}

    for skill_id in ROUND1_SKILLS:
        candidate_path = ROUND1 / "dev_candidates" / skill_id / "judged_results.json"
        candidate = {item["case_id"]: item for item in core.load_json(candidate_path).get("results", [])}
        output_path = ROUND1_ADJUDICATION / f"{skill_id}.json"
        saved = load_saved_pairs(output_path, env["JUDGE_MODEL"])
        results: list[dict[str, Any]] = []
        disagreements = [case_id for case_id in baseline if baseline[case_id]["score"] != candidate[case_id]["score"]]
        for index, case_id in enumerate(disagreements, start=1):
            if case_id in saved:
                results.append(saved[case_id])
                continue
            before = baseline[case_id]
            after = candidate[case_id]
            core.say(f"[Round1成对复核:{skill_id}] {index}/{len(disagreements)}")
            judged = call_pair_judge(
                env,
                before["question"],
                before["gold_answer"],
                before["student_answer"],
                after["student_answer"],
            )
            record = {
                "case_id": case_id,
                "question_type": before.get("question_type"),
                "question": before["question"],
                "gold_answer": before["gold_answer"],
                "baseline_answer": before["student_answer"],
                "candidate_answer": after["student_answer"],
                "original_baseline_score": before["score"],
                "original_candidate_score": after["score"],
                **judged,
            }
            results.append(record)
            core.save_json(output_path, {"judge_model": env["JUDGE_MODEL"], "results": results})

        wins = sum(item["relation"] == "candidate_better" for item in results)
        losses = sum(item["relation"] == "baseline_better" for item in results)
        ties = 20 - wins - losses
        summary["skills"][skill_id] = {
            "adjudicated_disagreements": len(results),
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "rounding_equivalent_cases": [item["case_id"] for item in results if item["rounding_equivalent"]],
            "true_regressions": [
                {
                    "case_id": item["case_id"],
                    "question_type": item.get("question_type"),
                    "question": item["question"],
                    "reasoning": item["reasoning"],
                }
                for item in results
                if item["relation"] == "baseline_better"
            ],
        }
    core.save_json(ROUND1_ADJUDICATION / "summary.json", summary)
    return summary


def normalize_round2_skills(result: dict[str, Any]) -> list[dict[str, Any]]:
    skills = result.get("skills") or result.get("candidates")
    if isinstance(skills, list):
        return skills
    normalized: list[dict[str, Any]] = []
    for strategy in ROUND2_STRATEGIES:
        value = result.get(strategy)
        if isinstance(value, str):
            value = {
                "instructions": [
                    part.strip()
                    for part in re.split(r"(?:^|\n)\s*\d+[.)]\s*", value)
                    if part.strip()
                ]
            }
        elif isinstance(value, list):
            value = {"instructions": value}
        if isinstance(value, dict):
            normalized.append(
                {
                    "skill_id": f"r2_{strategy}",
                    "strategy": strategy,
                    "instructions": value.get("instructions", []),
                    "expected_behavior": value.get("expected_behavior", "Apply conservative conditional guards."),
                    "cost_risk": value.get("cost_risk", "Low conditional overhead."),
                    "regression_risk": value.get("regression_risk", "May add verification steps."),
                }
            )
    result["skills"] = normalized
    return normalized


def generate_round2_skills() -> dict[str, Any]:
    summary = round1_adjudicate()
    skills_path = ROUND2 / "candidate_skills.json"
    if skills_path.exists():
        core.say("[Round2 Repair] 复用已生成的两套skills。")
        return core.load_json(skills_path)

    env = core.legacy.load_experiment_env()
    round1_skills = core.load_json(ROUND1 / "candidate_skills.json")
    comparison = core.load_json(ROUND1 / "comparison.json")
    detailed_feedback: dict[str, Any] = {}
    for skill_id in ROUND1_SKILLS:
        path = ROUND1_ADJUDICATION / f"{skill_id}.json"
        detailed_feedback[skill_id] = core.load_json(path).get("results", []) if path.exists() else []
    payload = {
        "round1_skill_bundles": round1_skills.get("skills", []),
        "round1_measured_metrics": comparison,
        "paired_adjudication_summary": summary,
        "paired_adjudication_details": detailed_feedback,
        "required_round2_strategies": list(ROUND2_STRATEGIES),
    }
    prompt = (ROOT / "prompts" / "round2_repairer.md").read_text(encoding="utf-8")
    core.say("[Round2 Repair] 根据真实回归和成本反馈生成两套保守skills……")
    result = core.model_call(env, "teacher", prompt, payload, 8192)
    skills = normalize_round2_skills(result)
    if len(skills) != 2 or {item.get("strategy") for item in skills} != set(ROUND2_STRATEGIES):
        core.save_json(ROUND2 / "invalid_candidate_skills.json", result)
        raise RuntimeError("Round2 Repair Agent未返回两套规定的skills。")
    for skill in skills:
        skill["skill_id"] = f"r2_{skill['strategy']}"
        instructions = skill.get("instructions")
        if not isinstance(instructions, list) or not (3 <= len(instructions) <= 6):
            raise RuntimeError(f"{skill['skill_id']} 必须包含3–6条instructions。")
        if not all(isinstance(item, str) and item.strip() for item in instructions):
            raise RuntimeError(f"{skill['skill_id']} instructions格式不正确。")
        if sum(len(item) for item in instructions) > 4500:
            raise RuntimeError(f"{skill['skill_id']} 超过长度限制。")

    companies = {
        str(row.get("company") or "").strip()
        for row in core.load_jsonl(core.SOURCE_JSONL)
        if len(str(row.get("company") or "").strip()) >= 3
    }
    student_text = "\n".join(
        instruction for skill in skills for instruction in skill["instructions"]
    )
    # Case-sensitive whole-name matching catches copied proper nouns while avoiding
    # false positives for ordinary words that are also company names (for example,
    # "target" or "block" used as retrieval terminology).
    leaked = sorted(
        name
        for name in companies
        if name and re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", student_text)
    )
    if leaked or "financebench_id" in student_text.lower():
        core.save_json(ROUND2 / "invalid_candidate_skills.json", result)
        raise RuntimeError("Round2 skills包含疑似个案泄漏，已拒绝：" + ", ".join(leaked[:5] or ["financebench_id"]))
    core.save_json(skills_path, result)
    return result


def pair_evaluate(
    label: str,
    split: str,
    candidate_answers: dict[str, dict[str, Any]],
    output_path: Path,
) -> list[dict[str, Any]]:
    env = core.legacy.load_experiment_env()
    rows = core.load_jsonl(core.SPLIT_DIR / f"{split}.jsonl")
    baseline_answers = core.baseline_answers(split)
    saved = load_saved_pairs(output_path, env["JUDGE_MODEL"])
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        case_id = row["financebench_id"]
        if case_id in saved:
            results.append(saved[case_id])
            continue
        before = baseline_answers[row["question"]]
        after = candidate_answers[row["question"]]
        baseline_text = before.get("llm", {}).get("final_answer", "")
        candidate_text = after.get("llm", {}).get("final_answer", "")
        core.say(f"[成对Judge:{label}] {index}/{len(rows)}")
        judged = call_pair_judge(env, row["question"], row["answer"], baseline_text, candidate_text)
        record = {
            "case_id": case_id,
            "split": split,
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


def pair_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(records)
    wins = sum(item["relation"] == "candidate_better" for item in records)
    losses = sum(item["relation"] == "baseline_better" for item in records)
    baseline_score = sum(item["baseline_score"] for item in records)
    candidate_score = sum(item["candidate_score"] for item in records)
    baseline_tokens = sum(item["baseline_input_tokens"] for item in records) / count
    candidate_tokens = sum(item["candidate_input_tokens"] for item in records) / count
    baseline_latency = sum(item["baseline_latency_sec"] for item in records) / count
    candidate_latency = sum(item["candidate_latency_sec"] for item in records) / count
    return {
        "count": count,
        "baseline_accuracy": baseline_score / (4 * count),
        "candidate_accuracy": candidate_score / (4 * count),
        "score_delta": candidate_score - baseline_score,
        "wins": wins,
        "ties": count - wins - losses,
        "losses": losses,
        "large_regressions": sum(item["candidate_score"] - item["baseline_score"] <= -2 for item in records),
        "baseline_input_tokens": baseline_tokens,
        "candidate_input_tokens": candidate_tokens,
        "input_token_change_percent": (candidate_tokens / baseline_tokens - 1) * 100 if baseline_tokens else 0,
        "baseline_latency_sec": baseline_latency,
        "candidate_latency_sec": candidate_latency,
        "latency_change_percent": (candidate_latency / baseline_latency - 1) * 100 if baseline_latency else 0,
    }


def passes_gate(value: dict[str, Any]) -> bool:
    return (
        value["candidate_accuracy"] >= value["baseline_accuracy"]
        and value["wins"] > value["losses"]
        and value["large_regressions"] == 0
        and value["candidate_input_tokens"] <= value["baseline_input_tokens"] * 1.10
    )


def write_round2_report(
    skills: list[dict[str, Any]],
    evaluated: list[tuple[dict[str, Any], list[dict[str, Any]], Path]],
    selected: dict[str, Any] | None,
) -> None:
    lines = [
        "# 研究内容2：Round 2 开发集结果",
        "",
        "Round 2 使用成对Judge：每次调用同时看到Baseline与候选，并明确接受数学等价的单位换算和常规舍入。61题测试集仍未打开。",
        "",
        "| 候选 | Baseline准确率 | 候选准确率 | 胜/平/负 | 净得分 | 严重退步 | 输入Token变化 | 耗时变化 | 通过门槛 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    comparison: dict[str, Any] = {"candidates": {}, "selected": selected.get("skill_id") if selected else "none"}
    for skill, records, output in evaluated:
        value = pair_metrics(records)
        passed = passes_gate(value)
        comparison["candidates"][skill["skill_id"]] = {"metrics": value, "passed": passed, "output": str(output)}
        lines.append(
            f"| {skill['skill_id']} | {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['large_regressions']} | {value['input_token_change_percent']:+.1f}% | {value['latency_change_percent']:+.1f}% | {'是' if passed else '否'} |"
        )
    lines.extend(["", "## 自动决策", ""])
    if selected:
        lines.extend([
            f"冻结候选：`{selected['skill_id']}`。它同时满足准确率不下降、胜题多于负题、无严重退步、输入Token不超过Baseline 110%的四项门槛。",
            "",
            "冻结skills：",
            "",
            *[f"- {instruction}" for instruction in selected["instructions"]],
            "",
            "可以进入61题独立测试，但测试命令不会被Round 2自动触发。",
        ])
    else:
        lines.append("没有候选通过全部门槛。本轮停止，不运行61题测试；这本身是有效的负结果。")
    lines.append("")
    core.save_json(ROUND2 / "comparison.json", comparison)
    (ROUND2 / "ROUND2_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_round2() -> None:
    generated = generate_round2_skills()
    skills = generated["skills"]
    evaluated: list[tuple[dict[str, Any], list[dict[str, Any]], Path]] = []
    for skill in skills:
        output = core.run_student("dev", skill, ROUND2_DEV)
        judged = pair_evaluate(
            skill["skill_id"],
            "dev",
            core.generated_answers(output),
            ROUND2_DEV / skill["skill_id"] / "paired_judgment.json",
        )
        evaluated.append((skill, judged, output))

    eligible = [(skill, records, output) for skill, records, output in evaluated if passes_gate(pair_metrics(records))]
    selected: dict[str, Any] | None = None
    if eligible:
        best = max(
            eligible,
            key=lambda item: (
                pair_metrics(item[1])["score_delta"],
                pair_metrics(item[1])["wins"] - pair_metrics(item[1])["losses"],
                -pair_metrics(item[1])["candidate_input_tokens"],
                -pair_metrics(item[1])["candidate_latency_sec"],
            ),
        )
        selected = best[0]
        core.save_json(ROUND2 / "frozen_skill.json", selected)
    else:
        # A stale freeze marker must never unlock the held-out test after a later
        # re-evaluation fails the gate.
        frozen_path = ROUND2 / "frozen_skill.json"
        if frozen_path.exists():
            frozen_path.unlink()
    write_round2_report(skills, evaluated, selected)
    core.say(f"[完成] Round 2：{ROUND2 / 'ROUND2_REPORT.md'}")


def run_test61() -> None:
    frozen = ROUND2 / "frozen_skill.json"
    if not frozen.exists():
        raise RuntimeError("Round 2没有候选通过门槛，拒绝打开测试集。")
    skill = core.load_json(frozen)
    ROUND2_TEST.mkdir(parents=True, exist_ok=True)
    metadata = ROUND2_TEST / "metadata.json"
    if metadata.exists() and core.load_json(metadata).get("completed"):
        core.say(f"[已完成] Round 2测试集不会重复运行：{ROUND2_TEST}")
        return
    core.save_json(metadata, {"completed": False, "questions": 61, "skill_id": skill["skill_id"]})
    output = core.run_student("test", skill, ROUND2_TEST / "candidate")
    records = pair_evaluate(
        "round2_test61",
        "test",
        core.generated_answers(output),
        ROUND2_TEST / "paired_judgment.json",
    )
    value = pair_metrics(records)
    lines = [
        "# Round 2：61题独立测试",
        "",
        f"冻结技能：`{skill['skill_id']}`。",
        "",
        "| Baseline准确率 | 候选准确率 | 胜/平/负 | 净得分 | 输入Token变化 | 耗时变化 |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {value['baseline_accuracy']:.2%} | {value['candidate_accuracy']:.2%} | {value['wins']}/{value['ties']}/{value['losses']} | {value['score_delta']:+d} | {value['input_token_change_percent']:+.1f}% | {value['latency_change_percent']:+.1f}% |",
        "",
    ]
    (ROUND2_TEST / "TEST61_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    core.save_json(metadata, {"completed": True, "questions": 61, "skill_id": skill["skill_id"]})
    core.say(f"[完成] Round 2独立测试：{ROUND2_TEST / 'TEST61_REPORT.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic RAG self-learning Round 2")
    parser.add_argument("command", choices=("adjudicate", "learn", "round2", "test"))
    args = parser.parse_args()
    if args.command == "adjudicate":
        round1_adjudicate()
        core.say(f"[完成] Round 1成对复核：{ROUND1_ADJUDICATION / 'summary.json'}")
    elif args.command == "learn":
        generate_round2_skills()
        core.say(f"[完成] Round 2 skills：{ROUND2 / 'candidate_skills.json'}")
    elif args.command == "round2":
        run_round2()
    else:
        run_test61()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        core.say("\n[已停止] 已完成的成对评分、Teacher结果和Student答案均保留；重新运行同一命令即可继续。")
        raise SystemExit(130)
    except Exception as exc:
        core.say(f"\n[失败] {exc}")
        raise SystemExit(1)
