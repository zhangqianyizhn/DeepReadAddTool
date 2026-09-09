"""数据集 profile：把工具演化链中的数据集差异集中到这一处。

每条链路脚本（blind_reconstruction / dev_ab / repair_round2 / frozen_test61）通过
`--dataset` 选择 profile；不指定时默认 financebench，行为与原实验完全一致。

统一后的"归一化行" schema（所有 split 文件、反馈包、Judge 均使用）：
    case_id           唯一 ID（financebench_id / hotpot id / syllabus id）
    question          Student 实际看到的问题文本（SyllabusQA 为加前缀后的完整形式）
    answer            gold answer
    question_type     题型
    evidence_sources  gold 证据所在文档名列表
    evidence_excerpts gold 证据摘录（至多 2 条）
    leakage_terms     修复代码中禁止出现的字面量（公司名 / 大纲名等）
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]                       # agentic_rag_tool_evolution/
WORKSPACE = ROOT.parent                      # 工作区根
REPO = WORKSPACE / "ruc-ov-eval-zqy-DeepRead"
V2 = WORKSPACE / "agentic_rag_self_learning_v2"
OLD_EXPERIMENT = WORKSPACE / "agentic_rag_self_learning"

# 数据根目录可用环境变量覆盖（服务器上数据位置可能不同）。
DATA_ROOT = Path(os.environ.get("DEEPREAD_DATA_ROOT", str(WORKSPACE / "Data"))).expanduser().resolve()

EXPECTED_COUNTS = {"financebench": 61, "hotpotqa": 40, "syllabusqa": 80}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class DatasetProfile:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    # ---- 路径 ----
    @property
    def splits_dir(self) -> Path:
        return self._splits_dir

    def split_file(self, split: str) -> Path:
        """归一化 split（jsonl）。"""
        return self.splits_dir / f"{split}.jsonl"

    def harness_file(self, split: str) -> Path:
        """harness（ov_test adapter）可直接消费的分割文件。"""
        return self.splits_dir / f"harness_{split}{self.harness_ext}"

    def harness_full_file(self) -> Path:
        """baseline 入库/答题用的完整实验集文件（覆盖所有 split 涉及的文档）。"""
        if self.name == "syllabusqa":
            return self.splits_dir / "harness_all.csv"
        return self.raw_data

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    @property
    def baseline_dir(self) -> Path:
        return (
            WORKSPACE
            / "ExperimentArtifacts"
            / self.artifact_group
            / "Output"
            / f"deepread_matched_baseline_{self.total_count}_0001"
        )

    def load_split_rows(self, split: str) -> list[dict[str, Any]]:
        return load_jsonl(self.split_file(split))

    def write_harness_subset(self, rows: list[dict[str, Any]], path: Path) -> None:
        """把归一化行子集写成 adapter 可消费的格式（供 --max-questions 冒烟用）。"""
        raise NotImplementedError(self.name)


# ---------------------------------------------------------------- financebench

def _fb_rows(split: str) -> list[dict[str, Any]]:
    normalized = []
    for row in load_jsonl(V2 / "data" / "splits" / f"{split}.jsonl"):
        evidence = row.get("evidence") or []
        normalized.append(
            {
                "case_id": row.get("financebench_id"),
                "question": row.get("question"),
                "answer": row.get("answer"),
                "question_type": row.get("question_type"),
                "evidence_sources": sorted(
                    {str(e.get("doc_name")) for e in evidence if isinstance(e, dict) and e.get("doc_name")}
                ),
                "evidence_excerpts": [str(e.get("evidence_text", "")) for e in evidence[:2] if isinstance(e, dict)],
                "leakage_terms": [str(row.get("company") or "")] if row.get("company") else [],
                "raw": row,
            }
        )
    return normalized


def _fb_write_subset(rows: list[dict[str, Any]], path: Path) -> None:
    save_jsonl(path, [row["raw"] for row in rows])


FINANCEBENCH = DatasetProfile(
    name="financebench",
    display_name="FinanceBench",
    total_count=141,
    train_count=60,
    dev_count=20,
    test_count=61,
    doc_count=82,
    artifact_group="FinanceBenchFull141",
    adapter_module="src.adapters.finance_bench_adapter",
    adapter_class="FinanceBenchAdapter",
    judge_system="You are a strict FinanceBench answer evaluator.",
    harness_ext=".jsonl",
    raw_data=DATA_ROOT / "FinanceBench" / "data" / "financebench_open_source.jsonl",
    index_dir=OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "store_index",
    processed_dir=OLD_EXPERIMENT / "data" / "generated" / "full141" / "DeepRead" / "processed_docs",
    baseline_dataset_name="FinanceBenchFull141MatchedBaseline",
    dev_dataset_name="FinanceBenchDev20",
    env_overrides={},
    _splits_dir=V2 / "data" / "splits",   # 归一化读取走 load_split_rows 覆盖
    _runs_dir=ROOT / "runs",
)


# ---------------------------------------------------------------- hotpotqa

def _hotpot_rows(split: str) -> list[dict[str, Any]]:
    normalized = []
    for item in load_json(HOTPOTQA.splits_dir / f"harness_{split}.json"):
        context = item.get("context", {})
        facts = item.get("supporting_facts", {})
        titles = context.get("title", [])
        sentences = context.get("sentences", [])
        by_title = {t: (sentences[i] if i < len(sentences) else []) for i, t in enumerate(titles)}
        excerpts: list[str] = []
        for fact_title, sent_id in zip(facts.get("title", []), facts.get("sent_id", [])):
            sents = by_title.get(fact_title, [])
            if sent_id < len(sents) and sents[sent_id].strip():
                excerpts.append(sents[sent_id].strip())
        normalized.append(
            {
                "case_id": item.get("id"),
                "question": item.get("question"),
                "answer": item.get("answer"),
                "question_type": item.get("type"),
                "evidence_sources": sorted(set(facts.get("title", []))),
                "evidence_excerpts": excerpts[:2],
                "leakage_terms": [],
                "raw": item,
            }
        )
    return normalized


def _hotpot_write_subset(rows: list[dict[str, Any]], path: Path) -> None:
    save_json(path, [row["raw"] for row in rows])


HOTPOTQA = DatasetProfile(
    name="hotpotqa",
    display_name="HotpotQA",
    total_count=100,
    train_count=40,
    dev_count=20,
    test_count=40,
    doc_count=None,  # 由 prepare_splits 写入 manifest（被引用的文章数）
    artifact_group="HotpotQA100",
    adapter_module="src.adapters.hotpotqa_adapter",
    adapter_class="HotpotQAAdapter",
    judge_system="You are a strict HotpotQA answer evaluator.",
    harness_ext=".json",
    raw_data=DATA_ROOT / "HotpotQA" / "hotpot_qa_100.json",
    index_dir=ROOT / "data" / "index" / "hotpotqa" / "store_index",
    processed_dir=ROOT / "data" / "index" / "hotpotqa" / "processed_docs",
    baseline_dataset_name="HotpotQA100MatchedBaseline",
    dev_dataset_name="HotpotQADev20",
    env_overrides={},
    _splits_dir=ROOT / "data" / "splits" / "hotpotqa",
    _runs_dir=ROOT / "runs" / "hotpotqa",
)


# ---------------------------------------------------------------- syllabusqa

SYLLABUS_COLUMNS = (
    ["id", "syllabus_name", "question_type", "question", "answer"]
    + [f"answer_span_{i}" for i in range(1, 6)]
    + [f"reasoning_step_{i}" for i in range(1, 6)]
)


def _syllabus_rows(split: str) -> list[dict[str, Any]]:
    path = SYLLABUSQA.splits_dir / f"harness_{split}.csv"
    normalized = []
    with path.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            excerpts = [
                row[f"answer_span_{i}"].strip()
                for i in range(1, 6)
                if (row.get(f"answer_span_{i}") or "").strip()
            ]
            normalized.append(
                {
                    "case_id": row.get("id"),
                    # 与 adapter 生成给 Student 的问题文本保持一致
                    "question": f'Based on the syllabus "{row.get("syllabus_name", "")}", {row.get("question", "")}',
                    "answer": row.get("answer"),
                    "question_type": row.get("question_type"),
                    "evidence_sources": [row.get("syllabus_name", "")],
                    "evidence_excerpts": excerpts[:2],
                    "leakage_terms": [row.get("syllabus_name", "")],
                    "raw": dict(row),
                }
            )
    return normalized


def _syllabus_write_subset(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SYLLABUS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row["raw"].get(key, "") for key in SYLLABUS_COLUMNS})


SYLLABUSQA = DatasetProfile(
    name="syllabusqa",
    display_name="SyllabusQA",
    total_count=200,
    train_count=80,
    dev_count=40,
    test_count=80,
    doc_count=None,  # manifest：抽样覆盖的大纲数
    artifact_group="SyllabusQA200",
    adapter_module="src.adapters.syllabusqa_adapter",
    adapter_class="SyllabusQAAdapter",
    judge_system="You are a strict SyllabusQA answer evaluator.",
    harness_ext=".csv",
    raw_data=DATA_ROOT / "SyllabusQA",
    index_dir=ROOT / "data" / "index" / "syllabusqa" / "store_index",
    processed_dir=ROOT / "data" / "index" / "syllabusqa" / "processed_docs",
    baseline_dataset_name="SyllabusQA200MatchedBaseline",
    dev_dataset_name="SyllabusQADev40",
    env_overrides={"SYLLABUSQA_DOC_DIR": str(DATA_ROOT / "SyllabusQA" / "syllabi")},
    _splits_dir=ROOT / "data" / "splits" / "syllabusqa",
    _runs_dir=ROOT / "runs" / "syllabusqa",
)


PROFILES: dict[str, DatasetProfile] = {
    "financebench": FINANCEBENCH,
    "hotpotqa": HOTPOTQA,
    "syllabusqa": SYLLABUSQA,
}

# 默认答题/入库线程数：financebench 保持 1 以与历史 reference artifacts 完全对齐；
# 新数据集无历史对齐包袱，默认 4（火山方舟 429 由底层指数退避重试兜底）。
DEFAULT_WORKERS = {"financebench": 1, "hotpotqa": 4, "syllabusqa": 4}

# FinanceBench 的归一化行直接从 v2 splits 派生；其余两个由 prepare_splits 预生成 harness 文件。
_LOADERS: dict[str, Callable[[str], list[dict[str, Any]]]] = {
    "financebench": _fb_rows,
    "hotpotqa": _hotpot_rows,
    "syllabusqa": _syllabus_rows,
}
_WRITERS: dict[str, Callable[[list[dict[str, Any]], Path], None]] = {
    "financebench": _fb_write_subset,
    "hotpotqa": _hotpot_write_subset,
    "syllabusqa": _syllabus_write_subset,
}


def get_profile(name: str) -> DatasetProfile:
    if name not in PROFILES:
        raise ValueError(f"未知数据集：{name!r}（可选：{sorted(PROFILES)}）")
    profile = PROFILES[name]
    profile.load_split_rows = _LOADERS[name]      # type: ignore[method-assign]
    profile.write_harness_subset = _WRITERS[name]  # type: ignore[method-assign]
    if profile.name == "financebench":
        # v2 splits 本身就是 harness 可消费的 FinanceBench jsonl
        profile.harness_file = lambda split: V2 / "data" / "splits" / f"{split}.jsonl"  # type: ignore[method-assign]
    else:
        # doc-disjoint 划分按文档粒度分配，实际题数以 manifest 为准
        manifest_path = profile.splits_dir / "SPLIT_MANIFEST.json"
        if manifest_path.exists():
            manifest = load_json(manifest_path)
            counts = manifest.get("question_counts") or {}
            for split in ("train", "dev", "test"):
                if split in counts:
                    setattr(profile, f"{split}_count", counts[split])
            if counts:
                profile.total_count = sum(counts.values())
            if manifest.get("doc_count"):
                profile.doc_count = manifest["doc_count"]
    return profile


def leakage_terms_for(profile: DatasetProfile, splits: tuple[str, ...] = ("train", "dev")) -> set[str]:
    """修复代码泄漏检查用的禁止字面量集合（归一化小写字母数字形式）。"""
    terms: set[str] = set()
    for split in splits:
        for row in profile.load_split_rows(split):
            for term in row.get("leakage_terms") or []:
                normalized = re.sub(r"[^a-z0-9]+", "", str(term).lower())
                if len(normalized) >= 3 and normalized not in {"block"}:
                    terms.add(normalized)
    return terms
