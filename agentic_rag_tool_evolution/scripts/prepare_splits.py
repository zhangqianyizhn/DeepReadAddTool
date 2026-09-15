"""为 HotpotQA / SyllabusQA 生成固定的 train/dev/test 划分（40%/20%/40%）。

- HotpotQA：100 题，按题随机划分 40/20/40。注意其多跳问题共享 Wikipedia 文章，
  无法做到文档级不相交，这一点写入 manifest 供报告引用。
- SyllabusQA：4358 题先按大纲分层抽样 200 题（剔除 "no answer" 题型，adapter 无法评分），
  再按大纲（syllabus_name）doc-disjoint 划分为 80/40/80。
- 两个数据集的划分都是确定性的（固定 seed），重复运行结果一致；已存在且内容一致时直接复用。

产物（均在 agentic_rag_tool_evolution/data/splits/<dataset>/）：
    harness_{train,dev,test}.<json|csv>   adapter 可直接消费的分割文件
    {train,dev,test}.jsonl                归一化行（chain 脚本使用，由 profile loader 派生校验）
    SPLIT_MANIFEST.json                   seed、数量、文档数、哈希
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import dataset_profiles as profiles  # noqa: E402

SEED = 20260909


def say(message: str) -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- hotpotqa

def prepare_hotpotqa(profile: profiles.DatasetProfile) -> dict[str, Any]:
    qa_data = profiles.load_json(profile.raw_data)
    if len(qa_data) != profile.total_count:
        raise RuntimeError(f"HotpotQA 应为 {profile.total_count} 题，实际 {len(qa_data)} 题。")

    rng = random.Random(SEED)
    shuffled = qa_data[:]
    rng.shuffle(shuffled)
    splits = {
        "train": shuffled[: profile.train_count],
        "dev": shuffled[profile.train_count : profile.train_count + profile.dev_count],
        "test": shuffled[profile.train_count + profile.dev_count :],
    }
    assert sum(len(v) for v in splits.values()) == profile.total_count

    # 入库需要覆盖全部问题引用的文章，统计文档数供索引完整性校验
    all_titles = {
        title for item in qa_data for title in item.get("context", {}).get("title", [])
    }

    for split, rows in splits.items():
        profiles.save_json(profile.splits_dir / f"harness_{split}.json", rows)
    manifest = {
        "dataset": "hotpotqa",
        "seed": SEED,
        "ratio": "40/20/40",
        "question_counts": {key: len(value) for key, value in splits.items()},
        "doc_count": len(all_titles),
        "doc_disjoint": False,
        "doc_disjoint_note": "HotpotQA 多跳问题共享 Wikipedia 文章，划分为题目级随机，跨 split 存在文章重叠。",
    }
    return manifest


# ---------------------------------------------------------------- syllabusqa

def _load_all_syllabus_rows(raw_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for csv_name in ("train.csv", "val.csv", "test.csv"):
        path = raw_dir / csv_name
        if not path.exists():
            raise FileNotFoundError(f"缺少 {path}")
        with path.open("r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("question_type") == "no answer":
                    continue  # adapter 同样跳过，无法评分
                row["original_split"] = csv_name.removesuffix(".csv")
                rows.append(row)
    return rows


def prepare_syllabusqa(profile: profiles.DatasetProfile) -> dict[str, Any]:
    pool = _load_all_syllabus_rows(profile.raw_data)
    rng = random.Random(SEED)

    # 1. 按大纲分层抽样 200 题：大纲内打乱后轮转领取，保证每个大纲尽量有代表
    by_syllabus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool:
        by_syllabus[row["syllabus_name"]].append(row)
    syllabi = sorted(by_syllabus)
    rng.shuffle(syllabi)
    for rows in by_syllabus.values():
        rng.shuffle(rows)

    sampled: list[dict[str, Any]] = []
    cursor = 0
    while len(sampled) < profile.total_count:
        name = syllabi[cursor % len(syllabi)]
        cursor += 1
        if by_syllabus[name]:
            sampled.append(by_syllabus[name].pop())
        if not any(by_syllabus.values()):
            raise RuntimeError("可用题目不足 200。")

    # 2. 按大纲 doc-disjoint 划分 80/40/80：大纲整体分配，贪心补齐目标题数
    sampled_by_syllabus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sampled:
        sampled_by_syllabus[row["syllabus_name"]].append(row)
    groups = sorted(sampled_by_syllabus.items())
    rng.shuffle(groups)

    targets = {"train": profile.train_count, "dev": profile.dev_count, "test": profile.test_count}
    assignment: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    for name, rows in groups:
        # 分配给"缺口比例最大"的 split
        split = max(
            targets,
            key=lambda key: (targets[key] - len(assignment[key])) / targets[key],
        )
        assignment[split].extend(rows)

    for split, rows in assignment.items():
        path = profile.splits_dir / f"harness_{split}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=profiles.SYLLABUS_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in profiles.SYLLABUS_COLUMNS})

    # baseline 入库需要覆盖全部 200 题涉及的大纲：写一份合并文件
    all_path = profile.splits_dir / "harness_all.csv"
    with all_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=profiles.SYLLABUS_COLUMNS)
        writer.writeheader()
        for row in sampled:
            writer.writerow({key: row.get(key, "") for key in profiles.SYLLABUS_COLUMNS})

    manifest = {
        "dataset": "syllabusqa",
        "seed": SEED,
        "ratio": "40/20/40",
        "pool_size": len(pool),
        "sampled": profile.total_count,
        "question_counts": {key: len(value) for key, value in assignment.items()},
        "doc_count": len(sampled_by_syllabus),
        "doc_disjoint": True,
        "doc_disjoint_note": "按 syllabus_name 整体分配，同一大纲不会跨 split。",
        "excluded_question_type": "no answer",
    }
    return manifest


# ---------------------------------------------------------------- 共用

def _greedy_assign(
    groups: list[tuple[str, list[Any]]], targets: dict[str, int]
) -> dict[str, list[tuple[str, Any]]]:
    """把 (文档名, 题目列表) 整体分配到目标题数的 split（doc-disjoint），保留文档名。"""
    assignment: dict[str, list[tuple[str, Any]]] = {key: [] for key in targets}
    for name, rows in groups:
        split = max(
            targets,
            key=lambda key: (targets[key] - len(assignment[key])) / targets[key],
        )
        assignment[split].extend((name, qa) for qa in rows)
    return assignment


def _write_json_splits(
    profile: profiles.DatasetProfile,
    assignment: dict[str, list[tuple[str, Any]]],
    docs_by_name: dict[str, Any],
    qa_key: str,
) -> None:
    """每个 split 写 harness 文件：文档完整内容 + 仅本 split 的 QA。
    qa_key="qa" 输出会话列表（locomo）；qa_key="qas" 输出论文 dict（qasper）。"""
    for split, pairs in assignment.items():
        by_doc: dict[str, list[Any]] = defaultdict(list)
        for name, qa in pairs:
            by_doc[name].append(qa)
        if qa_key == "qas":
            out: Any = {
                name: {**docs_by_name[name], "qas": qas}
                for name, qas in sorted(by_doc.items())
            }
        else:
            out = [
                {**docs_by_name[name], "qa": qas}
                for name, qas in sorted(by_doc.items())
            ]
        profiles.save_json(profile.splits_dir / f"harness_{split}.json", out)


# ---------------------------------------------------------------- locomo

def prepare_locomo(profile: profiles.DatasetProfile) -> dict[str, Any]:
    data = profiles.load_json(profile.raw_data)
    if not isinstance(data, list):
        data = [data]
    rng = random.Random(SEED)

    # 每个会话分层抽样（adapter 跳过 category 5，保持一致）
    per_conv = profile.total_count // len(data)
    sampled_conv: dict[str, list[dict[str, Any]]] = {}
    for item in data:
        sample_id = item.get("sample_id", "unknown")
        pool = [qa for qa in item.get("qa", []) if str(qa.get("category")) != "5"]
        rng.shuffle(pool)
        sampled_conv[sample_id] = pool[:per_conv]
    if sum(len(v) for v in sampled_conv.values()) < profile.total_count:
        raise RuntimeError(f"Locomo 可抽题目不足 {profile.total_count}。")

    # 会话整体 doc-disjoint 分配
    groups = sorted(sampled_conv.items())
    rng.shuffle(groups)
    targets = {"train": profile.train_count, "dev": profile.dev_count, "test": profile.test_count}
    assignment = _greedy_assign(groups, targets)

    docs_by_name = {item.get("sample_id", "unknown"): item for item in data}
    _write_json_splits(profile, assignment, docs_by_name, qa_key="qa")

    # baseline 文件：全部会话入库，QA 仅保留抽样题
    sampled_by_conv: dict[str, list[Any]] = defaultdict(list)
    for pairs in assignment.values():
        for name, qa in pairs:
            sampled_by_conv[name].append(qa)
    all_out = [
        {**item, "qa": sampled_by_conv.get(item.get("sample_id", "unknown"), [])}
        for item in data
    ]
    profiles.save_json(profile.splits_dir / "harness_all.json", all_out)

    return {
        "dataset": "locomo",
        "seed": SEED,
        "ratio": "40/20/40",
        "question_counts": {key: len(value) for key, value in assignment.items()},
        "doc_count": len(data),
        "doc_disjoint": True,
        "doc_disjoint_note": "按 sample_id（会话）整体分配，同一会话不跨 split。",
        "excluded_question_type": "category 5（adversarial，adapter 同样跳过）",
    }


# ---------------------------------------------------------------- qasper

def prepare_qasper(profile: profiles.DatasetProfile) -> dict[str, Any]:
    data = profiles.load_json(profile.raw_data)
    rng = random.Random(SEED)

    # 论文内打乱后可答题目轮转抽样
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for paper_id, paper in data.items():
        pool = [
            qa
            for qa in paper.get("qas", [])
            if not all(a.get("answer", {}).get("unanswerable", False) for a in qa.get("answers", []))
        ]
        rng.shuffle(pool)
        by_paper[paper_id] = pool
    papers = sorted(by_paper)
    rng.shuffle(papers)

    sampled: list[tuple[str, dict[str, Any]]] = []
    cursor = 0
    while len(sampled) < profile.total_count:
        paper_id = papers[cursor % len(papers)]
        cursor += 1
        if by_paper[paper_id]:
            sampled.append((paper_id, by_paper[paper_id].pop()))
        if not any(by_paper.values()):
            raise RuntimeError(f"Qasper 可抽题目不足 {profile.total_count}。")

    # 论文整体 doc-disjoint 分配
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for paper_id, qa in sampled:
        grouped[paper_id].append(qa)
    groups = sorted(grouped.items())
    rng.shuffle(groups)
    targets = {"train": profile.train_count, "dev": profile.dev_count, "test": profile.test_count}
    assignment = _greedy_assign(groups, targets)
    _write_json_splits(profile, assignment, data, qa_key="qas")

    # baseline 文件：全部论文入库，QA 仅保留抽样题
    sampled_by_paper: dict[str, list[Any]] = defaultdict(list)
    for pairs in assignment.values():
        for name, qa in pairs:
            sampled_by_paper[name].append(qa)
    all_out = {
        paper_id: {**paper, "qas": sampled_by_paper.get(paper_id, [])}
        for paper_id, paper in data.items()
    }
    profiles.save_json(profile.splits_dir / "harness_all.json", all_out)

    return {
        "dataset": "qasper",
        "seed": SEED,
        "ratio": "40/20/40",
        "source": profile.raw_data.name,
        "question_counts": {key: len(value) for key, value in assignment.items()},
        "doc_count": len(data),
        "doc_disjoint": True,
        "doc_disjoint_note": "按论文整体分配，同一论文不跨 split；入库覆盖全部论文。",
        "excluded_question_type": "全标注 unanswerable 的题目",
    }


# ---------------------------------------------------------------- clapnq

def prepare_clapnq(profile: profiles.DatasetProfile) -> dict[str, Any]:
    annotations = (
        profile.raw_data / "annotated_data" / "dev" / "clapnq_dev_answerable.jsonl"
    )
    orig_docs = profile.raw_data / "original_documents" / "dev" / "clapnq_dev_answerable_orig.jsonl"
    for path in (annotations, orig_docs):
        if not path.exists():
            raise FileNotFoundError(f"缺少 ClapNQ 数据文件：{path}")

    rows = profiles.load_jsonl(annotations)
    if len(rows) != profile.total_count:
        raise RuntimeError(f"ClapNQ dev answerable 应为 {profile.total_count} 题，实际 {len(rows)} 题。")

    # 题目级随机划分（与 HotpotQA 相同：不同题目可能共享来源文章，无法 doc-disjoint）
    rng = random.Random(SEED)
    shuffled = rows[:]
    rng.shuffle(shuffled)
    splits = {
        "train": shuffled[: profile.train_count],
        "dev": shuffled[profile.train_count : profile.train_count + profile.dev_count],
        "test": shuffled[profile.train_count + profile.dev_count :],
    }
    for split, split_rows in splits.items():
        profiles.save_jsonl(profile.splits_dir / f"harness_{split}.jsonl", split_rows)

    return {
        "dataset": "clapnq",
        "seed": SEED,
        "ratio": "40/20/40",
        "question_counts": {key: len(value) for key, value in splits.items()},
        "doc_count": profile.doc_count,
        "doc_disjoint": False,
        "doc_disjoint_note": "题目级随机划分；不同题目可能共享来源 Wikipedia 文章（与 HotpotQA 同类）。",
        "source": "annotated_data/dev/clapnq_dev_answerable.jsonl（adapter 只读取 dev answerable）",
    }


# ---------------------------------------------------------------- driver

PREPARERS = {
    "hotpotqa": prepare_hotpotqa,
    "syllabusqa": prepare_syllabusqa,
    "locomo": prepare_locomo,
    "qasper": prepare_qasper,
    "clapnq": prepare_clapnq,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(PREPARERS), required=True)
    parser.add_argument("--force", action="store_true", help="已有 manifest 也强制重算（会校验一致性）")
    args = parser.parse_args()

    profile = profiles.get_profile(args.dataset)
    manifest_path = profile.splits_dir / "SPLIT_MANIFEST.json"

    if manifest_path.exists() and not args.force:
        say(f"[复用] 划分已存在：{manifest_path}")
        return 0

    manifest = PREPARERS[args.dataset](profile)

    # 归一化行由 profile loader 派生，立刻自检数量
    for split, expected in manifest["question_counts"].items():
        rows = profile.load_split_rows(split)
        if len(rows) != expected:
            raise RuntimeError(f"{args.dataset}/{split} 归一化行数 {len(rows)} != {expected}")

    manifest["files"] = {
        path.name: sha256_file(path)
        for path in sorted(profile.splits_dir.glob("harness_*"))
    }
    if manifest_path.exists():
        old = profiles.load_json(manifest_path)
        if old != manifest:
            raise RuntimeError(
                "新计算的划分与已有 manifest 不一致；划分是冻结产物，请确认后再删除旧文件重算。"
            )
        say("[校验] 重算结果与已有 manifest 完全一致。")
    profiles.save_json(manifest_path, manifest)
    say(
        f"[完成] {args.dataset}: "
        + "/".join(str(manifest["question_counts"][key]) for key in ("train", "dev", "test"))
        + f" 题，{manifest['doc_count']} 文档；manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
