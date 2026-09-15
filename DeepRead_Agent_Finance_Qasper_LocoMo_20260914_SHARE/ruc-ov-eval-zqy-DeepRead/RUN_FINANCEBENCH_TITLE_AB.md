# FinanceBench title-preload A/B runbook

This experiment is intentionally isolated from historical `Data/**/DeepRead` and
`Output` directories.

## Inputs

The repository root must contain:

```text
Data/FinanceBench/data/financebench_open_source.jsonl
Data/FinanceBench/markdown/*.md
Data/FinanceBench/pdfs/*.pdf
```

The adapter prefers Markdown and falls back to PDF. The checked local dataset
contains 141 questions over 82 unique documents: 81 have Markdown and the
remaining document has a PDF, so no source document is missing.

## Environment

Provide credentials through environment variables, never by editing them into
the YAML files:

```bash
export LLM_MODEL="doubao-seed-1-8-251228"
export LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export LLM_API_KEY="..."
export EMBEDDING_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export EMBEDDING_API_KEY="..."
export EMBEDDING_MODEL_NAME="doubao-embedding-vision-250615"
```

## Preflight (read-only)

```bash
test -f Data/FinanceBench/data/financebench_open_source.jsonl && echo DATA_OK
find Data/FinanceBench/markdown -maxdepth 1 -type f -name '*.md' | wc -l
find Data/FinanceBench/pdfs -maxdepth 1 -type f -name '*.pdf' | wc -l
test -f DeepRead/agent/runner.py && echo DEEPREAD_OK
test -f OpenViking/pyproject.toml && echo OPENVIKING_OK
test -f KohakuRAG/pyproject.toml && echo KOHAKU_OK
rg -n "preload_directory_structure" DeepRead/agent/runner.py DeepRead/prompt/system.py ov_test/src/core/deepread_store.py
```

Do not run the benchmark unless the checks print `DATA_OK`, `DEEPREAD_OK`,
`OPENVIKING_OK`, and `KOHAKU_OK`, and the final command finds the flag in all
three code locations.

## Smoke A/B

The OFF run performs the one-time ingestion and writes only below
`ExperimentArtifacts/FinanceBench`. It does not edit source Markdown/PDF files:

```bash
uv run python ov_test/run.py \
  --config ov_test/config_deepread_global/financebench_title_ab_off_smoke.yaml \
  --step all
```

The ON run reuses that new index and changes only the title-directory preload
behavior:

```bash
uv run python ov_test/run.py \
  --config ov_test/config_deepread_global/financebench_title_ab_on_smoke.yaml \
  --step all \
  --skip-ingest
```

Expected new outputs:

```text
ExperimentArtifacts/FinanceBench/title_ab_v1/
ExperimentArtifacts/FinanceBench/Output/deepread_title_ab_off_smoke_*/
ExperimentArtifacts/FinanceBench/Output/deepread_title_ab_on_smoke_*/
```

The two configurations both use one worker, `top_k=1`, no session pagination,
and the same model, corpus, index, maximum rounds, and first 20 questions.
