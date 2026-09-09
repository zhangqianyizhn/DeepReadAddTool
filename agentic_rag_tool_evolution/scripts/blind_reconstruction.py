from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(HERE.parent))
import dataset_profiles as profiles  # noqa: E402

ENV_FILE = WORKSPACE / "agentic_rag_self_learning" / ".env"


ANALYZER_SYSTEM = """You are the analysis agent in a blind RAG capability-discovery experiment.
You receive only training-set questions, gold information, baseline answers, scores, and raw tool trajectories.
No human diagnosis and no previous repair design are available to you.

Your job is to find recurring causal failure mechanisms, not to write generic prompt advice.
Distinguish failures in corpus selection, within-document retrieval, evidence composition, numerical reasoning,
answer synthesis, and stopping. Compare failures with successful controls. Propose missing executable capabilities
only when trajectory evidence supports them. A capability must state its inputs, outputs, preconditions, and how it
would alter the action space. Do not assume that prompt editing is the answer.

Return one JSON object with keys:
- evidence_summary: concise dataset-level observations
- failure_clusters: array of {name, count_estimate, causal_chain, trajectory_evidence, repairability}
- candidate_capabilities: array of {name, problem_solved, inputs, outputs, preconditions, expected_effect, risks}
- selected_capability: the single best capability or null
- selection_reason
- falsification_test: what result would show the diagnosis is wrong
"""


ARCHITECT_SYSTEM = """You are the repair agent in a blind tool-synthesis experiment.
Turn the analyzer's selected missing capability into one small executable Python tool and a usage policy.
The tool must solve a recurring failure mechanism, not encode gold answers or specific benchmark question IDs.

Runtime contract:
- Define exactly one public function: run(question: str, documents: list[dict[str, str]], top_k: int = 5) -> dict.
- Each document contains only generic corpus metadata: doc_id and source_name.
- Return JSON-serializable data. Include ranked results where relevant.
- Allowed imports: re, math, json, collections, typing, dataclasses.
- Forbidden: file/network/process access, environment variables, dynamic execution, third-party packages.
- Do not copy benchmark answers, question IDs, or a hard-coded company list into the code.

Return one JSON object with keys:
- tool_spec: {name, purpose, inputs, outputs, algorithm, complexity, failure_modes}
- code: complete Python source as a JSON string
- usage_policy: {when_to_call, how_to_use_output, fallback, stopping_rule}
- tests: array of generic {name, question, documents, top_k, expected_property}
- novelty_claim: a restrained statement; do not claim literature novelty
"""


def say(message: str) -> None:
    print(message, flush=True)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def query_id(question: str) -> str:
    return hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]


def compact_tool_result(event: dict[str, Any]) -> dict[str, Any]:
    result = event.get("result")
    if not isinstance(result, dict):
        return {"preview": clip(result, 800)}
    compact: dict[str, Any] = {"ok": result.get("ok")}
    for key in ("query", "scope", "doc_id", "source_name", "title", "error"):
        if result.get(key) is not None:
            compact[key] = clip(result[key], 300)
    rows = result.get("results")
    if isinstance(rows, list):
        compact["results"] = []
        for row in rows[:3]:
            if not isinstance(row, dict):
                compact["results"].append(clip(row, 500))
                continue
            item: dict[str, Any] = {}
            for key in ("score", "source_name", "title", "text"):
                if row.get(key) is not None:
                    item[key] = clip(row[key], 500)
            ref = row.get("ref")
            if isinstance(ref, dict):
                item["ref"] = {k: ref.get(k) for k in ("doc_id", "node_id") if ref.get(k) is not None}
            compact["results"].append(item)
    if len(compact) == 1:
        compact["preview"] = clip(result, 900)
    return compact


def load_trajectories(log_file: Path, wanted_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = str(event.get("query_id") or "")
            if qid not in wanted_ids:
                continue
            kind = event.get("event")
            if kind == "llm_response":
                grouped[qid].append(
                    {
                        "round": event.get("round"),
                        "event": kind,
                        "reasoning": clip(event.get("reasoning_content") or event.get("content") or "", 1100),
                        "tool_calls": event.get("tool_calls") or [],
                    }
                )
            elif kind == "tool_call":
                grouped[qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "args": event.get("args") or {},
                    }
                )
            elif kind == "tool_result":
                grouped[qid].append(
                    {
                        "event": kind,
                        "tool": event.get("tool"),
                        "result": compact_tool_result(event),
                    }
                )
    return grouped


