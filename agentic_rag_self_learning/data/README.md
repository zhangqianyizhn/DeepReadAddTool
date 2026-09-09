# Data artifacts

本目录不复制或修改原始 `Data/FinanceBench`。

审核通过并实现脚本后，将在 `data/generated/` 生成：

```text
split_manifest.json
train.jsonl
dev.jsonl
test.jsonl
pilot20.jsonl
question_metadata.json
```

要求：

- 原始数据保持只读；
- 按 `doc_name` 分组划分；
- 使用 `financebench_id` 做稳定配对；
- manifest 记录随机种子、分布和文件 SHA256；
- Teacher 运行时只能读取 Train 相关文件。
