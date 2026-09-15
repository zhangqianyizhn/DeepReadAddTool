from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
SOURCE_COMMON = WORKSPACE / "agentic_rag_tool_evolution_qasper" / "scripts" / "common.py"

spec = importlib.util.spec_from_file_location("locomo_shared_common", SOURCE_COMMON)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load shared experiment utilities: {SOURCE_COMMON}")
_shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_shared)

RAW_LOCOMO = WORKSPACE / "Data" / "Locomo" / "Locomo.json"
SPLIT_DIR = ROOT / "data_v2" / "splits"
INDEX_DIR = ROOT / "data_v2" / "index"
PROCESSED_DIR = INDEX_DIR / "processed_docs"
STORE_DIR = INDEX_DIR / "store_index"
CANONICAL_UNITS = ROOT / "data_v2" / "canonical_units.json"
RUNS_DIR = ROOT / "runs_v2"

for _name, _value in {
    "ROOT": ROOT,
    "RAW_QASPER": RAW_LOCOMO,
    "SPLIT_DIR": SPLIT_DIR,
    "INDEX_DIR": INDEX_DIR,
    "PROCESSED_DIR": PROCESSED_DIR,
    "STORE_DIR": STORE_DIR,
    "PDF_PAGES": CANONICAL_UNITS,
    "RUNS_DIR": RUNS_DIR,
}.items():
    setattr(_shared, _name, _value)

for _name in dir(_shared):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_shared, _name)

# Restore experiment-local constants after exporting shared names.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
RAW_LOCOMO = WORKSPACE / "Data" / "Locomo" / "Locomo.json"
SPLIT_DIR = ROOT / "data_v2" / "splits"
INDEX_DIR = ROOT / "data_v2" / "index"
PROCESSED_DIR = INDEX_DIR / "processed_docs"
STORE_DIR = INDEX_DIR / "store_index"
CANONICAL_UNITS = ROOT / "data_v2" / "canonical_units.json"
RUNS_DIR = ROOT / "runs_v2"


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
        "project_name": "AutonomousSingleToolLocomo",
        "dataset_name": "LocomoConversationDisjoint",
        "adapter": {
            "module": "src.adapters.locomo_adapter",
            "class_name": "LocomoAdapter",
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
            "generated_corpus_inventory_path": (
                str(inventory_path or CANONICAL_UNITS) if candidate_enabled else ""
            ),
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


_shared.make_config = make_config


def judge_prompt(question: str, golds: list[str], answer: str) -> str:
    return f'''Evaluate a generated answer for LocoMo long-term conversational-memory QA on a 0-4 scale.
Accept semantic equivalence and reasonable approximate dates when the gold is relative. For list questions,
penalize important omissions; for inference questions, accept only conclusions supported by the conversation.
4: fully correct; 3: correct but slightly incomplete/imprecise; 2: partially correct; 1: mostly wrong; 0: wrong/refusal.

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
                {"role": "system", "content": "You are a strict LocoMo evaluator."},
                {
                    "role": "user",
                    "content": judge_prompt(
                        row["question"], row["gold_answers"], student_answer
                    ),
                },
            ],
            temperature=0,
            max_tokens=1000,
        )
        score = max(0, min(4, int(evaluation.get("score", 0))))
        record = {
            "case_id": case_id,
            "paper_id": row["sample_id"],
            "question": row["question"],
            "gold_answers": row["gold_answers"],
            "student_answer": student_answer,
            "score": score,
            "judge_reasoning": str(evaluation.get("reasoning") or ""),
            "category": row.get("category"),
            "input_tokens": int(
                (generated.get("token_usage") or {}).get("total_input_tokens", 0)
            ),
            "output_tokens": int(
                (generated.get("token_usage") or {}).get("llm_output_tokens", 0)
            ),
            "latency_sec": float(
                (generated.get("retrieval") or {}).get("latency_sec", 0)
            ),
            "recall": float((generated.get("metrics") or {}).get("Recall", 0)),
        }
        results.append(record)
        save_json(path, {"judge_model": values["JUDGE_MODEL"], "results": results})
    return results


_shared.judge_prompt = judge_prompt
_shared.judge = judge
