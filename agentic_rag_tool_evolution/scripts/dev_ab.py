from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
REPO = WORKSPACE / "ruc-ov-eval-zqy-DeepRead"
HARNESS = REPO / "ov_test" / "run.py"
OLD_EXPERIMENT = WORKSPACE / "agentic_rag_self_learning"

sys.path.insert(0, str(OLD_EXPERIMENT / "scripts"))
sys.path.insert(0, str(HERE.parent))
import run_pilot as legacy  # noqa: E402
import dataset_profiles as profiles  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def latest_blind_run(profile: "profiles.DatasetProfile") -> Path:
    candidates = [
        path
        for path in profile.runs_dir.glob("blind_*")
        if (path / "candidate_tool.py").exists()
        and (path / "candidate.json").exists()
        and (path / "analysis.json").exists()
    ]
    if not candidates:
        raise RuntimeError(f"没有找到已完成的盲重建候选（{profile.runs_dir}）。")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def validate_candidate(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_imports = {"re", "math", "json", "collections", "typing", "dataclasses"}
    forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    public: list[str] = []
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allowed_imports:
                    problems.append(f"forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module not in allowed_imports:
                problems.append(f"forbidden import: {module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
            problems.append(f"forbidden call: {node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"forbidden dunder attribute: {node.attr}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            public.append(node.name)
    if public != ["run"]:
        problems.append(f"public functions must equal ['run']; got {public}")
    if problems:
        raise RuntimeError("候选工具未通过接入前安全复核：" + "; ".join(sorted(set(problems))))


def load_candidate_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("blind_candidate_for_validation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入候选工具。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _results_of(output: Any) -> list[Any]:
    """候选工具的排名结果列表。契约要求 `results` 键，但生成模型常用近义键名，
    逐一兼容（运行时 Student 直接读整个 JSON，键名不影响实际效果，只有门禁关心）。"""
    if not isinstance(output, dict):
        return []
    for key in ("results", "ranked_documents", "ranked", "top_documents", "documents"):
        value = output.get(key)
        if isinstance(value, list):
            return value
    return []


def run_generated_tests(module: Any, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for test in candidate.get("tests") or []:
        expected = str(test.get("expected_property") or "")
        expected_top = str(test.get("expected_top_doc_id") or "").strip()
        if not expected_top:
            for pattern in (
                r"top result is\s+([A-Z][A-Z0-9_-]+)",
                r"([A-Z][A-Z0-9_-]+)\s+is ranked first",
                r"([A-Z][A-Z0-9_-]+)\s+is ranked before",
            ):
                match = re.search(pattern, expected)
                if match:
                    expected_top = match.group(1)
                    break
        error = None
        output: Any = {}
        try:
            output = module.run(
                str(test.get("question") or ""),
                list(test.get("documents") or []),
                int(test.get("top_k") or 5),
            )
            json.dumps(output)  # 必须 JSON 可序列化
        except Exception as exc:  # 工具自身抛错视为测试失败
            error = f"{type(exc).__name__}: {exc}"
        actual_rows = _results_of(output)
        actual = str((actual_rows[0] or {}).get("doc_id") or "") if actual_rows and isinstance(actual_rows[0], dict) else ""
        if expected_top:
            # 排名型断言：严格比对 top1 文档
            passed = bool(actual and actual.upper() == expected_top.upper())
            check = "top_doc"
        else:
            # 行为/属性型断言（如"空结果不得当作证据"）：验证可执行且返回合法 dict
            passed = error is None and isinstance(output, dict)
            check = "execution_only"
        results.append(
            {
                "name": test.get("name"),
                "passed": passed,
                "check": check,
                "expected_top": expected_top or None,
                "actual_top": actual,
                **({"error": error} if error else {}),
            }
        )
    if not results or not all(item["passed"] for item in results):
        raise RuntimeError(f"候选工具自生成测试未全部通过：{results}")
    if not any(item["check"] == "top_doc" for item in results):
        say("[提示] 候选工具的自测全部为行为型断言（无排名型），门禁仅验证了可执行性。")
    return results


def generated_policy(candidate: dict[str, Any]) -> list[str]:
    policy = candidate.get("usage_policy") or {}
    labels = {
        "when_to_call": "When to call the generated tool",
        "how_to_use_output": "How to use its output",
        "fallback": "Fallback",
        "stopping_rule": "Stopping rule",
    }
    return [
        f"{labels[key]}: {policy[key]}"
        for key in labels
        if str(policy.get(key) or "").strip()
    ]


def make_config(
    profile: "profiles.DatasetProfile",
    raw_data: Path,
    output_base: Path,
    max_questions: int,
    *,
    candidate_enabled: bool,
    candidate_path: Path,
    instructions: list[str],
    workers: int = 1,
) -> dict[str, Any]:
    return {
        "project_name": "AgenticRAGGeneratedToolDevAB",
        "dataset_name": profile.dev_dataset_name,
        "adapter": {
            "module": profile.adapter_module,
            "class_name": profile.adapter_class,
        },
        "store": {
            "type": "DeepRead",
            "enable_vector": True,
            "enable_hybrid": False,
            "enable_semantic": False,
            "neighbor_window": "1,-1",
            "max_rounds": 50,
            "use_pymupdf": True,
            "source_header_enabled": True,
            "enable_session_pagination": False,
            "preload_directory_structure": False,
            "enable_document_title_search": False,
            "enable_document_inventory_search": candidate_enabled,
            "document_inventory_tool_path": str(candidate_path),
            "enable_structure_title_search": False,
            "agent_topk_max": 1,
            "pagination_candidate_limit": 1,
            "agent_instructions": instructions,
            "embedding_api_key": "${EMBEDDING_API_KEY}",
            "embedding_base_url": "${EMBEDDING_BASE_URL}",
            "embedding_model": "${EMBEDDING_MODEL_NAME}",
        },
        "execution": {
            "max_workers": workers,
            "ingest_workers": 1,
            "retrieval_topk": 1,
            "max_queries": max_questions,
            "skip_ingestion": True,
        },
        "paths": {
            "raw_data": str(raw_data),
            "doc_output_dir": str(profile.processed_dir),
            "vector_store": str(profile.index_dir),
            "output_dir": str(output_base),
        },
        "llm": {
            "model": "${LLM_MODEL}",
            "temperature": 0,
            "base_url": "${LLM_BASE_URL}",
            "api_key": "${LLM_API_KEY}",
        },
    }


def find_complete_output(stage: Path, expected: int) -> Path | None:
    for output in sorted(stage.glob("output_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        generated = output / "generated_answers.json"
        if not generated.exists():
            continue
        try:
            if len(load_json(generated).get("results", [])) == expected:
                return output
        except Exception:
            continue
    return None


def run_arm(
    label: str,
    run_root: Path,
    rows_file: Path,
    expected: int,
    candidate_path: Path,
    candidate_enabled: bool,
    instructions: list[str],
    env_values: dict[str, str],
    profile: "profiles.DatasetProfile",
    workers: int = 1,
) -> Path:
    stage = run_root / label
    stage.mkdir(parents=True, exist_ok=True)
    completed = find_complete_output(stage, expected)
    if completed:
        say(f"[复用] {label} 已完成：{completed}")
        return completed
    config_path = stage / "config.yaml"
    config = make_config(
        profile,
        rows_file,
        stage / "output",
        expected,
        candidate_enabled=candidate_enabled,
        candidate_path=candidate_path,
        instructions=instructions,
        workers=workers,
    )
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env.update(profile.env_overrides)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env["PYTHONUTF8"] = "1"
    say(f"[Student] {label}：{expected}题，模型={env_values['STUDENT_MODEL']}……")
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "gen", "--skip-ingest"],
        cwd=str(REPO / "ov_test"),
        env=process_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Student运行失败：{label}")
    completed = find_complete_output(stage, expected)
    if completed is None:
        raise RuntimeError(f"Student没有生成完整答案：{label}")
    return completed


def answer_map(output: Path) -> dict[str, dict[str, Any]]:
    rows = load_json(output / "generated_answers.json").get("results", [])
    return {row["question"]: row for row in rows}


def judge_prompt(question: str, gold: str, answer: str) -> str:
    return f'''Score Generated Answer vs Gold Answer (0-4).
The Gold Answer is the complete acceptable answer.
Strictly penalize core factual errors, but do not penalize verbosity or valid extra facts.
4: fully correct; 3: accurate but incomplete; 2: relevant but misses core facts; 1: core factual error; 0: wrong/refusal.

Question: {question}
Gold Answer: {gold}
Generated Answer: {answer}

Respond ONLY with JSON: {{"score": 0, "reasoning": "one sentence"}}'''


def judge(
    label: str,
    rows: list[dict[str, Any]],
    answers: dict[str, dict[str, Any]],
    path: Path,
    env_values: dict[str, str],
    judge_system: str = "You are a strict FinanceBench answer evaluator.",
) -> list[dict[str, Any]]:
    saved: dict[str, dict[str, Any]] = {}
    if path.exists():
        payload = load_json(path)
        if payload.get("judge_model") == env_values["JUDGE_MODEL"]:
            saved = {row["case_id"]: row for row in payload.get("results", [])}
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        case_id = row["case_id"]
        if case_id in saved:
            results.append(saved[case_id])
            continue
        generated = answers[row["question"]]
        student_answer = str((generated.get("llm") or {}).get("final_answer") or "")
        say(f"[Judge:{label}] {index}/{len(rows)}")
        evaluation = legacy.model_json_call(
            env_values["JUDGE_BASE_URL"],
            env_values.get("JUDGE_API_KEY") or env_values["VOLCENGINE_API_KEY"],
            env_values["JUDGE_MODEL"],
            [
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_prompt(row["question"], row["answer"], student_answer)},
            ],
            temperature=0,
            max_tokens=1200,
        )
        score = max(0, min(4, int(evaluation.get("score", 0))))
        results.append(
            {
                "case_id": case_id,
                "question": row["question"],
                "question_type": row.get("question_type"),
                "gold_answer": row["answer"],
                "student_answer": student_answer,
                "score": score,
                "judge_reasoning": str(evaluation.get("reasoning") or ""),
                "input_tokens": int((generated.get("token_usage") or {}).get("total_input_tokens", 0)),
                "output_tokens": int((generated.get("token_usage") or {}).get("llm_output_tokens", 0)),
                "latency_sec": float((generated.get("retrieval") or {}).get("latency_sec", 0)),
                "recall": float((generated.get("metrics") or {}).get("Recall", 0)),
            }
        )
        save_json(path, {"judge_model": env_values["JUDGE_MODEL"], "results": results})
    return results


def metrics(records: list[dict[str, Any]]) -> dict[str, float]:
    count = len(records)
    return {
        "count": count,
        "average_score": sum(row["score"] for row in records) / count,
        "accuracy": sum(row["score"] for row in records) / (4 * count),
        "average_input_tokens": sum(row["input_tokens"] for row in records) / count,
        "average_output_tokens": sum(row["output_tokens"] for row in records) / count,
        "average_latency_sec": sum(row["latency_sec"] for row in records) / count,
        "average_recall": sum(row["recall"] for row in records) / count,
    }


def paired(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    before = {row["case_id"]: row for row in baseline}
    after = {row["case_id"]: row for row in candidate}
    details = []
    for case_id in before:
        details.append(
            {
                "case_id": case_id,
                "question": before[case_id]["question"],
                "baseline_score": before[case_id]["score"],
                "candidate_score": after[case_id]["score"],
                "delta": after[case_id]["score"] - before[case_id]["score"],
            }
        )
    return {
        "wins": sum(row["delta"] > 0 for row in details),
        "ties": sum(row["delta"] == 0 for row in details),
        "losses": sum(row["delta"] < 0 for row in details),
        "net_score": sum(row["delta"] for row in details),
        "details": details,
    }


def write_report(
    path: Path,
    blind_run: Path,
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    test_results: list[dict[str, Any]],
    display_name: str = "FinanceBench",
) -> None:
    b = metrics(baseline)
    c = metrics(candidate)
    comparison = paired(baseline, candidate)
    lines = [
        f"# AI自主生成工具：{display_name} Dev {len(baseline)}严格A/B",
        "",
        "## 实验边界",
        "",
        "- 候选工具仅由固定train题中的原始轨迹生成。",
        f"- 本轮只使用dev {len(baseline)}题；test题保持未触碰。",
        "- Baseline关闭旧标题工具；Candidate只新增AI生成工具及AI生成的使用策略。",
        "- Student、Judge、索引、轮数、top-k和其他检索工具完全相同。",
        f"- 盲重建来源：`{blind_run}`",
        "",
        "## 自动生成单元测试",
        "",
        f"{sum(item['passed'] for item in test_results)}/{len(test_results)} 通过。",
        "",
        "## Dev结果",
        "",
        "| 方案 | 准确率 | 平均分(0-4) | 输入Token/题 | 输出Token/题 | 耗时/题 | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {b['accuracy']:.2%} | {b['average_score']:.3f} | {b['average_input_tokens']:.0f} | {b['average_output_tokens']:.0f} | {b['average_latency_sec']:.1f}s | {b['average_recall']:.2%} |",
        f"| AI生成工具 | {c['accuracy']:.2%} | {c['average_score']:.3f} | {c['average_input_tokens']:.0f} | {c['average_output_tokens']:.0f} | {c['average_latency_sec']:.1f}s | {c['average_recall']:.2%} |",
        "",
        f"成对结果：**{comparison['wins']}胜 / {comparison['ties']}平 / {comparison['losses']}负**，净得分变化 **{comparison['net_score']:+d}**。",
        "",
        "## 逐题变化",
        "",
        "| case_id | Baseline | Candidate | 变化 | 问题 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in sorted(comparison["details"], key=lambda item: item["delta"], reverse=True):
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {row['case_id']} | {row['baseline_score']} | {row['candidate_score']} | {row['delta']:+d} | {question} |"
        )
    lines += [
        "",
        "## 判定规则",
        "",
        "若dev净提升且没有不可接受的大幅退化，则冻结工具与策略并进入test 61；否则只用dev轨迹分析和修复，不能查看test答案。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="financebench", choices=sorted(profiles.PROFILES))
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None,
                        help="答题线程数（默认：financebench=1 对齐历史，其余=4）")
    args = parser.parse_args()

    profile = profiles.get_profile(args.dataset)
    workers = args.workers or profiles.DEFAULT_WORKERS[profile.name]
    max_questions = args.max_questions if args.max_questions is not None else profile.dev_count
    if not 1 <= max_questions <= profile.dev_count:
        raise ValueError(f"max-questions必须在1到{profile.dev_count}之间。")

    required = [HARNESS, profile.index_dir, profile.processed_dir, OLD_EXPERIMENT / ".env"]
    if profile.name != "financebench" and not (profile.splits_dir / "SPLIT_MANIFEST.json").exists():
        raise FileNotFoundError(
            f"缺少划分：请先运行 scripts/prepare_splits.py --dataset {profile.name}"
        )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少实验输入：\n" + "\n".join(missing))

    blind_run = latest_blind_run(profile)
    candidate_path = blind_run / "candidate_tool.py"
    candidate_json = load_json(blind_run / "candidate.json")
    validate_candidate(candidate_path)
    module = load_candidate_module(candidate_path)
    generated_tests = run_generated_tests(module, candidate_json)
    say(f"[候选复核] 静态安全检查通过；自生成测试 {len(generated_tests)}/{len(generated_tests)} 通过。")

    rows = profile.load_split_rows("dev")[:max_questions]
    run_root = blind_run / ("dev_ab" if max_questions == profile.dev_count else f"dev_ab_smoke{max_questions}")
    run_root.mkdir(parents=True, exist_ok=True)
    if max_questions == profile.dev_count:
        rows_file = profile.harness_file("dev")
    else:
        rows_file = run_root / f"dev_input{profile.harness_ext}"
        if not rows_file.exists():
            profile.write_harness_subset(rows, rows_file)

    env_values = legacy.load_experiment_env()
    say(
        f"[严格A/B] {profile.display_name} {len(rows)}题；Student={env_values['STUDENT_MODEL']}；"
        f"Judge={env_values['JUDGE_MODEL']}；旧标题工具=OFF；答题线程={workers}。"
    )
    baseline_output = run_arm(
        "baseline",
        run_root,
        rows_file,
        len(rows),
        candidate_path,
        False,
        [],
        env_values,
        profile,
        workers,
    )
    candidate_output = run_arm(
        "generated_tool",
        run_root,
        rows_file,
        len(rows),
        candidate_path,
        True,
        generated_policy(candidate_json),
        env_values,
        profile,
        workers,
    )
    baseline_judged = judge(
        "baseline",
        rows,
        answer_map(baseline_output),
        run_root / "baseline_judged.json",
        env_values,
        profile.judge_system,
    )
    candidate_judged = judge(
        "generated_tool",
        rows,
        answer_map(candidate_output),
        run_root / "generated_tool_judged.json",
        env_values,
        profile.judge_system,
    )
    report = run_root / "DEV_AB_REPORT.md"
    write_report(report, blind_run, baseline_judged, candidate_judged, generated_tests, profile.display_name)
    comparison = paired(baseline_judged, candidate_judged)
    say(
        f"[完成] dev A/B：{comparison['wins']}胜/{comparison['ties']}平/"
        f"{comparison['losses']}负，净分={comparison['net_score']:+d}"
    )
    say(f"[报告] {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 已完成答案与Judge评分均保留，重新运行会从断点继续。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
