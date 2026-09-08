from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from openai import OpenAI


PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = PROJECT_DIR.parent
REPO_DIR = WORKSPACE_DIR / "ruc-ov-eval-zqy-DeepRead"
HARNESS = REPO_DIR / "ov_test" / "run.py"
SOURCE_ROOT = WORKSPACE_DIR / "Data" / "FinanceBench"
SOURCE_JSONL = SOURCE_ROOT / "data" / "financebench_open_source.jsonl"
SOURCE_MARKDOWN = SOURCE_ROOT / "markdown"
PILOT_ROOT = PROJECT_DIR / "data" / "generated" / "pilot20"
PILOT_JSONL = PILOT_ROOT / "data" / "financebench_open_source.jsonl"
PILOT_MARKDOWN = PILOT_ROOT / "markdown"
PILOT_PDFS = PILOT_ROOT / "pdfs"
PILOT_INDEX = PILOT_ROOT / "DeepRead" / "store_index"
PILOT_PROCESSED = PILOT_ROOT / "DeepRead" / "processed_docs"
PILOT_MANIFEST = PILOT_ROOT / "pilot_manifest.json"
ENV_FILE = PROJECT_DIR / ".env"
RUNS_DIR = PROJECT_DIR / "runs"
SEED = 20260810


def say(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def expand_env(raw: dict[str, str | None]) -> dict[str, str]:
    values = {key: value or "" for key, value in raw.items()}
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    for _ in range(10):
        changed = False
        for key, value in list(values.items()):
            rendered = pattern.sub(lambda match: values.get(match.group(1), os.getenv(match.group(1), "")), value)
            if rendered != value:
                values[key] = rendered
                changed = True
        if not changed:
            break
    return values


def load_experiment_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise RuntimeError(f"缺少配置文件：{ENV_FILE}")
    values = expand_env(dotenv_values(ENV_FILE))
    required = [
        "VOLCENGINE_API_KEY",
        "STUDENT_MODEL",
        "TEACHER_MODEL",
        "JUDGE_MODEL",
        "STUDENT_BASE_URL",
        "TEACHER_BASE_URL",
        "JUDGE_BASE_URL",
        "EMBEDDING_MODEL_NAME",
    ]
    missing = [key for key in required if not values.get(key)]
    placeholders = [
        key for key in required
        if any(marker in values.get(key, "").upper() for marker in ("PASTE_", "FILL_", "YOUR_", "这里", "你的"))
    ]
    if missing or placeholders:
        fields = sorted(set(missing + placeholders))
        raise RuntimeError(".env 仍有未填写字段：" + ", ".join(fields))
    if len(values["VOLCENGINE_API_KEY"].strip()) < 12:
        raise RuntimeError("VOLCENGINE_API_KEY 看起来过短，请检查 .env。")
    return values


def validate_layout() -> None:
    required = [HARNESS, SOURCE_JSONL, SOURCE_MARKDOWN, ENV_FILE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("缺少运行所需文件：\n" + "\n".join(missing))
    if SOURCE_ROOT.resolve() == PILOT_ROOT.resolve() or SOURCE_ROOT in PILOT_ROOT.parents:
        raise RuntimeError("安全检查失败：实验输出不能位于原始 Data/FinanceBench 内。")


def prepare_pilot() -> list[dict[str, Any]]:
    all_rows = load_jsonl(SOURCE_JSONL)
    if len(all_rows) != 141:
        raise RuntimeError(f"FinanceBench 应为141题，实际读到 {len(all_rows)} 题。")

    rng = random.Random(SEED)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        by_type[str(row.get("question_type") or "unknown")].append(row)
    for rows in by_type.values():
        rng.shuffle(rows)

    selected: list[dict[str, Any]] = []
    used_docs: set[str] = set()
    types = sorted(by_type)
    target_by_type = {name: 20 // len(types) for name in types}
    for name in types[: 20 % len(types)]:
        target_by_type[name] += 1

    for question_type in types:
        for row in by_type[question_type]:
            doc_name = row["doc_name"]
            if doc_name in used_docs:
                continue
            selected.append(row)
            used_docs.add(doc_name)
            if sum(1 for item in selected if item.get("question_type") == question_type) >= target_by_type[question_type]:
                break

    if len(selected) < 20:
        remaining = all_rows[:]
        rng.shuffle(remaining)
        for row in remaining:
            if row["doc_name"] not in used_docs:
                selected.append(row)
                used_docs.add(row["doc_name"])
            if len(selected) == 20:
                break
    if len(selected) != 20:
        raise RuntimeError("无法选出20道来自不同文档的题目。")

    rng.shuffle(selected)
    train_rows = selected[:12]
    dev_rows = selected[12:]
    split_by_id = {row["financebench_id"]: "train" for row in train_rows}
    split_by_id.update({row["financebench_id"]: "dev" for row in dev_rows})

    PILOT_MARKDOWN.mkdir(parents=True, exist_ok=True)
    PILOT_PDFS.mkdir(parents=True, exist_ok=True)
    PILOT_PROCESSED.mkdir(parents=True, exist_ok=True)
    for row in selected:
        markdown_source = SOURCE_MARKDOWN / f"{row['doc_name']}.md"
        pdf_source = SOURCE_ROOT / "pdfs" / f"{row['doc_name']}.pdf"
        if markdown_source.exists():
            destination = PILOT_MARKDOWN / markdown_source.name
            if not destination.exists() or destination.stat().st_size != markdown_source.stat().st_size:
                shutil.copy2(markdown_source, destination)
        elif pdf_source.exists():
            destination = PILOT_PDFS / pdf_source.name
            if not destination.exists() or destination.stat().st_size != pdf_source.stat().st_size:
                shutil.copy2(pdf_source, destination)
        else:
            raise RuntimeError(f"缺少 Markdown 和 PDF 文档：{row['doc_name']}")

    write_jsonl(PILOT_JSONL, selected)
    manifest = {
        "seed": SEED,
        "source": str(SOURCE_JSONL),
        "source_is_read_only": True,
        "question_count": len(selected),
        "document_count": len(used_docs),
        "question_type_counts": dict(Counter(str(row.get("question_type")) for row in selected)),
        "splits": split_by_id,
        "questions": [
            {
                "financebench_id": row["financebench_id"],
                "split": split_by_id[row["financebench_id"]],
                "doc_name": row["doc_name"],
                "question_type": row.get("question_type"),
                "question": row["question"],
            }
            for row in selected
        ],
    }
    save_json(PILOT_MANIFEST, manifest)
    return selected


def preflight_models(env: dict[str, str]) -> None:
    tests = {
        "Student": (env["STUDENT_BASE_URL"], env.get("STUDENT_API_KEY") or env["VOLCENGINE_API_KEY"], env["STUDENT_MODEL"]),
        "Teacher/Judge": (env["TEACHER_BASE_URL"], env.get("TEACHER_API_KEY") or env["VOLCENGINE_API_KEY"], env["TEACHER_MODEL"]),
    }
    checked: set[tuple[str, str]] = set()
    for role, (base_url, api_key, model) in tests.items():
        signature = (base_url, model)
        if signature in checked:
            continue
        say(f"[连通性检查] {role}: {model}")
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60, max_retries=1)
        try:
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=8,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{role} 模型调用失败（{model}）。这通常是模型ID在你的账号中不同。"
                "请把火山控制台该模型的‘API调用’示例截图发给我，不要发送API Key。\n"
                f"原始错误：{exc}"
            ) from exc
        checked.add(signature)


def model_json_call(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    # Seed Pro can spend several minutes on hidden reasoning.  A longer per-request
    # timeout plus explicit outer retries is safer than letting one transient timeout
    # discard an otherwise completed experiment.
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=600, max_retries=1)
    attempts = [
        {"temperature": temperature, "response_format": {"type": "json_object"}, "max_tokens": max_tokens},
        {"max_tokens": max_tokens},
        {"max_tokens": max_tokens},
    ]
    last_error: Exception | None = None
    for attempt_number, extra in enumerate(attempts, start=1):
        try:
            response = client.chat.completions.create(model=model, messages=messages, **extra)
            content = response.choices[0].message.content or ""
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                raise ValueError("模型没有返回JSON对象。")
            return json.loads(match.group(0))
        except Exception as exc:
            last_error = exc
            error_text = str(exc)
            if any(marker in error_text for marker in ("AccountOverdueError", "PermissionDeniedError", "code: 403")):
                raise RuntimeError(
                    f"模型 {model} 被火山账户拒绝调用（欠费、余额不足或无权限），已立即停止且保留断点：{exc}"
                ) from exc
            if attempt_number < len(attempts):
                wait_seconds = 10 * attempt_number
                say(f"[模型重试] {model} 第{attempt_number}次失败：{type(exc).__name__}。{wait_seconds}秒后继续，已完成结果不会丢失。")
                time.sleep(wait_seconds)
    raise RuntimeError(f"模型 {model} 返回JSON失败：{last_error}")


def make_harness_config(path: Path, output_base: Path, instructions: list[str]) -> None:
    config = {
        "project_name": "Agentic_RAG_Self_Learning_Pilot",
        "dataset_name": "FinanceBench_pilot20",
        "adapter": {
            "module": "src.adapters.finance_bench_adapter",
            "class_name": "FinanceBenchAdapter",
        },
        "store": {
            "type": "DeepRead",
            "enable_vector": True,
            "enable_hybrid": False,
            "enable_semantic": False,
            "neighbor_window": "1,-1",
            "max_rounds": 30,
            "use_pymupdf": True,
            "source_header_enabled": True,
            "enable_session_pagination": True,
            "preload_directory_structure": False,
            "agent_topk_max": 10,
            "pagination_candidate_limit": 50,
            "agent_instructions": instructions,
            "embedding_api_key": "${EMBEDDING_API_KEY}",
            "embedding_base_url": "${EMBEDDING_BASE_URL}",
            "embedding_model": "${EMBEDDING_MODEL_NAME}",
        },
        "execution": {
            "max_workers": 1,
            "ingest_workers": 1,
            "retrieval_topk": 1,
            "max_queries": None,
            "skip_ingestion": False,
        },
        "paths": {
            "raw_data": str(PILOT_JSONL),
            "doc_output_dir": str(PILOT_PROCESSED),
            "vector_store": str(PILOT_INDEX),
            "output_dir": str(output_base),
        },
        "llm": {
            "model": "${LLM_MODEL}",
            "temperature": 0,
            "base_url": "${LLM_BASE_URL}",
            "api_key": "${LLM_API_KEY}",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def index_is_complete(rows: list[dict[str, Any]]) -> bool:
    return all((PILOT_INDEX / f"{row['doc_name']}_corpus.json").exists() for row in rows)


def run_student(
    session_dir: Path,
    stage_name: str,
    instructions: list[str],
    env_values: dict[str, str],
    rows: list[dict[str, Any]],
    allow_ingest: bool,
) -> Path:
    stage_dir = session_dir / stage_name
    completed_outputs = sorted(stage_dir.glob("output_*"), key=lambda item: item.stat().st_mtime)
    for existing_output in reversed(completed_outputs):
        generated_path = existing_output / "generated_answers.json"
        if generated_path.exists():
            try:
                if len(load_json(generated_path).get("results", [])) == len(rows):
                    say(f"[断点续跑] 复用已完成的 Student 阶段：{stage_name}")
                    return existing_output
            except Exception:
                pass
    config_path = stage_dir / "config.yaml"
    output_base = stage_dir / "output"
    make_harness_config(config_path, output_base, instructions)

    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env["PYTHONUTF8"] = "1"

    command = [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "gen"]
    if not allow_ingest or index_is_complete(rows):
        command.append("--skip-ingest")
    say(f"[Student] 开始 {stage_name}（20题）……")
    result = subprocess.run(command, cwd=str(REPO_DIR / "ov_test"), env=process_env)
    if result.returncode != 0:
        raise RuntimeError(f"Student 阶段失败：{stage_name}")
    candidates = sorted(stage_dir.glob("output_*"), key=lambda item: item.stat().st_mtime)
    if not candidates:
        raise RuntimeError(f"找不到 Student 输出：{stage_dir}")
    output_dir = candidates[-1]
    if not (output_dir / "generated_answers.json").exists():
        raise RuntimeError(f"Student 未生成答案文件：{output_dir}")
    return output_dir


def token_f1(answer: str, gold: str) -> float:
    answer_tokens = re.findall(r"[A-Za-z0-9.%$-]+", answer.lower())
    gold_tokens = re.findall(r"[A-Za-z0-9.%$-]+", gold.lower())
    if not answer_tokens or not gold_tokens:
        return 0.0
    common = Counter(answer_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if not overlap:
        return 0.0
    precision = overlap / len(answer_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def judge_output(output_dir: Path, rows: list[dict[str, Any]], env: dict[str, str]) -> list[dict[str, Any]]:
    generated_path = output_dir / "generated_answers.json"
    judged_path = output_dir / "judged_results.json"
    generated = load_json(generated_path).get("results", [])
    by_question = {row["question"]: row for row in rows}
    manifest = load_json(PILOT_MANIFEST)
    split_by_id = manifest["splits"]
    existing: dict[str, dict[str, Any]] = {}
    if judged_path.exists():
        existing = {item["financebench_id"]: item for item in load_json(judged_path).get("results", [])}

    judged: list[dict[str, Any]] = []
    for index, item in enumerate(generated, start=1):
        source = by_question.get(item["question"])
        if not source:
            raise RuntimeError("无法把生成答案对应回 FinanceBench 题目。")
        financebench_id = source["financebench_id"]
        if financebench_id in existing:
            judged.append(existing[financebench_id])
            continue
        answer = item.get("llm", {}).get("final_answer", "")
        gold = source["answer"]
        prompt = f"""Score an answer to a FinanceBench question from 0 to 4.
4 = fully correct with no core factual error.
3 = correct but slightly incomplete.
2 = relevant but misses a core fact or has a minor factual error.
1 = major factual error.
0 = wrong, unsupported, or refuses despite an available answer.

Question: {source['question']}
Gold answer: {gold}
Generated answer: {answer}

Return JSON only: {{"score": 0, "reasoning": "one concise sentence"}}"""
        say(f"[Judge] {index}/{len(generated)}")
        evaluation = model_json_call(
            env["JUDGE_BASE_URL"],
            env.get("JUDGE_API_KEY") or env["VOLCENGINE_API_KEY"],
            env["JUDGE_MODEL"],
            [
                {"role": "system", "content": "You are a strict and consistent financial QA evaluator."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=2048,
        )
        score = max(0, min(4, int(evaluation.get("score", 0))))
        record = {
            "financebench_id": financebench_id,
            "split": split_by_id[financebench_id],
            "doc_name": source["doc_name"],
            "question_type": source.get("question_type"),
            "question": source["question"],
            "gold_answer": gold,
            "student_answer": answer,
            "evidence": [ev.get("evidence_text", "") for ev in source.get("evidence", [])],
            "retrieval_recall": item.get("metrics", {}).get("Recall", 0),
            "retrieved_texts": item.get("retrieval", {}).get("recall_texts", [])[:4],
            "latency_sec": item.get("retrieval", {}).get("latency_sec", 0),
            "input_tokens": item.get("token_usage", {}).get("total_input_tokens", 0),
            "output_tokens": item.get("token_usage", {}).get("llm_output_tokens", 0),
            "token_f1": token_f1(answer, gold),
            "judge_score": score,
            "judge_reasoning": str(evaluation.get("reasoning", "")),
        }
        judged.append(record)
        save_json(judged_path, {"results": judged})
    return judged


def metrics(records: list[dict[str, Any]], split: str | None = None) -> dict[str, float]:
    subset = [record for record in records if split is None or record["split"] == split]
    if not subset:
        return {"count": 0, "average_score": 0, "normalized_accuracy": 0, "average_recall": 0, "average_input_tokens": 0, "average_latency_sec": 0}
    average_score = sum(record["judge_score"] for record in subset) / len(subset)
    return {
        "count": len(subset),
        "average_score": average_score,
        "normalized_accuracy": average_score / 4,
        "average_recall": sum(float(record["retrieval_recall"]) for record in subset) / len(subset),
        "average_input_tokens": sum(float(record["input_tokens"]) for record in subset) / len(subset),
        "average_latency_sec": sum(float(record["latency_sec"]) for record in subset) / len(subset),
    }


def split_numbered_instructions(text: str) -> list[str]:
    parts = re.split(r"(?:^|\n)\s*\d+\.\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def normalize_teacher_response(response: dict[str, Any]) -> dict[str, Any]:
    """Accept both the requested candidates array and Seed Pro's keyed-object variant."""
    if isinstance(response.get("candidates"), list):
        return response

    strategies = ("minimal_patch", "retrieval_discipline", "reasoning_verification")
    if not all(isinstance(response.get(strategy), str) and response[strategy].strip() for strategy in strategies):
        return response

    candidates = []
    for strategy in strategies:
        instructions = split_numbered_instructions(response[strategy])
        candidates.append({
            "candidate_id": f"r1_{strategy}",
            "strategy": strategy,
            "instructions": instructions,
            "target_failure_modes": ["recurring_retrieval_or_reasoning_failures"],
            "expected_effect": "Improve evidence selection and answer verification on unseen questions.",
            "regression_risks": ["May add extra tool calls or verification tokens."],
            "specificity_audit": {
                "contains_company_names": False,
                "contains_case_answers_or_numbers": False,
                "contains_doc_or_node_ids": False,
                "estimated_prompt_tokens": max(1, len(response[strategy]) // 4),
            },
        })
    return {
        "round": 1,
        "global_diagnosis": "Teacher returned three strategy-keyed instruction sets; normalized locally without another API call.",
        "failure_clusters": [{
            "name": "retrieval_and_verification",
            "description": "Recurring evidence selection, period/unit alignment, and calculation verification failures.",
            "estimated_frequency": 0,
            "actionable": True,
        }],
        "candidates": candidates,
    }


def ask_teacher(session_dir: Path, baseline: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
    meta_prompt = (PROJECT_DIR / "prompts" / "teacher_prompt_optimizer.md").read_text(encoding="utf-8")
    train_failures = [
        record for record in baseline
        if record["split"] == "train" and (record["judge_score"] <= 2 or float(record["retrieval_recall"]) < 0.5)
    ]
    if not train_failures:
        train_failures = [record for record in baseline if record["split"] == "train"]
    compact = []
    for record in train_failures[:12]:
        compact.append({
            "question_type": record["question_type"],
            "question": record["question"],
            "student_answer": record["student_answer"],
            "gold_answer": record["gold_answer"],
            "judge_score": record["judge_score"],
            "judge_reasoning": record["judge_reasoning"],
            "evidence_recall": record["retrieval_recall"],
            "retrieved_snippets": record["retrieved_texts"][:2],
        })
    payload = {
        "round": 1,
        "current_agent_instructions": [],
        "train_metrics": metrics(baseline, "train"),
        "train_failure_records": compact,
    }
    say(f"[Teacher] 正在分析 {len(compact)} 个训练集失败案例并生成3套提示词……")
    response = model_json_call(
        env["TEACHER_BASE_URL"],
        env.get("TEACHER_API_KEY") or env["VOLCENGINE_API_KEY"],
        env["TEACHER_MODEL"],
        [
            {"role": "system", "content": meta_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=8192,
    )
    response = normalize_teacher_response(response)
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        save_json(session_dir / "teacher_invalid_response.json", response)
        raise RuntimeError("Teacher 没有返回3套候选提示词；原始结果已保存。")
    for index, candidate in enumerate(candidates, start=1):
        instructions = candidate.get("instructions")
        if not isinstance(instructions, list) or not instructions or not all(isinstance(value, str) for value in instructions):
            raise RuntimeError(f"Teacher 第{index}套候选的 instructions 格式不正确。")
    save_json(session_dir / "teacher_candidates.json", response)
    return response


def select_best(baseline: list[dict[str, Any]], candidate_results: list[tuple[dict[str, Any], list[dict[str, Any]], Path]]) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    def key(value: tuple[dict[str, Any], list[dict[str, Any]], Path]) -> tuple[float, float, float, float]:
        result_metrics = metrics(value[1], "dev")
        return (
            result_metrics["normalized_accuracy"],
            result_metrics["average_recall"],
            -result_metrics["average_input_tokens"],
            -result_metrics["average_latency_sec"],
        )
    return max(candidate_results, key=key)


def write_report(
    session_dir: Path,
    baseline: list[dict[str, Any]],
    candidates: list[tuple[dict[str, Any], list[dict[str, Any]], Path]],
    best: tuple[dict[str, Any], list[dict[str, Any]], Path],
) -> None:
    best_candidate, best_records, best_output = best
    baseline_dev = metrics(baseline, "dev")
    best_dev = metrics(best_records, "dev")
    delta = best_dev["normalized_accuracy"] - baseline_dev["normalized_accuracy"]
    lines = [
        "# Agentic RAG 自学习 20题 Pilot 结果",
        "",
        "## 实验说明",
        "",
        "本次使用20道来自不同文档的 FinanceBench 问题。12题作为 Teacher 可见的训练集，8题作为 Teacher 不可见的开发集。Student 模型和检索配置保持不变，只改变追加给 Agent 的行为提示词。",
        "",
        "## 开发集核心结果",
        "",
        "| 设置 | 题数 | 平均得分(0-4) | 归一化准确率 | Evidence Recall | 平均输入Token | 平均耗时(s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Baseline | {int(baseline_dev['count'])} | {baseline_dev['average_score']:.3f} | {baseline_dev['normalized_accuracy']:.2%} | {baseline_dev['average_recall']:.2%} | {baseline_dev['average_input_tokens']:.0f} | {baseline_dev['average_latency_sec']:.1f} |",
    ]
    for candidate, records, _ in candidates:
        value = metrics(records, "dev")
        lines.append(
            f"| {candidate.get('candidate_id', candidate.get('strategy', 'candidate'))} | {int(value['count'])} | {value['average_score']:.3f} | {value['normalized_accuracy']:.2%} | {value['average_recall']:.2%} | {value['average_input_tokens']:.0f} | {value['average_latency_sec']:.1f} |"
        )
    lines.extend([
        "",
        "## 当前最佳提示词",
        "",
        f"候选：`{best_candidate.get('candidate_id', best_candidate.get('strategy', 'candidate'))}`",
        "",
        *[f"- {instruction}" for instruction in best_candidate["instructions"]],
        "",
        "## 初步结论",
        "",
        f"最佳候选相对 Baseline 的开发集归一化准确率变化为 {delta:+.2%}。20题 Pilot 的用途是验证自学习闭环和观察方向，不能代替141题正式结论。",
        "",
        "## 文件位置",
        "",
        f"- Baseline 与候选的完整输出位于：`{session_dir}`",
        f"- 当前最佳候选输出：`{best_output}`",
        "",
    ])
    (session_dir / "RESULT_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(session_dir / "comparison.json", {
        "baseline": {"all": metrics(baseline), "train": metrics(baseline, "train"), "dev": baseline_dev},
        "candidates": [
            {
                "candidate_id": candidate.get("candidate_id"),
                "strategy": candidate.get("strategy"),
                "all": metrics(records),
                "train": metrics(records, "train"),
                "dev": metrics(records, "dev"),
                "output_dir": str(output_dir),
            }
            for candidate, records, output_dir in candidates
        ],
        "best_candidate_id": best_candidate.get("candidate_id"),
    })


def reset_index() -> None:
    if not PILOT_INDEX.exists():
        return
    resolved = PILOT_INDEX.resolve()
    safe_root = (PROJECT_DIR / "data" / "generated").resolve()
    if safe_root not in resolved.parents:
        raise RuntimeError(f"拒绝删除不在实验目录内的索引：{resolved}")
    shutil.rmtree(resolved)


def find_resumable_session(candidate_limit: int) -> Path | None:
    if not RUNS_DIR.exists():
        return None
    sessions = sorted(
        (path for path in RUNS_DIR.glob("pilot_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for session in sessions:
        if (session / "RESULT_SUMMARY.md").exists():
            continue
        metadata_path = session / "run_metadata.json"
        if not metadata_path.exists():
            continue
        try:
            metadata = load_json(metadata_path)
        except Exception:
            continue
        if int(metadata.get("candidate_limit", 1)) == candidate_limit:
            return session
    return None


def find_completed_pilot() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    sessions = sorted(
        (
            path for path in RUNS_DIR.glob("pilot_*")
            if path.is_dir() and (path / "RESULT_SUMMARY.md").exists()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return sessions[0] if sessions else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FinanceBench 20-question Agentic RAG self-learning pilot.")
    parser.add_argument("--candidate-limit", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--dry-run", action="store_true", help="Prepare and validate files without any API calls.")
    parser.add_argument("--force-new-index", action="store_true", help="Delete only the generated pilot index and rebuild it.")
    args = parser.parse_args()

    validate_layout()
    env = load_experiment_env()
    if args.force_new_index:
        reset_index()
    rows = prepare_pilot()
    say(f"[数据准备] 20题、20文档；原始 Data 保持只读。题单：{PILOT_MANIFEST}")
    if args.dry_run:
        say("[DRY RUN通过] 文件、密钥占位符、模型字段和数据路径检查正常；没有调用任何API。")
        return 0

    completed_pilot = find_completed_pilot()
    if completed_pilot is not None:
        say(f"[已完成] 已存在完整20题 Pilot，拒绝重复运行：{completed_pilot.name}")
        return 0

    session_dir = find_resumable_session(args.candidate_limit)
    if session_dir is not None:
        say(f"[断点续跑] 继续上次未完成实验：{session_dir.name}")
    else:
        preflight_models(env)
        session_name = datetime.now().strftime("pilot_%Y%m%d_%H%M%S")
        session_dir = RUNS_DIR / session_name
        session_dir.mkdir(parents=True, exist_ok=False)
        save_json(session_dir / "run_metadata.json", {
            "started_at": datetime.now().isoformat(),
            "student_model": env["STUDENT_MODEL"],
            "teacher_model": env["TEACHER_MODEL"],
            "judge_model": env["JUDGE_MODEL"],
            "candidate_limit": args.candidate_limit,
            "source_data_modified": False,
        })

    baseline_output = run_student(session_dir, "baseline", [], env, rows, allow_ingest=True)
    baseline = judge_output(baseline_output, rows, env)
    teacher_path = session_dir / "teacher_candidates.json"
    invalid_teacher_path = session_dir / "teacher_invalid_response.json"
    if teacher_path.exists():
        say("[断点续跑] 复用 Teacher 已生成的候选提示词。")
        teacher = load_json(teacher_path)
    elif invalid_teacher_path.exists():
        teacher = normalize_teacher_response(load_json(invalid_teacher_path))
        if not isinstance(teacher.get("candidates"), list) or len(teacher["candidates"]) != 3:
            raise RuntimeError("已保存的 Teacher 结果仍无法转换为3套候选提示词。")
        save_json(teacher_path, teacher)
        say("[断点续跑] 已将上次 Teacher 的三套提示词转换为标准格式，无需再次调用 Teacher。")
    else:
        teacher = ask_teacher(session_dir, baseline, env)

    candidate_results: list[tuple[dict[str, Any], list[dict[str, Any]], Path]] = []
    for index, candidate in enumerate(teacher["candidates"][: args.candidate_limit], start=1):
        candidate_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(candidate.get("candidate_id") or f"candidate_{index}"))
        output_dir = run_student(
            session_dir,
            candidate_id,
            candidate["instructions"],
            env,
            rows,
            allow_ingest=False,
        )
        records = judge_output(output_dir, rows, env)
        candidate_results.append((candidate, records, output_dir))

    best = select_best(baseline, candidate_results)
    write_report(session_dir, baseline, candidate_results, best)
    say("\n[完成] 20题 Agentic RAG 自学习闭环已经跑完。")
    say(f"结果摘要：{session_dir / 'RESULT_SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 可以之后重新运行；已完成的 DeepRead 索引会被复用。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
