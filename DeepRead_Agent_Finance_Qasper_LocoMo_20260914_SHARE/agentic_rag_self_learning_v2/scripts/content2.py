from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
REPO = WORKSPACE / "ruc-ov-eval-zqy-DeepRead"
HARNESS = REPO / "ov_test" / "run.py"
SOURCE_JSONL = WORKSPACE / "Data" / "FinanceBench" / "data" / "financebench_open_source.jsonl"
OLD_EXPERIMENT = WORKSPACE / "agentic_rag_self_learning"
OLD_SCRIPT_DIR = OLD_EXPERIMENT / "scripts"
TITLE_OUTPUT = (
    WORKSPACE
    / "ExperimentArtifacts"
    / "FinanceBenchFull141"
    / "Output"
    / "deepread_title_entity_141_0001"
)
TITLE_RESULTS = TITLE_OUTPUT / "qa_eval_detailed_results.json"
TITLE_LOG = TITLE_OUTPUT / "deepread_run.log"
FULL_INDEX = OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "store_index"
FULL_PROCESSED = OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "processed_docs"
DATA_DIR = ROOT / "data"
SPLIT_DIR = DATA_DIR / "splits"
TRAJECTORY_FILE = DATA_DIR / "trajectories" / "title_v1_trajectories.jsonl"
MANIFEST = SPLIT_DIR / "manifest.json"
RUN_DIR = ROOT / "runs" / "round1"
TEST_DIR = ROOT / "runs" / "frozen_test61"
SEED = 20260818
TARGETS = {"train": 60, "dev": 20, "test": 61}

sys.path.insert(0, str(OLD_SCRIPT_DIR))
import run_pilot as legacy  # noqa: E402


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
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp.replace(path)


