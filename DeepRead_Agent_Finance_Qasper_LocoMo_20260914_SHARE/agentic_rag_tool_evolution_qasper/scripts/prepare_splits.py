from __future__ import annotations

import argparse
import copy
import random
from pathlib import Path
from typing import Any

from common import RAW_QASPER, SPLIT_DIR, load_json, save_json, save_jsonl, sha256_file


TARGETS = {"train": 60, "dev": 20, "test": 80}


def answerable(q: dict[str, Any]) -> bool:
    answers = q.get("answers") or []
    return bool(answers) and not all(
        wrapper.get("answer", {}).get("unanswerable", False) for wrapper in answers
    )


def golds(q: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for wrapper in q.get("answers") or []:
        obj = wrapper.get("answer") or {}
        if obj.get("unanswerable", False):
            value = "Not mentioned"
        else:
            spans = [str(v).strip() for v in obj.get("extractive_spans") or [] if str(v).strip()]
            free = str(obj.get("free_form_answer") or "").strip()
            yes_no = obj.get("yes_no")
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
    raise RuntimeError(f"无法按论文隔离凑出精确{target}题。")


def filtered_paper(paper: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(paper)
    result["qas"] = [qa for qa in paper.get("qas") or [] if answerable(qa)]
    return result


def flatten(split: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
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
                    "gold_answers": golds(qa),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    source = load_json(RAW_QASPER)
    counts = {
        paper_id: sum(answerable(qa) for qa in paper.get("qas") or [])
        for paper_id, paper in source.items()
    }
    candidates = [paper_id for paper_id, count in counts.items() if count > 0]
    rng = random.Random(args.seed)
    remaining = set(candidates)
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
    for name, target in TARGETS.items():
        if len(flattened[name]) != target:
            raise AssertionError(f"{name}题数错误：{len(flattened[name])} != {target}")
    if any(set(selected[a]) & set(selected[b]) for a in TARGETS for b in TARGETS if a < b):
        raise AssertionError("论文级划分发生重叠。")

    corpus: dict[str, dict[str, Any]] = {}
    for split in splits.values():
        corpus.update(split)
    manifest = {
        "dataset": "Qasper dev-v0.3",
        "source": str(RAW_QASPER),
        "source_sha256": sha256_file(RAW_QASPER),
        "seed": args.seed,
        "split_unit": "paper_id",
        "targets": TARGETS,
        "question_counts": {name: len(rows) for name, rows in flattened.items()},
        "paper_counts": {
            **{name: len(ids) for name, ids in selected.items()},
            "total": len(corpus),
        },
        "paper_ids": selected,
        "leakage_rule": (
            "Analyzer/Repair may read train trajectories and then dev feedback only. "
            "Test questions, gold answers, trajectories and reports stay sealed until tool freeze."
        ),
    }

    if args.verify_only:
        old = load_json(SPLIT_DIR / "SPLIT_MANIFEST.json")
        if old != manifest:
            raise RuntimeError("现有划分与确定性重算结果不一致。")
        print("[验证通过] 60/20/80题，论文级零重叠。")
        return 0

    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    for name in TARGETS:
        save_json(SPLIT_DIR / f"{name}.json", splits[name])
        save_jsonl(SPLIT_DIR / f"{name}_questions.jsonl", flattened[name])
    save_json(SPLIT_DIR / "corpus.json", corpus)
    save_json(SPLIT_DIR / "SPLIT_MANIFEST.json", manifest)
    print(
        "[划分完成] "
        + "，".join(
            f"{name}={len(flattened[name])}题/{len(selected[name])}篇"
            for name in TARGETS
        )
        + "；论文级零重叠。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
