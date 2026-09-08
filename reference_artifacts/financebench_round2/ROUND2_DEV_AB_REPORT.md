# AI自主生成工具：Dev 20严格A/B

## 实验边界

- 候选工具仅由固定train 60题中的原始轨迹生成。
- 本轮只使用dev 20题；test 61题保持未触碰。
- Baseline关闭旧标题工具；Candidate只新增AI生成工具及AI生成的使用策略。
- Student、Judge、索引、轮数、top-k和其他检索工具完全相同。
- 盲重建来源：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\repair_round2`

## 自动生成单元测试

9/9 通过。

## Dev结果

| 方案 | 准确率 | 平均分(0-4) | 输入Token/题 | 输出Token/题 | 耗时/题 | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 85.00% | 3.400 | 204979 | 2696 | 44.3s | 30.00% |
| AI生成工具 | 92.50% | 3.700 | 98887 | 2487 | 33.1s | 30.00% |

成对结果：**2胜 / 18平 / 0负**，净得分变化 **+6**。

## 逐题变化

| case_id | Baseline | Candidate | 变化 | 问题 |
|---|---:|---:|---:|---|
| financebench_id_00438 | 1 | 4 | +3 | Does Adobe have an improving operating margin profile as of FY2022? If operating margin is not a useful metric for a company like this, then state that and explain why. |
| financebench_id_04458 | 1 | 4 | +3 | We want to calculate a financial metric. Please help us compute it by basing your answers off of the statement of income and the statement of cash flows. Here's the question: what is the FY2015 unadjusted EBITDA % margin for Netflix? Calculate unadjusted EBITDA using unadjusted operating income and D&A (from cash flow statement). |
| financebench_id_03856 | 4 | 4 | +0 | What is the FY2017 operating cash flow ratio for Adobe? Operating cash flow ratio is defined as: cash from operations / total current liabilities. Round your answer to two decimal places. Please utilize information provided primarily within the balance sheet and the cash flow statement. |
| financebench_id_00591 | 4 | 4 | +0 | Does Adobe have an improving Free cashflow conversion as of FY2022? |
| financebench_id_01935 | 4 | 4 | +0 | What was the key agenda of the AMCOR's 8k filing dated 1st July 2022? |
| financebench_id_03838 | 4 | 4 | +0 | What is the FY2019 - FY2020 total revenue growth rate for Block (formerly known as Square)? Answer in units of percents and round to one decimal place. Approach the question asked by assuming the standpoint of an investment banking analyst who only has access to the statement of income. |
| financebench_id_07661 | 4 | 4 | +0 | Using the cash flow statement, answer the following question to the best of your abilities: how much did Block (formerly known as Square) generate in cash flow from operating activities in FY2020? Answer in USD millions. |
| financebench_id_04209 | 4 | 4 | +0 | Using only the information within the balance sheet, how much total assets did Costco have at the end of FY2021? Answer in USD millions. |
| financebench_id_00790 | 1 | 1 | +0 | Is CVS Health a capital-intensive business based on FY2022 data? |
| financebench_id_01107 | 4 | 4 | +0 | Has CVS Health reported any materially important ongoing legal battles from 2022, 2021 and 2020? |
| financebench_id_01244 | 4 | 4 | +0 | Has CVS Health paid dividends to common shareholders in Q2 of FY2022? |
| financebench_id_00839 | 4 | 4 | +0 | Does Foot Locker's new CEO have previous CEO experience in a similar company to Footlocker? |
| financebench_id_00651 | 1 | 1 | +0 | Is growth in JnJ's adjusted EPS expected to accelerate in FY2023? |
| financebench_id_01484 | 4 | 4 | +0 | How did JnJ's US sales growth compare to international sales growth in FY2022? |
| financebench_id_00206 | 4 | 4 | +0 | Are JPM's gross margins historically consistent (not fluctuating more than roughly 2% each year)? If gross margins are not a relevant metric for a company like this, then please state that and explain why. |
| financebench_id_04171 | 4 | 4 | +0 | Basing your judgments off of the balance sheet, what is the year end FY2018 amount of accounts payable for MGM Resorts? Answer in USD millions. |
| financebench_id_00552 | 4 | 4 | +0 | Has Microsoft increased its debt on balance sheet between FY2023 and the FY2022 period? |
| financebench_id_03282 | 4 | 4 | +0 | What is Netflix's year end FY2017 total current liabilities (in USD millions)? Base your judgments on the information provided primarily in the balance sheet. |
| financebench_id_00859 | 4 | 4 | +0 | Among all of the derivative instruments that Verizon used to manage the exposure to fluctuations of foreign currencies exchange rates or interest rates, which one had the highest notional value in FY 2021? |
| financebench_id_02024 | 4 | 4 | +0 | As of FY 2021, how much did Verizon expect to pay for its retirees in 2024? |

## 判定规则

若dev净提升且没有不可接受的大幅退化，则冻结工具与策略并进入test 61；否则只用dev轨迹分析和修复，不能查看test答案。


## Round 2自主修复说明

本轮Repair Agent只获得原候选、dev成对结果和原始轨迹；未提供人工故障结论，未访问test。

### Agent自主诊断

```json
{
  "what_worked": "For straightforward company-plus-year questions, the inventory tool selected the correct 10-K on the first call, eliminated repeated full-corpus searches, and reduced average input tokens from about 205k to 105k and latency from about 44s to 38s. The candidate achieved 1 win, 19 ties, and 0 losses.",
  "failure_mechanisms": "An additional metadata-level bug remained: the month-year date regex had only one capture group, but the extraction branch assumed two groups, raising 'no such group' at runtime and preventing month-year dates from being parsed. The earlier fiscal-year century bug, date-suffix company pollution, and possessive/multiword/initialism/ticker-prefix matching failures also remained in the rejected candidate.",
  "scope_boundary": "The tool ranks document metadata only. It cannot verify content, table rows, or semantic intent that selects among several same-company filings. It should not be used to prove absence; the coverage output exists so the agent can enumerate strong candidates before concluding 'not found'."
}
```

### Agent自主修改

```json
[
  "Replace positional regex group indexing with named capture groups for all date patterns so month-year dates do not raise 'no such group'.",
  "Fix fiscal-year and quarter parsing so the full four-digit year is captured instead of only the century prefix; removes spurious year 20 entries from query_parsed and fiscal_year lists.",
  "Mask full dates and the 'dated' marker before company-token extraction so date suffixes no longer pollute company names.",
  "Parse explicit dates from questions and document metadata, and add a date-match bonus so dated 8-K filings rank correctly.",
  "Generate generic company aliases from token initials and connector initials, and match proper-noun question tokens as prefixes of normalized company names; supports possessive, multiword, initialism, and ticker-prefix forms without a hard-coded alias list.",
  "Recognize EARNINGS as a filing type in metadata and questions.",
  "Expose quarter, filing-type, date, and strong-candidate coverage in the output, and sort by score then match count so better-qualified filings win ties."
]
```

- 原Round 1报告：`D:\桌面\DeepRead\agentic_rag_tool_evolution\runs\blind_20260821_181044\dev_ab\DEV_AB_REPORT.md`
- 修复组总轮数：134
- 修复组工具调用：`{"document_inventory_search": 26, "get_doc_structure": 26, "regex_search": 35, "read_section": 89, "bm25_search": 23, "vector_search": 1}`
