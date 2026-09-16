# ruc-ov-eval-initial（初始版消融运行时）

工具演化实验的**弱基线消融运行时**：初始版 ruc-ov-eval + 初始版 DeepRead，
外加一份最小回填（backport），使工具演化链可以在其上运行。

## 来源（provenance）

| 组件 | 版本 | 来源仓库 |
|---|---|---|
| ruc-ov-eval | `fb8a301cfd9cb92f19a5c95cd0066da1133b734b`（update legalbench topk args & sync deepread bugfix） | 本机 `~/Desktop/ruc-ov/ruc-ov-eval`（remote: github.com/g121370451/ruc-ov-eval） |
| DeepRead | `7fe3ba23f81d88ee83552ba7f38cd6cc25e6c1eb`（bugfix: threading.Lock） | 本机 `~/Desktop/ruc-ov/ruc-ov-eval/DeepRead`（remote: github.com/zhangqianyizhn/DeepRead） |

组建方式：从上述本地仓库 clone → checkout 钉版 commit → 删除 OpenViking/KohakuRAG/
hipporag/pageindex → 应用回填 → 折叠进主仓（嵌套 .git 历史已移除）。

## 最小回填内容（相对钉版的全部差异）

钉版**没有**工具演化所需的注入点，以下且仅有以下改动：

1. `ov_test/run.py`：支持 `paths.auto_increment_output: false`（固定输出目录，断点续跑必需）。
2. `ov_test/src/core/deepread_store.py`：
   - `agent_instructions` 透传（config `store.agent_instructions` → `run_agent(additional_instructions=...)`）；
   - AI 生成工具加载（`enable_document_inventory_search` + `document_inventory_tool_path`，动态 import 候选的 `run()`）；
   - embedding 参数走配置（原为硬编码 `doubao-embedding-vision-250615` 与 LLM base_url）。
3. `DeepRead/prompt/system.py`：`build_system_prompt(additional_instructions=...)`。
4. `DeepRead/tool/schema.py`：`document_inventory_search` 工具定义（开关控制）。
5. `DeepRead/agent/runner.py`：`document_inventory_search` 分发（corpus 文档清单调用候选工具）。
6. `ov_test/src/pipeline.py`：`skip_ingestion` 时不再调用 `adapter.data_prepare`
   （否则跳过入库的评测阶段会被 Adapter 的文档布局检查阻断，例如 ClapNQ 的 split 文件路径）；
   DeepRead 入库前不清空 store 目录（断点续传）。
7. `ov_test/src/core/doubao_embedding_util.py`：整体替换为调优版——plan 通道会把可重放的
   请求偶尔返回为 400 InvalidParameter，钉版无重试会直接终止入库；调优版带精确重试与
   跨线程 token 汇总支持。

**刻意未改**：检索工具集合、Agent 循环逻辑、系统 prompt 主体、轨迹事件 schema
（`llm_response`/`tool_call`/`tool_result` + sha1 query_id，与 blind_reconstruction 解析器兼容）、
串行入库。这些"弱"正是消融要测量的对象。

## 环境

- 与主仓共用 `ruc-ov-eval-zqy-DeepRead/.venv`（`uv sync` 一次即可，依赖兼容已验证）；
- `.env` 复用 `agentic_rag_self_learning/.env`（经 run_baseline/dev_ab 环境注入，无需另配）。

## 使用

```bash
DEEPREAD_RUNTIME=initial ./run_all.sh --datasets <name> --workers 4
```

索引/运行/产物自动隔离到 `data/index_initial/`、`runs_initial/`、`ExperimentArtifacts/*_initial/`。
