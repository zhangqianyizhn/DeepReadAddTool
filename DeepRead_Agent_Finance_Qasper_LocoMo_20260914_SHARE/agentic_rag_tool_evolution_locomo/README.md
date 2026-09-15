# LocoMo autonomous single-tool experiment

Protocol: deterministic conversation-disjoint Train/Dev/Test split (160/40/100 questions), full shared
ten-conversation retrieval corpus, Train-only generation of exactly one autonomous tool capability, one autonomous
Dev-feedback repair of that same tool, Dev selection between v1/v2, and one frozen Test A/B. Dev is development data;
only the untouched Test result is final generalization evidence.

Original `Data/Locomo/Locomo.json` is read-only. Generated splits, indexes, outputs, checkpoints and reports stay under
this experiment directory. Scripts resume completed work rather than deleting or overwriting it.

Preflight without API calls:

```powershell
.\run_train_generate.ps1 -DryRun
```

Run both stages:

```powershell
.\run_all.ps1
```
