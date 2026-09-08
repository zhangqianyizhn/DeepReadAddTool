# Student Agent Instructions v0

本文件有意保持为空白基线。

Baseline 使用 DeepRead 自带的 system prompt，不追加任何由 Teacher 学到的规则。这样后续候选只通过 `store.agent_instructions` 注入，能够进行干净的 paired comparison。

正式渲染配置时，本说明文字不会注入 Student；v0 的实际 `agent_instructions` 为：

```yaml
agent_instructions: []
```
