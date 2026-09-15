from __future__ import annotations

import argparse
import copy
import random
from collections import Counter
from typing import Any

from common import RAW_QASPER, SPLIT_DIR, load_json, save_json, save_jsonl, sha256_file


TARGETS = {"train": 100, "dev": 40, "test": 120}
DEFAULT_SEED = 20260823


def answerable(qa: dict[str, Any]) -> bool:
    answers = qa.get("answers") or []
    return bool(answers) and not all(
        wrapper.get("answer", {}).get("unanswerable", False)
        for wrapper in answers
    )


def answer_type(qa: dict[str, Any]) -> str:
    kinds: set[str] = set()
    for wrapper in qa.get("answers") or []:
        answer = wrapper.get("answer") or {}
        if answer.get("unanswerable", False):
            kinds.add("unanswerable")
        elif answer.get("extractive_spans"):
            kinds.add("extractive")
        elif str(answer.get("free_form_answer") or "").strip():
            kinds.add("free_form")
        elif answer.get("yes_no") is not None:
            kinds.add("yes_no")
    return "+".join(sorted(kinds)) or "unknown"


def golds(qa: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for wrapper in qa.get("answers") or []:
        answer = wrapper.get("answer") or {}
        if answer.get("unanswerable", False):
            value = "Not mentioned"
        else:
            spans = [
                str(item).strip()
                for item in answer.get("extractive_spans") or []
                if str(item).strip()
            ]
            free = str(answer.get("free_form_answer") or "").strip()
            yes_no = answer.get("yes_no")
            if spans:
                value = "; ".join(spans)
            elif free:
                value = free
            elif yes_no is not None:
                value = "Yes" if yes_no else "No"
            else:
                continue
        if value not in result:
            result.append(value)
    return result or ["Not mentioned"]


def select_exact(
    paper_ids: list[str], counts: dict[str, int], target: int, rng: random.Random
) -> list[str]:
    shuffled = list(paper_ids)
    rng.shuffle(shuffled)
    reachable: dict[int, list[str]] = {0: []}
    for paper_id in shuffled:
        count = counts[paper_id]
        for total, chosen in list(reachable.items())[::-1]:
            new_total = total + count
            if new_total <= target and new_total not in reachable:
                reachable[new_total] = chosen + [paper_id]
        if target in reachable:
            return reachable[target]
    raise RuntimeError(f"Cannot make an exact paper-disjoint split of {target} questions.")


def filtered_paper(paper: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(paper)
    result["qas"] = [qa for qa in paper.get("qas") or [] if answerable(qa)]
    return result


def flatten(split: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper_id, paper in split.items():
        title = str(paper.get("title") or "Unknown Title")
        for qa in paper.get("qas") or []:
            raw_question = str(qa.get("question") or "")
            rows.append(
                {
                    "paper_id": paper_id,
                    "paper_title": title,
                    "question_id": str(qa.get("question_id") or ""),
                    "question": f'Based on the paper "{title}", {raw_question}',
                    "raw_question": raw_question,
                    "answer_type": answer_type(qa),
                    "gold_answers": golds(qa),
                }
            )
    return rows


def build(seed: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    source = load_json(RAW_QASPER)
    counts = {
        paper_id: sum(answerable(qa) for qa in paper.get("qas") or [])
        for paper_id, paper in source.items()
    }
    remaining = {paper_id for paper_id, count in counts.items() if count > 0}
    rng = random.Random(seed)
    selected: dict[str, list[str]] = {}
    for name, target in TARGETS.items():
        chosen = select_exact(sorted(remaining), counts, target, rng)
        selected[name] = chosen
        remaining.difference_update(chosen)
    splits = {
        name: {paper_id: filtered_paper(source[paper_id]) for paper_id in ids}
        for name, ids in selected.items()
    }
    flattened = {name: flatten(split) for name, split in splits.items()}
    corpus: dict[str, dict[str, Any]] = {}
    for split in splits.values():
        corpus.update(split)
    manifest = {
        "dataset": "Qasper train-v0.3 canonical text",
        "source": str(RAW_QASPER),
        "source_sha256": sha256_file(RAW_QASPER),
        "seed": seed,
        "split_unit": "paper_id",
        "targets": TARGETS,
        "question_counts": {name: len(rows) for name, rows in flattened.items()},
        "paper_counts": {
            **{name: len(ids) for name, ids in selected.items()},
            "total": len(corpus),
        },
        "answer_type_counts": {
            name: dict(Counter(row["answer_type"] for row in rows))
            for name, rows in flattened.items()
        },
        "paper_ids": selected,
        "leakage_rule": (
            "Analyzer and Repair may receive train trajectories only. Dev is evaluation-only. "
            "Test remains sealed until the candidate and policy are frozen. Old experiment artifacts are never prompt inputs."
        ),
        "representation_rule": "Only canonical Qasper JSON text; no PDF files or PDF text extraction.",
    }
    return manifest, splits, flattened


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest, splits, flattened = build(args.seed)
    for name, target in TARGETS.items():
        if len(flattened[name]) != target:
            raise AssertionError(f"Wrong {name} question count.")
    paper_sets = {name: set(manifest["paper_ids"][name]) for name in TARGETS}
    for left in TARGETS:
        for right in TARGETS:
            if left < right and paper_sets[left] & paper_sets[right]:
                raise AssertionError("Paper overlap detected.")
    manifest_path = SPLIT_DIR / "SPLIT_MANIFEST.json"
    if args.verify_only:
        if not manifest_path.exists() or load_json(manifest_path) != manifest:
            raise RuntimeError("Existing split differs from deterministic preregistration.")
        print("[VERIFY] 100/40/120 questions; paper overlap=0.")
        return 0
    if manifest_path.exists():
        if load_json(manifest_path) != manifest:
            raise RuntimeError("Refusing to overwrite a different preregistered split.")
        print("[REUSE] Deterministic split already exists.")
        return 0
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    corpus: dict[str, dict[str, Any]] = {}
    for name in TARGETS:
        save_json(SPLIT_DIR / f"{name}.json", splits[name])
        save_jsonl(SPLIT_DIR / f"{name}_questions.jsonl", flattened[name])
        corpus.update(splits[name])
    save_json(SPLIT_DIR / "corpus.json", corpus)
    save_json(manifest_path, manifest)
    print(
        "[SPLIT] "
        + ", ".join(
            f"{name}={len(flattened[name])}q/{len(manifest['paper_ids'][name])}papers"
            for name in TARGETS
        )
        + "; paper overlap=0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

