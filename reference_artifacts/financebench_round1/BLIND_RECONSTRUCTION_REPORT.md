# Agent 自动工具盲重建报告

## 实验边界

- 仅使用训练集：60 题中的 20 个案例。
- Agent 未读取现成标题工具、标题路由报告、人工错误归因或 test 集。
- 本轮只生成候选，不修改 DeepRead，也不宣称最终有效。

## Analyzer 独立选择的能力

```json
"document_inventory_search"
```

### 选择依据

The most frequent and fundamental failure is wrong-document selection. Many trajectories show repeated full-corpus searches returning wrong company/period snippets and false 'not found' conclusions, even though the correct document exists. A document inventory/metadata search directly addresses this bottleneck, is executable with existing source-header metadata, and is a prerequisite for other fixes such as coverage checks and statement locators. It would have prevented or shortened failures in roughly 10 of 16 cases.

### 可证伪条件

If, after adding document_inventory_search, agents still fail on cases where the gold source exists in the corpus—e.g., they still return 'no document found' for Amazon FY2019, AMD FY2022, Best Buy FY2023, or still select the wrong company's filing—then the diagnosis that document selection is the primary bottleneck is wrong. More specifically, if a held-out set of the same failure cases shows no reduction in wrong-document selection errors or false-negative conclusions, the capability should be reconsidered.

## 自动生成的工具

- 名称：`document_inventory_search`
- 目的：Rank the available corpus documents by how well they match the company, fiscal period, and filing type mentioned in the question, so the agent can scope subsequent searches to the right document instead of running full-corpus searches that return wrong-company snippets.
- 静态检查：**通过静态安全检查**

### 算法规格

```json
{
  "name": "document_inventory_search",
  "purpose": "Rank the available corpus documents by how well they match the company, fiscal period, and filing type mentioned in the question, so the agent can scope subsequent searches to the right document instead of running full-corpus searches that return wrong-company snippets.",
  "inputs": {
    "question": "string; natural-language question containing company name, fiscal year/quarter, and optionally filing type",
    "documents": "list of dicts with keys doc_id and source_name; each entry is a corpus document's metadata",
    "top_k": "int; number of ranked candidates to return (default 5)"
  },
  "outputs": {
    "query_parsed": "parsed years, quarters, filing_type from question",
    "results": "ranked list of documents with doc_id, source_name, parsed company/year/quarter/filing_type, score, and match_reasons",
    "coverage": "counts of company-matched, year-matched, and strong candidates to support coverage checks before concluding 'not found'"
  },
  "algorithm": "Parse each document's doc_id/source_name into company tokens, fiscal years, quarters, and filing type via regex. Parse the question for the same fields. Score documents by weighted matches: company (3.0), year (1.5), quarter (1.0), filing type (1.0); neutral 0.5 when the question does not specify a field. Sort descending by score and return top_k.",
  "complexity": "O(N * T) where N is number of documents and T is length of document metadata strings; no external calls.",
  "failure_modes": [
    "Company names that are heavily abbreviated or completely different from the document identifier will not match.",
    "Ambiguous fiscal periods (e.g., a 10-K filed in 2020 for FY2019) depend on metadata conventions.",
    "The tool ranks metadata only; it does not verify content or table rows.",
    "If the question names no company, all company scores are zero and ranking relies on period/filing type only."
  ]
}
```

### 自动生成的使用策略

```json
{
  "when_to_call": "Call at the start of any question that asks for facts from a filing, before issuing a full-corpus search. Also call after a failed full-corpus search to enumerate candidate documents and check whether the gold source exists in the corpus.",
  "how_to_use_output": "Take the top-ranked result's doc_id as the scope for bm25_search/regex_search/read_section. If the top result is the wrong company or period, try the next candidate in the ranked list. Use coverage.company_matched_count and strong_candidate_count to decide whether the corpus plausibly contains the requested data before concluding 'not found'.",
  "fallback": "If the tool returns no strong company match, do not immediately conclude absence; run a broad get_doc_structure/vector_search over the corpus once and inspect source headers. If a candidate doc_id is known but not in results, pass it explicitly to read_section.",
  "stopping_rule": "Stop document selection as soon as one candidate has both company_match=true and (year_match=true or filing_type_match=true) and a subsequent content search locates the relevant statement/table. If no candidate satisfies that after checking all returned results, conclude 'corpus does not contain a matching document' only after a final broad inventory pass."
}
```

## 当前能得出的结论

本报告只回答 Agent 是否能从原始轨迹独立提出并写出一个候选工具。它尚未回答该工具是否真的提升 RAG。下一步必须先审计候选是否泄漏/过拟合，再接入 dev 20 题做严格 A/B；通过后才可冻结并运行 test 61 题。

## 产物

- 完整诊断：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\analysis.json`
- ToolSpec 与策略：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\candidate.json`
- 候选源码：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\candidate_tool.py`
- 盲测清单：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\manifest.json`
