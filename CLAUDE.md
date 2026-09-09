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

This wraps `agentic_rag_tool_evolution/scripts/run_baseline.py --dataset financebench` (the shim `rebuild_baseline141.py` keeps the old command shape). For the other datasets: `run_baseline.py --dataset hotpotqa|syllabusqa` — validates raw data, builds the index into `agentic_rag_tool_evolution/data/index/<dataset>/` when missing, runs `ov_test/run.py --step all` with a **stable** output dir (`auto_increment_output: false`, so reruns resume in place), and verifies the three artifacts. Baselines cover each dataset's full experiment set; `blind_reconstruction` feeds only train-split cases to the Analyzer.

### Benchmark harness (single source of truth for running DeepRead)

```bash
cd ruc-ov-eval-zqy-DeepRead
uv run python ov_test/run.py --config ov_test/config_deepread/financebench.yaml --step all
# --step all|gen|eval|del ; --skip-ingest reuses an existing index
# 其他数据集：config_deepread/{hotpotqa,syllabusqa}.yaml（config_deepread_global/ 下有同名变体）
```

Supported datasets: FinanceBench (markdown/pdf docs), HotpotQA (`hotpot_qa_100.json` + `hotpot_articles.json`, articles converted to markdown by the adapter), SyllabusQA (dir of train/val/test CSVs + `syllabi/*.docx`, converted via python-docx). Judge routing in `judge_util.py` only special-cases Locomo; all three use the generic 0–4 prompt. HotpotQA/SyllabusQA configs use `${LLM_*}`/`${EMBEDDING_*}` placeholders — direct runs need `ov_test/.env` (see `ov_test/.env.example`).

Data lives outside the repo: on this machine `DeepReadAddTool/Data` is a **symlink to `~/Desktop/ruc-ov/Data`** (gitignored); on a server, place the dataset dir at the same workspace-relative location. `Data/HotpotQA/DeepRead/store_index` ships a pre-built index (skip_ingestion reuses it; flip `skip_ingestion: false` to rebuild).

Experiment scripts never call the model directly — they generate a temp `config.yaml` and launch `ov_test/run.py` as a subprocess with env injection (`LLM_MODEL=$STUDENT_MODEL` etc.).

### Experiment entry points (tool-evolution chain)

One command for the full pipeline (all three datasets, or a subset) — see `SERVER_GUIDE.md`:

```bash
./run_all.sh                                  # prepare_splits → baseline → blind → dev A/B → repair → frozen test
./run_all.sh --datasets financebench          # subset
./run_all.sh --dry-run                        # preflight only, no API calls
```

Per-stage entries (all take `--dataset financebench|hotpotqa|syllabusqa`, default financebench):

```bash
cd agentic_rag_tool_evolution
./run_blind_reconstruction.sh        # [--dry-run] Analyzer + Tool Architect on train
./run_dev_ab.sh                      # dev strict A/B + Judge
./run_autonomous_repair_round2.sh    # Repair Agent on dev feedback, re-run repaired arm
./run_frozen_test61.sh               # SHA-256 freeze + one-shot test A/B (filename is historic; test size comes from the dataset profile)
```

The `.sh` wrappers share `scripts/_entry_common.sh`: they use the uv venv python, force UTF-8, and wrap with `caffeinate -i` on macOS. All stages checkpoint and resume on rerun. The old Windows `.ps1` entries were removed (still in git history); v2/pilot `.ps1` scripts were NOT ported — run their Python directly, e.g. `python agentic_rag_self_learning_v2/scripts/content2.py round1`.

### Multi-dataset support (`agentic_rag_tool_evolution/scripts/dataset_profiles.py`)

All dataset variation is centralized in `dataset_profiles.py`: paths, adapter module/class, judge system prompt, split counts, and a **normalized row schema** (`case_id/question/answer/question_type/evidence_sources/evidence_excerpts/leakage_terms`) that the four chain scripts consume via `get_profile(--dataset)`. Key per-dataset facts:

- **financebench**: splits come from `agentic_rag_self_learning_v2/data/splits/` (committed); index under `agentic_rag_self_learning/data/generated/full141/`; runs in `runs/` (historic layout).
- **hotpotqa**: 100 questions, question-level random 40/20/40 split (multi-hop questions share articles — NOT doc-disjoint, recorded in the manifest); index under `data/index/hotpotqa/` (gitignored); runs in `runs/hotpotqa/`.
- **syllabusqa**: 4358 questions → seeded stratified sample of 200 → doc-disjoint (by `syllabus_name`) 80/40/80 split — whole-syllabus granularity means actual counts land at 79/42/79, so profile counts are **read from SPLIT_MANIFEST.json at runtime**, never hardcode them; the harness gets the adapter-formatted question (`Based on the syllabus "X", ...`), and runs need `SYLLABUSQA_DOC_DIR` (injected automatically from the profile).
- Splits for the two new datasets are built by `scripts/prepare_splits.py` (seed 20260823-independent, seed 20260909, deterministic, refuses to overwrite a mismatched manifest) and committed under `data/splits/<dataset>/`.
- Data root defaults to `<workspace>/Data`; override with env `DEEPREAD_DATA_ROOT`.

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
