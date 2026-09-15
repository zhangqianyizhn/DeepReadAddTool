from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
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
PYTHON = WORKSPACE / "agentic_rag_self_learning" / ".venv" / "Scripts" / "python.exe"
ENV_FILE = WORKSPACE / "agentic_rag_self_learning" / ".env"
RAW_QASPER = WORKSPACE / "Data" / "Qasper" / "qasper-dev-v0.3.json"
SPLIT_DIR = ROOT / "data" / "splits"
INDEX_DIR = ROOT / "data" / "index"
PROCESSED_DIR = INDEX_DIR / "processed_docs"
STORE_DIR = INDEX_DIR / "store_index"
PDF_PAGES = ROOT / "data" / "pdf_pages.json"
RUNS_DIR = ROOT / "runs"

sys.path.insert(0, str(WORKSPACE / "agentic_rag_self_learning" / "scripts"))
import run_pilot as legacy  # noqa: E402


def say(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_inputs() -> None:
    required = [HARNESS, PYTHON, ENV_FILE, RAW_QASPER]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少实验输入：\n" + "\n".join(missing))


def load_env() -> dict[str, str]:
    values = legacy.load_experiment_env()
    required = [
        "STUDENT_MODEL",
        "STUDENT_BASE_URL",
        "JUDGE_MODEL",
        "JUDGE_BASE_URL",
        "TEACHER_MODEL",
        "TEACHER_BASE_URL",
        "EMBEDDING_MODEL_NAME",
        "EMBEDDING_BASE_URL",
    ]
    missing = [key for key in required if not str(values.get(key) or "").strip()]
    if missing:
        raise RuntimeError(".env 缺少变量：" + ", ".join(missing))
    return values


def process_env(values: dict[str, str], role: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(values)
    prefix = role.upper()
    env["LLM_MODEL"] = values[f"{prefix}_MODEL"]
    env["LLM_BASE_URL"] = values[f"{prefix}_BASE_URL"]
    env["LLM_API_KEY"] = (
        values.get(f"{prefix}_API_KEY") or values.get("VOLCENGINE_API_KEY") or ""
    )
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def make_config(
    raw_data: Path,
    output_base: Path,
    max_queries: int,
    *,
    skip_ingestion: bool,
    candidate_enabled: bool = False,
    candidate_path: Path | None = None,
    inventory_path: Path | None = None,
    instructions: list[str] | None = None,
    gate_enabled: bool = False,
    gate_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "project_name": "AgenticRAGSingleToolQasper",
        "dataset_name": "QasperPaperDisjoint",
        "adapter": {
            "module": "src.adapters.qasper_adapter",
            "class_name": "QasperAdapter",
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
            "enable_document_inventory_search": False,
            "document_inventory_tool_path": "",
            "enable_generated_corpus_search": candidate_enabled,
            "generated_corpus_tool_path": str(candidate_path or ""),
            "generated_corpus_inventory_path": str(inventory_path or PDF_PAGES) if candidate_enabled else "",
            "enable_generated_corpus_gate": gate_enabled,
            "generated_corpus_gate_path": str(gate_path or ""),
            "enable_structure_title_search": False,
            "agent_topk_max": 1,
            "pagination_candidate_limit": 1,
            "agent_instructions": instructions or [],
            "embedding_api_key": "${EMBEDDING_API_KEY}",
            "embedding_base_url": "${EMBEDDING_BASE_URL}",
            "embedding_model": "${EMBEDDING_MODEL_NAME}",
        },
        "execution": {
            "max_workers": 1,
            "ingest_workers": 1,
            "retrieval_topk": 1,
            "max_queries": max_queries,
            "skip_ingestion": skip_ingestion,
        },
        "paths": {
            "raw_data": str(raw_data),
            "doc_output_dir": str(PROCESSED_DIR),
            "vector_store": str(STORE_DIR),
            "output_dir": str(output_base),
            "auto_increment_output": False,
        },
        "llm": {
            "model": "${LLM_MODEL}",
            "temperature": 0,
            "base_url": "${LLM_BASE_URL}",
            "api_key": "${LLM_API_KEY}",
        },
    }


def write_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def find_complete_output(stage: Path, expected: int) -> Path | None:
    outputs = []
    stable = stage / "output"
    if stable.is_dir():
        outputs.append(stable)
    outputs.extend(
        sorted(stage.glob("output_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    )
    for output in outputs:
        generated = output / "generated_answers.json"
        if not generated.exists():
            continue
        try:
            if len(load_json(generated).get("results", [])) == expected:
                return output
        except Exception:
            continue
    return None


def run_index(values: dict[str, str]) -> None:
    marker = INDEX_DIR / "INDEX_COMPLETE.json"
    manifest = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
    if marker.exists():
        old = load_json(marker)
        if old.get("split_manifest_sha256") == sha256_file(SPLIT_DIR / "SPLIT_MANIFEST.json"):
            say("[复用] Qasper联合语料索引已经完成。")
            return
        raise RuntimeError("索引与当前划分不一致；为避免误删，不自动覆盖，请检查data/index。")

    stage = ROOT / "runs" / "index_build"
    config_path = stage / "config.yaml"
    write_config(
        config_path,
        make_config(
            SPLIT_DIR / "corpus.json",
            stage / "output",
            0,
            skip_ingestion=False,
        ),
    )
    say(f"[建库] {manifest['paper_counts']['total']}篇论文；原始Data保持只读……")
    result = subprocess.run(
        [sys.executable, str(HARNESS), "--config", str(config_path), "--step", "gen"],
        cwd=str(REPO / "ov_test"),
        env=process_env(values, "student"),
    )
    if result.returncode != 0:
        raise RuntimeError("Qasper索引构建失败。")
    save_json(
        marker,
        {
            "split_manifest_sha256": sha256_file(SPLIT_DIR / "SPLIT_MANIFEST.json"),
            "source_sha256": manifest["source_sha256"],
            "paper_count": manifest["paper_counts"]["total"],
        },
    )


def run_arm(
    label: str,
    stage_root: Path,
    raw_data: Path,
    expected: int,
    values: dict[str, str],
    *,
    candidate_enabled: bool = False,
    candidate_path: Path | None = None,
    inventory_path: Path | None = None,
    instructions: list[str] | None = None,
    gate_enabled: bool = False,
    gate_path: Path | None = None,
) -> Path:
    stage = stage_root / label
    stage.mkdir(parents=True, exist_ok=True)
    complete = find_complete_output(stage, expected)
    if complete:
        say(f"[复用] {label} 已完成：{complete}")
        return complete
    config_path = stage / "config.yaml"
    write_config(
        config_path,
        make_config(
            raw_data,
            stage / "output",
            expected,
            skip_ingestion=True,
            candidate_enabled=candidate_enabled,
            candidate_path=candidate_path,
            inventory_path=inventory_path,
            instructions=instructions,
            gate_enabled=gate_enabled,
            gate_path=gate_path,
        ),
    )
    say(f"[Student] {label}：{expected}题……")
    result = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "--config",
            str(config_path),
            "--step",
            "gen",
            "--skip-ingest",
        ],
        cwd=str(REPO / "ov_test"),
        env=process_env(values, "student"),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Student运行失败：{label}")
    complete = find_complete_output(stage, expected)
    if complete is None:
        raise RuntimeError(f"Student没有生成完整答案：{label}")
    return complete


def answer_map(output: Path) -> dict[str, dict[str, Any]]:
    rows = load_json(output / "generated_answers.json").get("results", [])
    return {str(row["question"]): row for row in rows}


def judge_prompt(question: str, golds: list[str], answer: str) -> str:
    return f'''Evaluate a generated answer for Qasper scientific-paper QA (0-4).
Any listed gold answer may be acceptable because annotators can phrase answers differently.
Accept semantic equivalence. Penalize unsupported core claims and wrong yes/no polarity.
4: fully correct; 3: correct but somewhat incomplete; 2: partially correct; 1: mostly wrong; 0: wrong/refusal.

Question: {question}
Acceptable gold answers: {json.dumps(golds, ensure_ascii=False)}
Generated answer: {answer}

Respond ONLY with JSON: {{"score": 0, "reasoning": "one sentence"}}'''


def judge(
    label: str,
    rows: list[dict[str, Any]],
    answers: dict[str, dict[str, Any]],
    path: Path,
    values: dict[str, str],
) -> list[dict[str, Any]]:
    saved: dict[str, dict[str, Any]] = {}
    if path.exists():
        payload = load_json(path)
        if payload.get("judge_model") == values["JUDGE_MODEL"]:
            saved = {str(row["case_id"]): row for row in payload.get("results", [])}
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        case_id = str(row["question_id"])
        if case_id in saved:
            results.append(saved[case_id])
            continue
        generated = answers[row["question"]]
        student_answer = str((generated.get("llm") or {}).get("final_answer") or "")
        say(f"[Judge:{label}] {index}/{len(rows)}")
        evaluation = legacy.model_json_call(
            values["JUDGE_BASE_URL"],
            values.get("JUDGE_API_KEY") or values.get("VOLCENGINE_API_KEY") or "",
            values["JUDGE_MODEL"],
            [
                {"role": "system", "content": "You are a strict Qasper evaluator."},
                {
                    "role": "user",
                    "content": judge_prompt(row["question"], row["gold_answers"], student_answer),
                },
            ],
            temperature=0,
            max_tokens=1000,
        )
        score = max(0, min(4, int(evaluation.get("score", 0))))
        record = {
            "case_id": case_id,
            "paper_id": row["paper_id"],
            "question": row["question"],
            "gold_answers": row["gold_answers"],
            "student_answer": student_answer,
            "score": score,
            "judge_reasoning": str(evaluation.get("reasoning") or ""),
            "input_tokens": int((generated.get("token_usage") or {}).get("total_input_tokens", 0)),
            "output_tokens": int((generated.get("token_usage") or {}).get("llm_output_tokens", 0)),
            "latency_sec": float((generated.get("retrieval") or {}).get("latency_sec", 0)),
            "recall": float((generated.get("metrics") or {}).get("Recall", 0)),
        }
        results.append(record)
        save_json(path, {"judge_model": values["JUDGE_MODEL"], "results": results})
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
    before = {str(row["case_id"]): row for row in baseline}
    after = {str(row["case_id"]): row for row in candidate}
    details = []
    for case_id, old in before.items():
        new = after[case_id]
        details.append(
            {
                "case_id": case_id,
                "paper_id": old["paper_id"],
                "question": old["question"],
                "baseline_score": old["score"],
                "candidate_score": new["score"],
                "delta": new["score"] - old["score"],
            }
        )
    return {
        "wins": sum(row["delta"] > 0 for row in details),
        "ties": sum(row["delta"] == 0 for row in details),
        "losses": sum(row["delta"] < 0 for row in details),
        "net_score": sum(row["delta"] for row in details),
        "details": details,
    }


def validate_candidate(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_imports = {"re", "math", "json", "collections", "typing", "dataclasses"}
    forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    # Only module-level functions form the tool's public API. Nested helpers are
    # implementation details and must not be rejected merely for lacking a
    # leading underscore.
    public = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
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
    if public != ["run"]:
        problems.append(f"public functions must equal ['run']; got {public}")
    if problems:
        raise RuntimeError("候选工具未通过安全检查：" + "; ".join(sorted(set(problems))))


def load_candidate_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("qasper_generated_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法载入候选工具。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_candidate_tests(
    module: Any, candidate: dict[str, Any], *, strict: bool = True
) -> list[dict[str, Any]]:
    results = []
    for test in candidate.get("tests") or []:
        output = module.run(
            str(test.get("question") or ""),
            list(test.get("corpus") or []),
            int(test.get("top_k") or 5),
        )
        first = (output.get("results") or [{}])[0]
        actual_doc = str(first.get("doc_id") or "")
        actual_node = str(first.get("node_id") or "")
        expected_doc = str(test.get("expected_top_doc_id") or "")
        expected_node = str(test.get("expected_top_node_id") or "")
        passed = bool(expected_doc and actual_doc == expected_doc)
        if expected_node:
            passed = passed and actual_node == expected_node
        results.append(
            {
                "name": test.get("name"),
                "passed": passed,
                "expected_doc": expected_doc,
                "actual_doc": actual_doc,
                "expected_node": expected_node or None,
                "actual_node": actual_node or None,
            }
        )
    if strict and (not results or not all(row["passed"] for row in results)):
        raise RuntimeError(f"候选工具自生成测试未全部通过：{results}")
    return results


def candidate_policy(candidate: dict[str, Any]) -> list[str]:
    policy = candidate.get("usage_policy") or {}
    labels = {
        "when_to_call": "When to call generated_corpus_search",
        "how_to_use_output": "How to use its output",
        "fallback": "Fallback",
        "stopping_rule": "Stopping rule",
    }
    return [
        f"{labels[key]}: {policy[key]}"
        for key in labels
        if str(policy.get(key) or "").strip()
    ]