def clip(value: Any, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def validate_layout() -> None:
    required = [
        HARNESS,
        SOURCE_JSONL,
        OLD_EXPERIMENT / ".env",
        TITLE_RESULTS,
        TITLE_LOG,
        FULL_INDEX,
        FULL_PROCESSED,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("缺少内容2需要复用的文件：\n" + "\n".join(missing))
    corpus_count = len(list(FULL_INDEX.glob("*_corpus.json")))
    if corpus_count != 82:
        raise RuntimeError(f"完整索引应有82个文档 corpus，实际为 {corpus_count}。")


def subset_sum_groups(
    groups: list[tuple[str, list[dict[str, Any]]]], target: int, rng: random.Random
) -> set[str] | None:
    shuffled = groups[:]
    rng.shuffle(shuffled)
    possible: dict[int, tuple[str, ...]] = {0: ()}
    for doc_name, rows in shuffled:
        size = len(rows)
        for total, chosen in sorted(list(possible.items()), reverse=True):
            new_total = total + size
            if new_total <= target and new_total not in possible:
                possible[new_total] = chosen + (doc_name,)
        if target in possible:
            return set(possible[target])
    return None


def category_error(
    split_rows: dict[str, list[dict[str, Any]]], all_rows: list[dict[str, Any]]
) -> float:
    global_counts = Counter(str(row.get("question_type") or "unknown") for row in all_rows)
    error = 0.0
    for split, rows in split_rows.items():
        counts = Counter(str(row.get("question_type") or "unknown") for row in rows)
        target = TARGETS[split]
        for category, global_count in global_counts.items():
            expected = target * global_count / len(all_rows)
            error += abs(counts[category] - expected)
    return error


def make_grouped_split(rows: list[dict[str, Any]]) -> dict[str, str]:
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_doc[str(row["doc_name"])].append(row)
    groups = list(by_doc.items())
    best: tuple[float, dict[str, str]] | None = None
    for attempt in range(1200):
        rng = random.Random(SEED + attempt)
        train_docs = subset_sum_groups(groups, TARGETS["train"], rng)
        if train_docs is None:
            continue
        remaining = [group for group in groups if group[0] not in train_docs]
        dev_docs = subset_sum_groups(remaining, TARGETS["dev"], rng)
        if dev_docs is None:
            continue
        mapping: dict[str, str] = {}
        split_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            split = "train" if row["doc_name"] in train_docs else "dev" if row["doc_name"] in dev_docs else "test"
            mapping[row["financebench_id"]] = split
            split_rows[split].append(row)
        score = category_error(split_rows, rows)
        if best is None or score < best[0]:
            best = (score, mapping)
            if score < 1.0:
                break
    if best is None:
        raise RuntimeError("无法生成60/20/61的按文档分组划分。")
    return best[1]


def query_id(question: str) -> str:
    return hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]


def compact_tool_result(tool: str, result: Any, question: str) -> Any:
    if not isinstance(result, dict):
        return clip(result)
    if tool == "search_document_titles":
        return {
            "results": [
                {
                    "doc_id": item.get("doc_id"),
                    "source_name": item.get("source_name"),
                    "rank": item.get("rank"),
                    "score": item.get("score"),
                }
                for item in result.get("results", [])[:5]
            ]
        }
    if tool == "get_doc_structure":
        structure = str(result.get("structure") or "")
        words = set(re.findall(r"[A-Za-z]{4,}", question.lower()))
        lines = [line for line in structure.splitlines() if any(word in line.lower() for word in words)]
        return {
            "structure_chars": len(structure),
            "question_related_headings": [clip(line, 220) for line in lines[:8]],
        }
    trimmed = {key: value for key, value in result.items() if key not in {"context_delta_preview", "structure"}}
    return clip(json.dumps(trimmed, ensure_ascii=False), 900)


def load_compact_traces(questions: list[str]) -> dict[str, dict[str, Any]]:
    wanted = {query_id(question): question for question in questions}
    traces: dict[str, dict[str, Any]] = {
        qid: {"query_id": qid, "steps": [], "rounds": 0, "title_candidates": []}
        for qid in wanted
    }
    with TITLE_LOG.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = str(event.get("query_id") or "")
            if qid not in traces:
                continue
            kind = event.get("event")
            trace = traces[qid]
            if kind == "llm_response":
                round_number = int(event.get("round") or 0)
                trace["rounds"] = max(trace["rounds"], round_number)
                reasoning = clip(event.get("reasoning_content"), 650)
                tools = [item.get("name") for item in (event.get("tool_calls") or [])]
                if reasoning or tools:
                    trace["steps"].append({"round": round_number, "agent_reasoning": reasoning, "requested_tools": tools})
            elif kind == "tool_call":
                trace["steps"].append({"tool": event.get("tool"), "args": event.get("args", {})})
            elif kind == "tool_result":
                tool = str(event.get("tool") or "")
                compact = compact_tool_result(tool, event.get("result"), wanted[qid])
                trace["steps"].append({"tool_result": tool, "ok": event.get("ok"), "result": compact})
                if tool == "search_document_titles" and isinstance(event.get("result"), dict):
                    trace["title_candidates"] = event["result"].get("results", [])[:5]
    for trace in traces.values():
        trace["tool_sequence"] = [
            step["tool"] for step in trace["steps"] if isinstance(step, dict) and step.get("tool")
        ]
        trace["steps"] = trace["steps"][:24]
    return traces


def prepare() -> None:
    validate_layout()
    rows = load_jsonl(SOURCE_JSONL)
    if len(rows) != 141:
        raise RuntimeError(f"FinanceBench应有141题，实际为 {len(rows)}。")

    if MANIFEST.exists():
        manifest = load_json(MANIFEST)
        split_by_id = manifest["split_by_id"]
        if manifest.get("seed") != SEED or manifest.get("targets") != TARGETS:
            raise RuntimeError("现有划分与当前固定参数不一致；为避免污染，不自动覆盖。")
    else:
        split_by_id = make_grouped_split(rows)
        split_rows = {name: [row for row in rows if split_by_id[row["financebench_id"]] == name] for name in TARGETS}
        manifest = {
            "seed": SEED,
            "method": "document_grouped_stratified_search",
            "targets": TARGETS,
            "source": str(SOURCE_JSONL),
            "source_read_only": True,
            "teacher_visibility": "train_only",
            "dev_use": "candidate_selection_only",
            "test_policy": "run_once_after_skill_freeze",
            "split_by_id": split_by_id,
            "summary": {
                name: {
                    "questions": len(values),
                    "documents": len({row["doc_name"] for row in values}),
                    "question_types": dict(Counter(row.get("question_type", "unknown") for row in values)),
                }
                for name, values in split_rows.items()
            },
        }
        save_json(MANIFEST, manifest)

    for split in TARGETS:
        subset = [row for row in rows if split_by_id[row["financebench_id"]] == split]
        if len(subset) != TARGETS[split]:
            raise RuntimeError(f"{split}题数错误：{len(subset)}")
        save_jsonl(SPLIT_DIR / f"{split}.jsonl", subset)

    if TRAJECTORY_FILE.exists() and len(load_jsonl(TRAJECTORY_FILE)) == 141:
        say("[准备] 复用已生成的141题压缩轨迹。")
        return

    evaluated = load_json(TITLE_RESULTS).get("results", [])
    by_question = {item["question"]: item for item in evaluated}
    traces = load_compact_traces([row["question"] for row in rows])
    records: list[dict[str, Any]] = []
    for row in rows:
        result = by_question.get(row["question"])
        if result is None:
            raise RuntimeError(f"原标题路由输出中找不到题目：{row['financebench_id']}")
        trace = traces[query_id(row["question"])]
        expected_doc = row["doc_name"]
        title_rank = next(
            (int(item.get("rank")) for item in trace.get("title_candidates", []) if item.get("source_name") == expected_doc),
            None,
        )
        records.append({
            "case_id": row["financebench_id"],
            "split": split_by_id[row["financebench_id"]],
            "question_type": row.get("question_type"),
            "question_reasoning": row.get("question_reasoning"),
            "doc_name": expected_doc,
            "question": row["question"],
            "gold_answer": row["answer"],
            "student_answer": result.get("llm", {}).get("final_answer", ""),
            "judge_score": int(result.get("llm_evaluation", {}).get("normalized_score", 0)),
            "judge_reasoning": result.get("llm_evaluation", {}).get("reasoning", ""),
            "evidence_recall": float(result.get("metrics", {}).get("Recall", 0)),
            "gold_evidence": [clip(item.get("evidence_text"), 800) for item in row.get("evidence", [])[:3]],
            "retrieved_snippets": [clip(text, 800) for text in result.get("retrieval", {}).get("recall_texts", [])[:4]],
            "input_tokens": int(result.get("token_usage", {}).get("total_input_tokens", 0)),
            "output_tokens": int(result.get("token_usage", {}).get("llm_output_tokens", 0)),
            "latency_sec": float(result.get("retrieval", {}).get("latency_sec", 0)),
            "title_rank": title_rank,
            "trajectory": trace,
        })
    save_jsonl(TRAJECTORY_FILE, records)
    say(f"[准备] 已固定60/20/61划分并生成141题结构化轨迹：{TRAJECTORY_FILE}")


def model_call(env: dict[str, str], role: str, system: str, payload: Any, max_tokens: int) -> dict[str, Any]:
    prefix = role.upper()
    model = env[f"{prefix}_MODEL"]
    base_url = env[f"{prefix}_BASE_URL"]
    api_key = env.get(f"{prefix}_API_KEY") or env["VOLCENGINE_API_KEY"]
    return legacy.model_json_call(
        base_url,
        api_key,
        model,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2 if role == "teacher" else 0,
        max_tokens=max_tokens,
    )


def select_teacher_cases(records: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    train = [record for record in records if record["split"] == "train"]
    weak = [record for record in train if record["judge_score"] <= 3]
    weak.sort(key=lambda item: (item["judge_score"], item["evidence_recall"], -item["input_tokens"]))
    selected: list[dict[str, Any]] = []
    per_type: Counter[str] = Counter()
    while weak and len(selected) < limit - 4:
        best_index = min(range(len(weak)), key=lambda index: per_type[str(weak[index]["question_type"])])
        item = weak.pop(best_index)
        selected.append(item)
        per_type[str(item["question_type"])] += 1
    successes = [record for record in train if record["judge_score"] == 4 and record not in selected]
    successes.sort(key=lambda item: (item["input_tokens"], -item["evidence_recall"]))
    selected.extend(successes[: min(4, limit - len(selected))])
    return selected


def teacher_learn() -> dict[str, Any]:
    prepare()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    env = legacy.load_experiment_env()
    records = load_jsonl(TRAJECTORY_FILE)
    cases = select_teacher_cases(records)
    analyzer_prompt = (ROOT / "prompts" / "analyzer.md").read_text(encoding="utf-8")
    diagnoses: list[dict[str, Any]] = []
    batch_size = 6
    for offset in range(0, len(cases), batch_size):
        batch_no = offset // batch_size + 1
        output_path = RUN_DIR / "analysis_batches" / f"batch_{batch_no:02d}.json"
        if output_path.exists():
            result = load_json(output_path)
            say(f"[Analyzer] 复用第{batch_no}批诊断。")
        else:
            batch = cases[offset : offset + batch_size]
            say(f"[Analyzer] 第{batch_no}批，共{len(batch)}例……")
            result = model_call(env, "teacher", analyzer_prompt, {"cases": batch}, 8192)
            save_json(output_path, result)
        batch_diagnoses = result.get("diagnoses")
        if batch_diagnoses is None:
            batch_diagnoses = result.get("case_diagnoses") or result.get("analysis") or []
        if isinstance(batch_diagnoses, dict):
            batch_diagnoses = batch_diagnoses.get("diagnoses") or list(batch_diagnoses.values())
        if not isinstance(batch_diagnoses, list):
            raise RuntimeError(f"Analyzer第{batch_no}批没有返回diagnoses数组。")
        diagnoses.extend(batch_diagnoses)

    skills_path = RUN_DIR / "candidate_skills.json"
    if skills_path.exists():
        say("[Repair] 复用已生成的三套候选skills。")
        return load_json(skills_path)

    stage_counts = Counter(str(item.get("primary_stage") or "unknown") for item in diagnoses)
    train_records = [record for record in records if record["split"] == "train"]
    payload = {
        "baseline_train_summary": {
            "questions": len(train_records),
            "average_score_0_to_4": sum(item["judge_score"] for item in train_records) / len(train_records),
            "average_input_tokens": sum(item["input_tokens"] for item in train_records) / len(train_records),
            "failure_stage_counts": dict(stage_counts),
        },
        "analyzer_diagnoses": diagnoses,
    }
    repair_prompt = (ROOT / "prompts" / "repairer.md").read_text(encoding="utf-8")
    say("[Repair] 根据分类型诊断生成三套候选skills……")
    result = model_call(env, "teacher", repair_prompt, payload, 8192)
    skills = result.get("skills") or result.get("candidates")
    if not isinstance(skills, list):
        normalized: list[dict[str, Any]] = []
        for strategy in ("minimal_repair", "retrieval_recovery", "typed_reasoning"):
            value = result.get(strategy)
            if value is None:
                continue
            if isinstance(value, str):
                instructions = [part.strip() for part in re.split(r"(?:^|\n)\s*\d+[.)]\s*", value) if part.strip()]
                value = {"instructions": instructions}
            elif isinstance(value, list):
                value = {"instructions": value}
            if isinstance(value, dict):
                normalized.append({
                    "skill_id": f"r1_{strategy}",
                    "strategy": strategy,
                    "target_stages": value.get("target_stages", ["recurring_failure"]),
                    "instructions": value.get("instructions", []),
                    "expected_benefit": value.get("expected_benefit", "Improve unseen RAG cases."),
                    "cost_risk": value.get("cost_risk", "May add conditional tool calls."),
                    "regression_risk": value.get("regression_risk", "May over-search simple questions."),
                })
        skills = normalized
        result["skills"] = skills
    required = {"minimal_repair", "retrieval_recovery", "typed_reasoning"}
    if not isinstance(skills, list) or len(skills) != 3 or {item.get("strategy") for item in skills} != required:
        save_json(RUN_DIR / "invalid_candidate_skills.json", result)
        raise RuntimeError("Repair Agent返回的三套skills格式不正确，原始结果已保存。")
    for skill in skills:
        instructions = skill.get("instructions")
        if not isinstance(instructions, list) or not instructions or not all(isinstance(item, str) for item in instructions):
            raise RuntimeError(f"{skill.get('skill_id')} 的 instructions 格式不正确。")
        if sum(len(item) for item in instructions) > 5000:
            raise RuntimeError(f"{skill.get('skill_id')} 超过安全长度限制。")
    source_rows = load_jsonl(SOURCE_JSONL)
    company_names = {
        str(row.get("company") or "").strip().lower()
        for row in source_rows
        if len(str(row.get("company") or "").strip()) >= 3
    }
    student_text = "\n".join(
        instruction for skill in skills for instruction in skill.get("instructions", [])
    ).lower()
    leaked_companies = sorted(name for name in company_names if name and name in student_text)
    if leaked_companies or "financebench_id" in student_text:
        save_json(RUN_DIR / "invalid_candidate_skills.json", result)
        raise RuntimeError(
            "Repair Agent生成了可能泄漏个案的信息，已拒绝："
            + ", ".join(leaked_companies[:5] or ["financebench_id"])
        )
    save_json(skills_path, result)
    return result


def make_config(raw_data: Path, output_base: Path, instructions: list[str], max_queries: int) -> dict[str, Any]:
    return {
        "project_name": "AgenticRAGSelfLearningV2",
        "dataset_name": "FinanceBenchContent2",
        "adapter": {"module": "src.adapters.finance_bench_adapter", "class_name": "FinanceBenchAdapter"},
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
            "enable_document_title_search": True,
            "enable_structure_title_search": False,
            "agent_topk_max": 1,
            "pagination_candidate_limit": 1,
            "agent_instructions": instructions,
            "embedding_api_key": "${EMBEDDING_API_KEY}",
            "embedding_base_url": "${EMBEDDING_BASE_URL}",
            "embedding_model": "${EMBEDDING_MODEL_NAME}",
        },
        "execution": {
            "max_workers": 1,
            "ingest_workers": 1,
            "retrieval_topk": 1,
            "max_queries": max_queries,
            "skip_ingestion": True,
        },
        "paths": {
            "raw_data": str(raw_data),
            "doc_output_dir": str(FULL_PROCESSED),
            "vector_store": str(FULL_INDEX),
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
    for output in sorted(stage.glob("output_*"), key=lambda path: path.stat().st_mtime, reverse=True):
        generated = output / "generated_answers.json"
        if not generated.exists():
            continue
        try:
            if len(load_json(generated).get("results", [])) == expected:
                return output
        except Exception:
            pass
    return None


def run_student(split: str, skill: dict[str, Any], run_root: Path) -> Path:
    rows = load_jsonl(SPLIT_DIR / f"{split}.jsonl")
    skill_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(skill["skill_id"]))
    stage = run_root / skill_id
    stage.mkdir(parents=True, exist_ok=True)
    completed = find_complete_output(stage, len(rows))
    if completed:
        say(f"[Student] 复用已完成答案：{skill_id}/{split}")
        return completed
    config_path = stage / "config.yaml"
    config = make_config(
        SPLIT_DIR / f"{split}.jsonl",
        stage / "output",
        skill["instructions"],
        len(rows),
    )
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    env_values = legacy.load_experiment_env()
    process_env = os.environ.copy()
    process_env.update(env_values)
    process_env["LLM_MODEL"] = env_values["STUDENT_MODEL"]
    process_env["LLM_API_KEY"] = env_values.get("STUDENT_API_KEY") or env_values["VOLCENGINE_API_KEY"]
    process_env["LLM_BASE_URL"] = env_values["STUDENT_BASE_URL"]
    process_env["PYTHONUTF8"] = "1"
    say(f"[Student] 运行 {skill_id} / {split}（{len(rows)}题）……")
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "gen", "--skip-ingest"],
        cwd=str(REPO / "ov_test"),
        env=process_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Student运行失败：{skill_id}/{split}")
    completed = find_complete_output(stage, len(rows))
    if completed is None:
        raise RuntimeError(f"Student没有生成完整答案：{skill_id}/{split}")
    return completed


def judge_prompt(question: str, gold: str, answer: str) -> str:
    return f'''Score Generated Answer vs Gold Answer (0-4).
The Gold Answer is provided as a JSON array. Treat the array as the complete set of acceptable answers.
RULE:
1: Strictly penalize core factual errors. DO NOT penalize verbosity, expanded lists, or non-contradictory redundancy.
2: Refusal Check: If Gold contains facts but Gen says "Not mentioned", score 0. If both say "Not mentioned", score 4.

[Rubric]
4: Fully captures Gold Answer. No factual errors. Extra valid info allowed.
3: Accurate but incomplete. No core errors.
2: Misses core facts but relevant, OR minor secondary errors.
1: Core factual errors (e.g., wrong dates/methods).
0: Completely wrong or hallucinates conflicting info.

Question: {question}
Gold Answer: {json.dumps([gold], ensure_ascii=False)}
Generated Answer: {answer}

Respond ONLY with JSON: {{"score": 0, "reasoning": "one sentence"}}'''


def judge_records(
    label: str,
    split: str,
    source_rows: list[dict[str, Any]],
    answers: dict[str, dict[str, Any]],
    output_path: Path,
) -> list[dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    env = legacy.load_experiment_env()
    if output_path.exists():
        saved = load_json(output_path)
        saved_model = str(saved.get("judge_model") or "")
        if saved_model and saved_model != env["JUDGE_MODEL"]:
            backup = output_path.with_name(output_path.stem + f".backup_{re.sub(r'[^A-Za-z0-9_.-]', '_', saved_model)}.json")
            if backup.exists():
                backup = output_path.with_name(output_path.stem + ".backup_previous.json")
            output_path.replace(backup)
            say(f"[Judge] 模型已变化，旧评分备份为：{backup.name}")
        else:
            existing = {item["case_id"]: item for item in saved.get("results", [])}
    results: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows, start=1):
        case_id = row["financebench_id"]
        if case_id in existing:
            results.append(existing[case_id])
            continue
        generated = answers[row["question"]]
        answer = generated.get("llm", {}).get("final_answer", "")
        say(f"[Judge:{label}] {index}/{len(source_rows)}")
        evaluation = model_call(
            env,
            "judge",
            "You are an expert evaluator scoring how well an AI-generated answer matches a gold standard.",
            {"grading_task": judge_prompt(row["question"], row["answer"], answer)},
            2048,
        )
        score = max(0, min(4, int(evaluation.get("score", 0))))
        results.append({
            "case_id": case_id,
            "split": split,
            "question_type": row.get("question_type"),
            "question": row["question"],
            "gold_answer": row["answer"],
            "student_answer": answer,
            "score": score,
            "judge_reasoning": str(evaluation.get("reasoning", "")),
            "input_tokens": int(generated.get("token_usage", {}).get("total_input_tokens", 0)),
            "output_tokens": int(generated.get("token_usage", {}).get("llm_output_tokens", 0)),
            "latency_sec": float(generated.get("retrieval", {}).get("latency_sec", 0)),
            "recall": float(generated.get("metrics", {}).get("Recall", 0)),
        })
        save_json(output_path, {"judge_model": env["JUDGE_MODEL"], "results": results})
    return results


def baseline_answers(split: str) -> dict[str, dict[str, Any]]:
    all_results = load_json(TITLE_RESULTS).get("results", [])
    wanted = {row["question"] for row in load_jsonl(SPLIT_DIR / f"{split}.jsonl")}
    return {item["question"]: item for item in all_results if item["question"] in wanted}


def generated_answers(output: Path) -> dict[str, dict[str, Any]]:
    return {item["question"]: item for item in load_json(output / "generated_answers.json").get("results", [])}


def metrics(records: list[dict[str, Any]]) -> dict[str, float]:
    count = len(records)
    return {
        "count": count,
        "average_score": sum(item["score"] for item in records) / count,
        "accuracy": sum(item["score"] for item in records) / (4 * count),
        "average_input_tokens": sum(item["input_tokens"] for item in records) / count,
        "average_output_tokens": sum(item["output_tokens"] for item in records) / count,
        "average_latency_sec": sum(item["latency_sec"] for item in records) / count,
        "average_recall": sum(item["recall"] for item in records) / count,
    }


def paired(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    before = {item["case_id"]: item for item in baseline}
    after = {item["case_id"]: item for item in candidate}
    deltas = [after[key]["score"] - before[key]["score"] for key in before]
    return {
        "wins": sum(delta > 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
        "losses": sum(delta < 0 for delta in deltas),
        "net_score": sum(deltas),
        "large_regressions": sum(delta <= -2 for delta in deltas),
    }


def write_round1_report(
    skills: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    candidates: list[tuple[dict[str, Any], list[dict[str, Any]], Path]],
    selected_id: str,
) -> None:
    base_metrics = metrics(baseline)
    lines = [
        "# 研究内容2：Agent自学习 Round 1",
        "",
        "本轮严格使用60题训练轨迹供Teacher学习，20题开发集选择skills；61题测试集尚未运行。原标题路由V1是共同Baseline，Student、索引、工具和检索参数保持不变。",
        "",
        "## 开发集结果",
        "",
        "| 方案 | 准确率 | 平均分(0-4) | 胜/平/负 | 输入Token/题 | 耗时/题 | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Title V1 Baseline | {base_metrics['accuracy']:.2%} | {base_metrics['average_score']:.3f} | — | {base_metrics['average_input_tokens']:.0f} | {base_metrics['average_latency_sec']:.1f}s | {base_metrics['average_recall']:.2%} |",
    ]
    comparison: dict[str, Any] = {"baseline": base_metrics, "candidates": {}, "selected": selected_id}
    for skill, records, output in candidates:
        value = metrics(records)
        pair = paired(baseline, records)
        skill_id = skill["skill_id"]
        comparison["candidates"][skill_id] = {"metrics": value, "paired": pair, "output": str(output)}
        lines.append(
            f"| {skill_id} | {value['accuracy']:.2%} | {value['average_score']:.3f} | {pair['wins']}/{pair['ties']}/{pair['losses']} | {value['average_input_tokens']:.0f} | {value['average_latency_sec']:.1f}s | {value['average_recall']:.2%} |"
        )
    selected = next((skill for skill in skills if skill["skill_id"] == selected_id), None)
    lines.extend(["", "## 自动选择", ""])
    if selected is None:
        lines.append("三套候选均未通过“开发集准确率不得低于Baseline”的门槛，因此本轮保留 `Title V1 Baseline`，不打开测试集。")
    else:
        lines.extend([
            f"冻结候选：`{selected_id}`。选择规则为准确率优先；同分时依次比较净胜题数、输入Token和耗时。",
            "",
            "Student-facing skills：",
            "",
            *[f"- {instruction}" for instruction in selected["instructions"]],
        ])
    lines.extend([
        "",
        "## 下一步",
        "",
        "先人工检查候选是否包含个案泄漏或明显过拟合。确认后再运行 `run_test61.ps1`，测试集只运行一次。",
        "",
    ])
    save_json(RUN_DIR / "comparison.json", comparison)
    (RUN_DIR / "ROUND1_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def evaluate_dev() -> None:
    teacher = teacher_learn()
    skills = teacher["skills"]
    dev_rows = load_jsonl(SPLIT_DIR / "dev.jsonl")
    baseline_path = RUN_DIR / "baseline_dev_rejudged.json"
    baseline = judge_records("baseline", "dev", dev_rows, baseline_answers("dev"), baseline_path)
    candidates: list[tuple[dict[str, Any], list[dict[str, Any]], Path]] = []
    for skill in skills:
        output = run_student("dev", skill, RUN_DIR / "dev_candidates")
        judged_path = RUN_DIR / "dev_candidates" / skill["skill_id"] / "judged_results.json"
        records = judge_records(skill["skill_id"], "dev", dev_rows, generated_answers(output), judged_path)
        candidates.append((skill, records, output))

    baseline_accuracy = metrics(baseline)["accuracy"]
    eligible = [item for item in candidates if metrics(item[1])["accuracy"] >= baseline_accuracy]
    if eligible:
        best = max(
            eligible,
            key=lambda item: (
                metrics(item[1])["accuracy"],
                paired(baseline, item[1])["net_score"],
                -metrics(item[1])["average_input_tokens"],
                -metrics(item[1])["average_latency_sec"],
            ),
        )
        selected_id = best[0]["skill_id"]
        save_json(RUN_DIR / "frozen_skill.json", best[0])
    else:
        selected_id = "baseline"
    write_round1_report(skills, baseline, candidates, selected_id)
    say(f"[完成] Round 1开发集选择已完成：{RUN_DIR / 'ROUND1_REPORT.md'}")


def run_test() -> None:
    prepare()
    frozen_path = RUN_DIR / "frozen_skill.json"
    comparison_path = RUN_DIR / "comparison.json"
    if not frozen_path.exists() or not comparison_path.exists():
        raise RuntimeError("尚未完成Round 1，或没有候选通过开发集门槛；拒绝打开测试集。")
    skill = load_json(frozen_path)
    test_rows = load_jsonl(SPLIT_DIR / "test.jsonl")
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    metadata = TEST_DIR / "test_metadata.json"
    if metadata.exists() and load_json(metadata).get("completed"):
        say(f"[已完成] 测试集已经运行过，不重复调用：{TEST_DIR}")
        return
    save_json(metadata, {"completed": False, "skill_id": skill["skill_id"], "questions": 61})
    baseline = judge_records(
        "test_baseline", "test", test_rows, baseline_answers("test"), TEST_DIR / "baseline_rejudged.json"
    )
    output = run_student("test", skill, TEST_DIR / "candidate")
    candidate = judge_records(
        "test_candidate", "test", test_rows, generated_answers(output), TEST_DIR / "candidate_judged.json"
    )
    base_metrics = metrics(baseline)
    candidate_metrics = metrics(candidate)
    pair = paired(baseline, candidate)
    lines = [
        "# 内容2：冻结技能的61题独立测试",
        "",
        f"冻结技能：`{skill['skill_id']}`。该测试集在技能选择完成后只运行一次。",
        "",
        "| 指标 | Title V1 Baseline | 冻结技能 | 变化 |",
        "|---|---:|---:|---:|",
        f"| 准确率 | {base_metrics['accuracy']:.2%} | {candidate_metrics['accuracy']:.2%} | {(candidate_metrics['accuracy']-base_metrics['accuracy'])*100:+.2f}个百分点 |",
        f"| 平均输入Token | {base_metrics['average_input_tokens']:.0f} | {candidate_metrics['average_input_tokens']:.0f} | {candidate_metrics['average_input_tokens']-base_metrics['average_input_tokens']:+.0f} |",
        f"| 平均耗时 | {base_metrics['average_latency_sec']:.1f}s | {candidate_metrics['average_latency_sec']:.1f}s | {candidate_metrics['average_latency_sec']-base_metrics['average_latency_sec']:+.1f}s |",
        f"| 逐题胜/平/负 | — | {pair['wins']}/{pair['ties']}/{pair['losses']} | 净分{pair['net_score']:+d} |",
        "",
    ]
    (TEST_DIR / "TEST61_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(metadata, {"completed": True, "skill_id": skill["skill_id"], "questions": 61})
    say(f"[完成] 61题独立测试：{TEST_DIR / 'TEST61_REPORT.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="FinanceBench content-2 Agentic RAG self-learning pipeline")
    parser.add_argument("command", choices=("prepare", "learn", "round1", "test"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
        say(f"[检查通过] 划分摘要：{MANIFEST}")
    elif args.command == "learn":
        teacher_learn()
        say(f"[完成] Teacher候选：{RUN_DIR / 'candidate_skills.json'}")
    elif args.command == "round1":
        evaluate_dev()
    else:
        run_test()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 已完成的Teacher批次、候选答案和Judge评分均保留；重新运行同一命令即可继续。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
