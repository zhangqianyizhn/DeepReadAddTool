from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve()
_V2_HERE = HERE
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
SOURCE_COMMON = WORKSPACE / "agentic_rag_tool_evolution_qasper" / "scripts" / "common.py"

spec = importlib.util.spec_from_file_location("qasper_v1_shared_common", SOURCE_COMMON)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load shared experiment utilities: {SOURCE_COMMON}")
_shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_shared)

RAW_QASPER = (
    WORKSPACE
    / "Data"
    / "Qasper_official_v0.3"
    / "qasper-train-v0.3.json"
)
SPLIT_DIR = ROOT / "data" / "splits"
INDEX_DIR = ROOT / "data" / "index"
PROCESSED_DIR = INDEX_DIR / "processed_docs"
STORE_DIR = INDEX_DIR / "store_index"
CANONICAL_UNITS = ROOT / "data" / "canonical_units.json"
RUNS_DIR = ROOT / "runs"

# Rebind the shared functions to this experiment's isolated paths. Function globals
# live in the loaded module, so no old data or result path is reachable by accident.
for _name, _value in {
    "ROOT": ROOT,
    "RAW_QASPER": RAW_QASPER,
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

# Restore the v2 constants after exporting the shared module namespace.
HERE = _V2_HERE
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
RAW_QASPER = WORKSPACE / "Data" / "Qasper_official_v0.3" / "qasper-train-v0.3.json"
SPLIT_DIR = ROOT / "data" / "splits"
INDEX_DIR = ROOT / "data" / "index"
PROCESSED_DIR = INDEX_DIR / "processed_docs"
STORE_DIR = INDEX_DIR / "store_index"
CANONICAL_UNITS = ROOT / "data" / "canonical_units.json"
RUNS_DIR = ROOT / "runs"

_original_make_config = _shared.make_config


def make_config(*args: Any, **kwargs: Any) -> dict[str, Any]:
    config = _original_make_config(*args, **kwargs)
    config["project_name"] = "AutonomousSingleToolBlindReplication"
    config["dataset_name"] = "QasperTrainCanonicalPaperDisjoint"
    return config


# The shared run_index/run_arm resolve make_config through their module globals.
_shared.make_config = make_config


def run_candidate_tests(
    module: Any, candidate: dict[str, Any], *, strict: bool = True
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for test in candidate.get("tests") or []:
        output = module.run(
            str(test.get("question") or ""),
            list(test.get("corpus") or []),
            int(test.get("top_k") or 5),
        )
        if not isinstance(output, dict):
            output = {}
        first = (output.get("results") or [{}])[0]
        actual = {
            "doc_id": str(first.get("doc_id") or ""),
            "node_id": str(first.get("node_id") or ""),
            "unit_index": str(
                first.get("unit_index")
                if first.get("unit_index") is not None
                else first.get("page_number") or ""
            ),
        }
        expected = {
            "doc_id": str(test.get("expected_top_doc_id") or ""),
            "node_id": str(test.get("expected_top_node_id") or ""),
            "unit_index": str(
                test.get("expected_top_unit_index")
                if test.get("expected_top_unit_index") is not None
                else test.get("expected_top_page_number") or ""
            ),
        }
        passed = bool(expected["doc_id"] and actual["doc_id"] == expected["doc_id"])
        for key in ("node_id", "unit_index"):
            if expected[key]:
                passed = passed and actual[key] == expected[key]
        results.append(
            {
                "name": test.get("name"),
                "passed": passed,
                "expected": expected,
                "actual": actual,
            }
        )
    if strict and (not results or not all(row["passed"] for row in results)):
        raise RuntimeError(f"Candidate self-tests did not all pass: {results}")
    return results


_shared.run_candidate_tests = run_candidate_tests