def normalized_score(row: dict[str, Any]) -> float:
    evaluation = row.get("llm_evaluation") or {}
    value = evaluation.get("normalized_score")
    if value is None:
        value = (row.get("metrics") or {}).get("Accuracy", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_blind_packet(
    profile: "profiles.DatasetProfile", failure_limit: int, success_limit: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    answers_file = profile.baseline_dir / "qa_eval_detailed_results.json"
    log_file = profile.baseline_dir / "deepread_run.log"
    train_rows = profile.load_split_rows("train")
    train_by_question = {row["question"]: row for row in train_rows}
    all_results = read_json(answers_file).get("results", [])
    train_results = [row for row in all_results if row.get("question") in train_by_question]
    if len(train_results) != len(train_rows):
        raise RuntimeError(
            f"训练集与 baseline 结果没有完整对齐：split={len(train_rows)}, matched={len(train_results)}"
        )

    failures = sorted((row for row in train_results if normalized_score(row) <= 2), key=normalized_score)
    successes = sorted((row for row in train_results if normalized_score(row) >= 4), key=normalized_score, reverse=True)
    selected = failures[:failure_limit] + successes[:success_limit]
    wanted = {query_id(row["question"]) for row in selected}
    trajectories = load_trajectories(log_file, wanted)

    cases: list[dict[str, Any]] = []
    for row in selected:
        source = train_by_question[row["question"]]
        qid = query_id(row["question"])
        cases.append(
            {
                "case_id": source.get("case_id"),
                "question_type": source.get("question_type"),
                "question": source.get("question"),
                "gold_answer": clip(source.get("answer") or row.get("gold_answers"), 1400),
                "gold_evidence_sources": source.get("evidence_sources") or [],
                "gold_evidence_excerpt": [clip(text, 650) for text in (source.get("evidence_excerpts") or [])[:2]],
                "baseline_answer": clip((row.get("llm") or {}).get("final_answer", ""), 1600),
                "judge_score_0_to_4": normalized_score(row),
                "judge_reason": clip((row.get("llm_evaluation") or {}).get("reasoning", ""), 650),
                "trajectory": trajectories.get(qid, [])[:30],
            }
        )

    packet = {
        "experiment": "blind_capability_discovery",
        "dataset": profile.display_name,
        "split": "train_only",
        "case_selection": {
            "failure_threshold": "judge score <= 2",
            "success_threshold": "judge score >= 4",
            "failure_cases": min(failure_limit, len(failures)),
            "success_controls": min(success_limit, len(successes)),
        },
        "available_baseline_tools_observed_in_trajectories": sorted(
            {
                str(event.get("tool"))
                for case in cases
                for event in case["trajectory"]
                if event.get("tool")
            }
        ),
        "cases": cases,
    }
    manifest = {
        "dataset": profile.name,
        "train_rows": len(train_rows),
        "matched_baseline_rows": len(train_results),
        "available_failures": len(failures),
        "available_successes": len(successes),
        "selected_cases": len(cases),
        "question_type_counts": dict(Counter(case["question_type"] for case in cases)),
        "source_files": [str(profile.harness_file("train")), str(answers_file), str(log_file)],
        "explicitly_excluded": [
            "test split",
            "existing title-routing source code",
            "title-routing trajectories and reports",
            "human-written failure attribution",
            "previous Teacher prompt candidates",
        ],
    }
    return packet, manifest


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("模型没有返回 JSON 对象。")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("模型返回值不是 JSON 对象。")
    return value


def model_json_call(client: OpenAI, model: str, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    attempts = [
        {"response_format": {"type": "json_object"}, "temperature": 0, "max_tokens": max_tokens},
        {"temperature": 0, "max_tokens": max_tokens},
        {"max_tokens": max_tokens},
        {"max_tokens": max_tokens},
        {"max_tokens": max_tokens},
    ]
    last_error: Exception | None = None
    for number, extra in enumerate(attempts, start=1):
        try:
            response = client.chat.completions.create(model=model, messages=messages, **extra)
            content = response.choices[0].message.content or ""
            return extract_json_object(content)
        except Exception as exc:
            last_error = exc
            error_text = str(exc)
            if any(marker in error_text for marker in ("403", "PermissionDenied", "AccountOverdue")):
                raise RuntimeError(f"模型无权限或套餐不可用：{exc}") from exc
            if number < len(attempts):
                # 网关 5xx/504 恢复较慢，使用更长退避（30/60/90/120 秒）
                wait = number * 30
                say(f"[重试] 第 {number} 次调用失败：{type(exc).__name__}；{wait} 秒后重试。")
                time.sleep(wait)
    raise RuntimeError(f"模型连续返回失败：{last_error}")


def find_resumable_run(runs_dir: Path) -> Path | None:
    """找最近一次 Analyzer 已完成但 Repair Agent 未完成的 blind 运行目录。"""
    candidates = sorted(
        (path for path in runs_dir.glob("blind_*") if (path / "analysis.json").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        if not (path / "BLIND_RECONSTRUCTION_REPORT.md").exists():
            return path
    return None


def validate_candidate(code: str) -> list[str]:
    problems: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Python 语法错误：{exc}"]

    allowed_imports = {"re", "math", "json", "collections", "typing", "dataclasses"}
    forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    public_functions: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".")[0] for alias in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
            for name in names:
                if name not in allowed_imports:
                    problems.append(f"禁止的 import：{name}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
            problems.append(f"禁止的调用：{node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"禁止访问双下划线属性：{node.attr}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            public_functions.append(node.name)
    if public_functions != ["run"]:
        problems.append(f"公开函数必须且只能是 run，实际为：{public_functions}")
    return sorted(set(problems))


def render_report(run_dir: Path, manifest: dict[str, Any], analysis: dict[str, Any], candidate: dict[str, Any], safety: list[str]) -> str:
    selected = analysis.get("selected_capability")
    spec = candidate.get("tool_spec") or {}
    status = "通过静态安全检查" if not safety else "未通过静态安全检查"
    lines = [
        "# Agent 自动工具盲重建报告",
        "",
        "## 实验边界",
        "",
        f"- 仅使用训练集：{manifest['train_rows']} 题中的 {manifest['selected_cases']} 个案例。",
        "- Agent 未读取现成标题工具、标题路由报告、人工错误归因或 test 集。",
        "- 本轮只生成候选，不修改 DeepRead，也不宣称最终有效。",
        "",
        "## Analyzer 独立选择的能力",
        "",
        "```json",
        json.dumps(selected, ensure_ascii=False, indent=2),
        "```",
        "",
        "### 选择依据",
        "",
        str(analysis.get("selection_reason") or "（未提供）"),
        "",
        "### 可证伪条件",
        "",
        str(analysis.get("falsification_test") or "（未提供）"),
        "",
        "## 自动生成的工具",
        "",
        f"- 名称：`{spec.get('name', '未命名')}`",
        f"- 目的：{spec.get('purpose', '未提供')}",
        f"- 静态检查：**{status}**",
        "",
    ]
    if safety:
        lines += ["发现的问题：", ""] + [f"- {item}" for item in safety] + [""]
    lines += [
        "### 算法规格",
        "",
        "```json",
        json.dumps(spec, ensure_ascii=False, indent=2),
        "```",
        "",
        "### 自动生成的使用策略",
        "",
        "```json",
        json.dumps(candidate.get("usage_policy"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 当前能得出的结论",
        "",
        "本报告只回答 Agent 是否能从原始轨迹独立提出并写出一个候选工具。它尚未回答该工具是否真的提升 RAG。下一步必须先审计候选是否泄漏/过拟合，再接入 dev 20 题做严格 A/B；通过后才可冻结并运行 test 61 题。",
        "",
        "## 产物",
        "",
        f"- 完整诊断：`{run_dir / 'analysis.json'}`",
        f"- ToolSpec 与策略：`{run_dir / 'candidate.json'}`",
        f"- 候选源码：`{run_dir / 'candidate_tool.py'}`",
        f"- 盲测清单：`{run_dir / 'manifest.json'}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="financebench", choices=sorted(profiles.PROFILES))
    parser.add_argument("--failure-cases", type=int, default=16)
    parser.add_argument("--success-cases", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    profile = profiles.get_profile(args.dataset)
    answers_file = profile.baseline_dir / "qa_eval_detailed_results.json"
    log_file = profile.baseline_dir / "deepread_run.log"
    required = [ENV_FILE, answers_file, log_file]
    missing = [str(path) for path in required if not path.exists()]
    if profile.name != "financebench" and not profile.harness_file("train").exists():
        missing.append(f"{profile.splits_dir}（先运行 prepare_splits.py --dataset {profile.name}）")
    if missing:
        raise FileNotFoundError("缺少实验输入：\n" + "\n".join(missing))

    packet, manifest = build_blind_packet(profile, args.failure_cases, args.success_cases)
    say(
        f"[数据就绪] {profile.display_name} train={manifest['train_rows']}，选中={manifest['selected_cases']}，"
        f"失败池={manifest['available_failures']}，成功池={manifest['available_successes']}"
    )
    say("[盲测约束] 不读取现成标题工具、人工归因、历史标题路由报告或 test 集。")
    if args.dry_run:
        say("[DryRun 完成] 输入完整；未调用 API，未生成候选工具。")
        return 0

    load_dotenv(ENV_FILE, override=True)
    api_key = os.getenv("TEACHER_API_KEY") or os.getenv("VOLCENGINE_API_KEY")
    base_url = os.getenv("TEACHER_BASE_URL") or os.getenv("ARK_BASE_URL")
    model = os.getenv("TEACHER_MODEL") or "deepseek-v4-flash"
    if not api_key or api_key == "PASTE_YOUR_VOLCENGINE_API_KEY_HERE":
        raise RuntimeError(f"请先在 {ENV_FILE} 的 VOLCENGINE_API_KEY= 后粘贴新套餐 Key。")
    if not base_url:
        raise RuntimeError("缺少 ARK_BASE_URL/TEACHER_BASE_URL。")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=600, max_retries=1)

    # 断点续跑：Analyzer 已成功但 Repair Agent 未完成的运行目录直接复用，
    # 不会因网关抖动重跑已付费的 Analyzer。
    resumed = find_resumable_run(profile.runs_dir)
    if resumed is not None:
        run_dir = resumed
        analysis = read_json(run_dir / "analysis.json")
        packet = read_json(run_dir / "blind_packet.json")
        say(f"[断点续跑] 复用 Analyzer 诊断：{run_dir}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = profile.runs_dir / f"blind_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "blind_packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")

        say(f"[Analyzer] {model} 正在从原始训练轨迹归纳可工具化的失败机制……")
        analysis = model_json_call(
            client,
            model,
            [
                {"role": "system", "content": ANALYZER_SYSTEM},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            max_tokens=5000,
        )
        (run_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    if (run_dir / "candidate.json").exists():
        candidate = read_json(run_dir / "candidate.json")
        say("[断点续跑] 复用已生成的候选工具，仅重建报告。")
        safety = candidate.get("static_safety_problems") or []
        report = render_report(run_dir, manifest, analysis, candidate, safety)
        (run_dir / "BLIND_RECONSTRUCTION_REPORT.md").write_text(report, encoding="utf-8")
        say(f"[完成] 盲重建报告：{run_dir / 'BLIND_RECONSTRUCTION_REPORT.md'}")
        return 0

    if not analysis.get("selected_capability"):
        raise RuntimeError(f"Analyzer 没有选择可工具化能力；诊断已保存到 {run_dir / 'analysis.json'}")

    architect_input = {
        "analysis": analysis,
        "observed_baseline_tool_names": packet["available_baseline_tools_observed_in_trajectories"],
        "constraint": "Build one general tool from the diagnosis; do not use test data or benchmark-specific IDs.",
    }
    say("[Repair Agent] 正在把诊断转换为 ToolSpec、受限 Python 工具和调用策略……")
    candidate = model_json_call(
        client,
        model,
        [
            {"role": "system", "content": ARCHITECT_SYSTEM},
            {"role": "user", "content": json.dumps(architect_input, ensure_ascii=False)},
        ],
        max_tokens=6000,
    )
    code = str(candidate.get("code") or "")
    safety = validate_candidate(code)
    candidate["static_safety_problems"] = safety
    (run_dir / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "candidate_tool.py").write_text(code, encoding="utf-8")
    report = render_report(run_dir, manifest, analysis, candidate, safety)
    report_path = run_dir / "BLIND_RECONSTRUCTION_REPORT.md"
    report_path.write_text(report, encoding="utf-8")

    say(f"[完成] 盲重建报告：{report_path}")
    say(f"[完成] 候选工具：{run_dir / 'candidate_tool.py'}")
    if safety:
        say("[注意] 候选未通过静态安全检查，禁止接入；先查看报告。")
    else:
        say("[下一关] 候选仅通过静态检查，尚未接入 DeepRead，也尚未证明有效。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("\n[已停止] 已生成的中间结果保留在 runs 中。")
        raise SystemExit(130)
    except Exception as exc:
        say(f"\n[失败] {exc}")
        raise SystemExit(1)
