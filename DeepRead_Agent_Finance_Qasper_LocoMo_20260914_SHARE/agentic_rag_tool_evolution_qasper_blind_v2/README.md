# Qasper autonomous single-tool blind replication v2

This experiment tests whether an LLM can independently discover and implement one useful RAG tool on a new, paper-disjoint sample from the official Qasper train split.

Protocol boundaries:

- Source: `Data/Qasper_official_v0.3/qasper-train-v0.3.json`.
- Deterministic paper-level split: 100 train questions, 40 dev questions, 120 sealed test questions.
- Representation: canonical Qasper JSON text only. PDF files and PDF extraction are disabled.
- Analyzer input: train baseline questions, golds, answers, automatic judge scores, and raw trajectories only.
- The Analyzer and Repair Agent receive no old tool, old report, human failure diagnosis, dev question, or test question.
- One Analyzer decision, one generated tool, and at most two self-repair attempts against the tool's frozen synthetic tests.
- Dev is evaluation-only; it is not fed back for repair.
- Test may be opened only after a passing dev result and a frozen artifact manifest.

Run the train-to-dev stage:

```powershell
cd "D:\桌面\DeepRead\agentic_rag_tool_evolution_qasper_blind_v2"
.\run_blind_train_then_dev.ps1
```

After the preregistered dev gate passes, freeze all artifacts and run the sealed
Test120 exactly once:

```powershell
.\run_frozen_test120.ps1
```
