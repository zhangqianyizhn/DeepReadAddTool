# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this workspace is

A research workspace (git repo since 2026-09-09) for "Agentic RAG self-learning and autonomous tool evolution" experiments on FinanceBench. Most docs and reports are written in Chinese. Large/generated data is gitignored: the raw FinanceBench dataset (`Data/FinanceBench/`), indexes, and `ExperimentArtifacts/` must be produced locally (see "Baseline rebuild").

Four sibling project directories are **mutually dependent via relative paths** — do not move or rename them:

- `ruc-ov-eval-zqy-DeepRead/` — the underlying RAG/DeepRead runtime and benchmark harness (uv project, Python ≥3.11). **Pruned to the DeepRead+FinanceBench path only**: OpenViking/KohakuRAG/hipporag/pageindex backends, their store modules, adapters and configs were deleted; `store.type` other than `DeepRead` now hard-fails in `ov_test/run.py`.
- `agentic_rag_self_learning/` — original Teacher–Student prompt-optimization experiment; its `scripts/run_pilot.py` is the **shared base harness** (LLM calls, JSON retry, Judge, config generation) imported as `import run_pilot as legacy` by both later experiments.
- `agentic_rag_self_learning_v2/` — strict Train/Dev/Test (60/20/61) self-learning loop, rounds 1–4 (`scripts/content2.py round1`, `round2.py`, `round3.py`, `round4.py`). Its `data/splits/` are committed and required by tool_evolution.
- `agentic_rag_tool_evolution/` — agent autonomously diagnoses failures from train trajectories and writes executable Python candidate tools (`blind_reconstruction.py` → `dev_ab.py` → `repair_round2.py` → `frozen_test61.py`).
- `reference_artifacts/` — frozen FinanceBench outputs from the original run; read-only evidence, not source.

## Commands

### Environment setup

```bash
cd ruc-ov-eval-zqy-DeepRead && uv sync   # the single shared venv for everything
cp agentic_rag_self_learning/.env.example agentic_rag_self_learning/.env   # fill in VOLCENGINE_API_KEY + model names
```

All experiment scripts load keys from `agentic_rag_self_learning/.env` (VOLCENGINE_API_KEY, STUDENT/TEACHER/JUDGE_MODEL + BASE_URL, EMBEDDING_MODEL_NAME). Never commit or print real `.env` contents. Note: some checked-in `ov_test/config*/` YAMLs contain a literal `llm.api_key` — prefer `.env` when editing configs.

### Baseline rebuild (required once before the tool-evolution chain)

`blind_reconstruction.py` hardcodes `ExperimentArtifacts/FinanceBenchFull141/Output/deepread_matched_baseline_141_0001/` (judged results + `deepread_run.log` trajectories). If it doesn't exist, rebuild from the raw dataset:

```bash
./ruc-ov-eval-zqy-DeepRead/run_full141_matched_baseline.sh            # ingest index + 141q baseline + judge (hours)
./ruc-ov-eval-zqy-DeepRead/run_full141_matched_baseline.sh --dry-run  # validate data/env only
```

This wraps `agentic_rag_tool_evolution/scripts/rebuild_baseline141.py`: validates `Data/FinanceBench` (141q/82docs), builds the 82-doc index into `agentic_rag_self_learning/data/generated/full141/DeepRead/` when missing, runs `ov_test/run.py --step all` with a **stable** output dir (`auto_increment_output: false`, so reruns resume in place), and verifies the three artifacts.

### Benchmark harness (single source of truth for running DeepRead)

```bash
cd ruc-ov-eval-zqy-DeepRead
uv run python ov_test/run.py --config ov_test/config_deepread/financebench.yaml --step all
# --step all|gen|eval|del ; --skip-ingest reuses an existing index
```

Experiment scripts never call the model directly — they generate a temp `config.yaml` and launch `ov_test/run.py` as a subprocess with env injection (`LLM_MODEL=$STUDENT_MODEL` etc.).

### Experiment entry points (tool-evolution chain)

```bash
cd agentic_rag_tool_evolution
./run_blind_reconstruction.sh        # [--dry-run] Analyzer + Tool Architect on train-60
./run_dev_ab.sh                      # dev-20 strict A/B + Judge
./run_autonomous_repair_round2.sh    # Repair Agent on dev feedback, re-run repaired arm
./run_frozen_test61.sh               # SHA-256 freeze + one-shot test-61 A/B
```

