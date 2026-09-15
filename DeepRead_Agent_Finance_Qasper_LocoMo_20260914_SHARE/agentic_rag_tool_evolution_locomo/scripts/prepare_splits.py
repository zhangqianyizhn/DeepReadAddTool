from __future__ import annotations

import copy
import itertools
import math
from collections import Counter
from typing import Any

from common import RAW_LOCOMO, SPLIT_DIR, load_json, save_json, save_jsonl, sha256_file


DOCUMENT_TARGETS = {"train": 6, "dev": 2, "test": 2}
QUESTION_TARGETS = {"train": 160, "dev": 40, "test": 100}


def qa_id(sample_id: str, index: int, qa: dict[str, Any]) -> str:
    return str(qa.get("id") or f"{sample_id}::q{index:04d}")


def valid_qas(item: dict[str, Any]) -> list[dict[str, Any]]:
    sample_id = str(item.get("sample_id") or "unknown")
    result: list[dict[str, Any]] = []
    for index, qa in enumerate(item.get("qa") or []):
        if str(qa.get("category")) == "5":
            continue
        cloned = copy.deepcopy(qa)
        cloned["id"] = qa_id(sample_id, index, qa)
        result.append(cloned)
    return result


def stats(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(qa.get("category")) for item in items for qa in valid_qas(item))


def split_documents(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_id = {str(item["sample_id"]): item for item in items}
    ids = sorted(by_id)
    total = stats(items)

    def deviation(chosen: tuple[str, ...], ratio: float) -> float:
        current = stats([by_id[value] for value in chosen])
        return sum(
            ((current[category] - count * ratio) / max(1.0, count * ratio)) ** 2
            for category, count in total.items()
        )

    train_tuple = min(
        itertools.combinations(ids, DOCUMENT_TARGETS["train"]),
        key=lambda chosen: (deviation(chosen, 0.6), chosen),
    )
    remaining = sorted(set(ids) - set(train_tuple))
    remaining_total = stats([by_id[value] for value in remaining])

    def dev_deviation(chosen: tuple[str, ...]) -> float:
        current = stats([by_id[value] for value in chosen])
        return sum(
            ((current[category] - count * 0.5) / max(1.0, count * 0.5)) ** 2
            for category, count in remaining_total.items()
        )

    dev_tuple = min(
        itertools.combinations(remaining, DOCUMENT_TARGETS["dev"]),
        key=lambda chosen: (dev_deviation(chosen), chosen),
    )
    test_tuple = tuple(sorted(set(remaining) - set(dev_tuple)))
    return {
        "train": [by_id[value] for value in train_tuple],
        "dev": [by_id[value] for value in dev_tuple],
        "test": [by_id[value] for value in test_tuple],
    }


def sample_items(items: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    strata: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        sample_id = str(item["sample_id"])
        for qa in valid_qas(item):
            strata.setdefault((sample_id, str(qa.get("category"))), []).append(qa)
    total = sum(len(rows) for rows in strata.values())
    if target > total:
        raise RuntimeError(f"Requested {target} questions from only {total} available.")
    allocation: dict[tuple[str, str], int] = {}
    fractions: list[tuple[float, tuple[str, str]]] = []
    assigned = 0
    for key, rows in strata.items():
        exact = len(rows) * target / total
        base = min(len(rows), math.floor(exact))
        allocation[key] = base
        assigned += base
        fractions.append((exact - base, key))
    for _, key in sorted(fractions, key=lambda pair: (-pair[0], pair[1])):
        if assigned >= target:
            break
        if allocation[key] < len(strata[key]):
            allocation[key] += 1
            assigned += 1
    if assigned != target:
        raise RuntimeError("Could not allocate the deterministic stratified sample.")

    selected_by_doc: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(strata):
        sample_id, _ = key
        rows = sorted(strata[key], key=lambda qa: str(qa["id"]))
        selected_by_doc.setdefault(sample_id, []).extend(rows[: allocation[key]])
    sampled: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: str(row["sample_id"])):
        result = copy.deepcopy(item)
        result["qa"] = sorted(
            selected_by_doc.get(str(item["sample_id"]), []), key=lambda qa: str(qa["id"])
        )
        sampled.append(result)
    return sampled


def full_item(item: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(item)
    result["qa"] = valid_qas(item)
    return result


def flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        sample_id = str(item.get("sample_id") or "unknown")
        for qa in item.get("qa") or []:
            raw = qa.get("answer")
            if isinstance(raw, list):
                golds = [str(value) for value in raw]
            else:
                golds = [str(raw if raw not in (None, "") else "Not mentioned")]
            rows.append(
                {
                    "sample_id": sample_id,
                    "question_id": str(qa["id"]),
                    "question": str(qa.get("question") or ""),
                    "gold_answers": golds,
                    "category": str(qa.get("category") or ""),
                    "evidence_ids": list(qa.get("evidence") or []),
                }
            )
    return rows


def main() -> int:
    source = load_json(RAW_LOCOMO)
    if not isinstance(source, list) or len(source) != 10:
        raise RuntimeError("Expected the canonical ten-conversation LocoMo source.")
    document_splits = split_documents(source)
    splits = {
        name: sample_items(document_splits[name], QUESTION_TARGETS[name])
        for name in QUESTION_TARGETS
    }
    flattened = {name: flatten(items) for name, items in splits.items()}
    ids = {
        name: {str(item["sample_id"]) for item in items}
        for name, items in document_splits.items()
    }
    pairs = (("train", "dev"), ("train", "test"), ("dev", "test"))
    if any(ids[left] & ids[right] for left, right in pairs):
        raise RuntimeError("Conversation overlap detected.")
    manifest = {
        "dataset": "LocoMo",
        "source": str(RAW_LOCOMO),
        "source_sha256": sha256_file(RAW_LOCOMO),
        "split_unit": "conversation/sample_id",
        "question_sampling": "deterministic proportional allocation over conversation x official category",
        "question_counts": QUESTION_TARGETS,
        "paper_counts": {**DOCUMENT_TARGETS, "total": len(source)},
        "conversation_ids": {name: sorted(values) for name, values in ids.items()},
        "category_counts": {
            name: dict(Counter(row["category"] for row in rows))
            for name, rows in flattened.items()
        },
        "leakage_rule": (
            "Analyzer selects one capability from train trajectories. Dev feedback may repair that same tool exactly once "
            "and select v1 or v2. The selected candidate and policy are frozen before the one-time test A/B."
        ),
        "retrieval_rule": "All questions search the same complete ten-conversation corpus.",
    }
    manifest_path = SPLIT_DIR / "SPLIT_MANIFEST.json"
    if manifest_path.exists():
        if load_json(manifest_path) != manifest:
            raise RuntimeError("Refusing to overwrite a different preregistered LocoMo V2 split.")
        print("[REUSE] LocoMo V2 deterministic 160/40/100 split.")
        return 0
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    for name in QUESTION_TARGETS:
        save_json(SPLIT_DIR / f"{name}.json", splits[name])
        save_jsonl(SPLIT_DIR / f"{name}_questions.jsonl", flattened[name])
    save_json(SPLIT_DIR / "corpus.json", [full_item(item) for item in source])
    save_json(manifest_path, manifest)
    print("[SPLIT] train=160/6 conversations; dev=40/2; test=100/2; overlap=0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