The `.sh` wrappers share `scripts/_entry_common.sh`: they use the uv venv python, force UTF-8, and wrap with `caffeinate -i` on macOS. All stages checkpoint and resume on rerun. The old Windows `.ps1` entries were removed (still in git history); v2/pilot `.ps1` scripts were NOT ported — run their Python directly, e.g. `python agentic_rag_self_learning_v2/scripts/content2.py round1`.

### Tests

```bash
cd ruc-ov-eval-zqy-DeepRead
PYTHONPATH=".:ov_test" uv run python -m unittest \
  DeepRead.tests.test_search_session DeepRead.tests.test_document_title_search DeepRead.tests.test_source_header
```

`DeepRead/agent/llm.py` imports `src.core.token_tracer_util` from ov_test, so tests need BOTH repo root and `ov_test/` on `PYTHONPATH` — plain `unittest discover` fails to import.

## Architecture

### Benchmark layer (`ruc-ov-eval-zqy-DeepRead/ov_test/`)

Adapter + Pipeline design. `run.py` parses `--config`, then `src/pipeline.py` orchestrates ingest → retrieve/generate → evaluate. Datasets plug in via `src/adapters/*_adapter.py` (produce `StandardDoc`/`StandardSample`, `build_prompt`, `post_process_answer`); the config's `adapter.module`/`class_name` and `store.type` select them — adding a dataset means a new adapter + config, never pipeline changes. LLM-as-judge routing per dataset lives in `src/core/judge_util.py:llm_grader` (0–4 scale, normalized to 0–1). **Path resolution quirk:** `run.py` derives `WORKSPACE_ROOT` as the *parent of the repo dir*, so `paths.raw_data: "Data/{dataset_name}/..."` resolves against the workspace root — `Data/FinanceBench/` must sit next to the project dirs.

### DeepRead agent (`ruc-ov-eval-zqy-DeepRead/DeepRead/`)

`agent/runner.py:run_agent` is an LLM tool-calling loop over tools defined in `tool/schema.py` (BM25/vector/hybrid/regex search, `read_section`, document-title routing), backed by `tool/retrieval.py` and the index under `store_index/` + `processed_docs/`. `prompt/system.py:build_system_prompt` composes the Student system prompt. The supported extension point is YAML `store.agent_instructions` → `run_agent(additional_instructions=...)` — the self-learning experiments inject optimized instructions this way rather than forking the agent.

AI-generated candidate tools are **not** added to the tool schema. They run through a restricted runtime contract: `runner.py:_invoke_generated_corpus_tool(tool, question, corpus_inventory, top_k, capability?)` where `corpus_inventory` is a read-only doc/section metadata view (`_build_generated_corpus_inventory`). Candidates are statically safety-checked (no file/network/process/dynamic-exec) and stay in `agentic_rag_tool_evolution/runs/` until audited.

### Experiment protocol (all three experiment dirs)

- Fixed document-grouped split in `agentic_rag_self_learning_v2/data/splits/`: train 60 / dev 20 / test 61. Teacher/Analyzer inputs are programmatically filtered to `split == train`; dev is for selection/A-B only; **test 61 runs exactly once after freeze** — `frozen_test61.py` SHA-256-locks candidate code, strategy, model config, and the split, and refuses to rerun if any of them change. Test feedback never flows back into any Repair Agent.
- "Blind" rule in tool_evolution: scripts must not read test data, the existing `search_document_titles` implementation, prior A/B reports, or human failure analyses.
- `Data/FinanceBench`, the 82-doc index, and old 141-question outputs are read-only; indexes are never rebuilt by experiment scripts (they may embed machine-specific absolute paths — rebuild on a new machine).

### Required external data (gitignored, must exist locally) for end-to-end reruns

```text
Data/FinanceBench/                                                          (workspace root)
agentic_rag_self_learning/data/generated/full141/DeepRead/processed_docs/   (rebuilt by rebuild_baseline141.py)
agentic_rag_self_learning/data/generated/full141/DeepRead/store_index/      (rebuilt by rebuild_baseline141.py)
ExperimentArtifacts/FinanceBenchFull141/Output/deepread_matched_baseline_141_0001/  (rebuilt likewise)
```

## Key files to read first

1. `agentic_rag_tool_evolution/scripts/blind_reconstruction.py` and `dev_ab.py`
2. `agentic_rag_self_learning/scripts/run_pilot.py` (shared harness API)
3. `ruc-ov-eval-zqy-DeepRead/DeepRead/agent/runner.py`
4. `ruc-ov-eval-zqy-DeepRead/ov_test/src/pipeline.py`
5. `reference_artifacts/financebench_test61/FROZEN_TEST61_REPORT.md`
