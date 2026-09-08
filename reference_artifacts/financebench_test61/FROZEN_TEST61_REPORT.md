# AI自主生成并修复工具：冻结Test 61最终A/B

## 实验纪律

- 工具与策略在查看test结果前冻结，并由SHA-256清单校验。
- test共61题；Repair Agent从未读取test反馈。
- Baseline关闭旧标题工具；Candidate只开启冻结的AI生成工具与AI生成策略。
- 两组Student、Judge、索引、轮数、top-k和其他检索工具完全一致。
- 本结果只用于最终泛化评估，禁止再用test反馈修改候选。

## 冻结信息

- Student：`deepseek-v4-flash`
- Judge：`deepseek-v4-flash`
- 候选代码SHA-256：`74dcab8e11db78721db730b74e53e7261ebf5e3e458e7ce4220d9d7c6b7edb03`
- test划分SHA-256：`fe434029ccbc3f2fc90a99c197e9dbb7237cc017f309477e269df3c7cfb20f07`

## 总体结果

| 方案 | 准确率 | 平均分(0-4) | 输入Token/题 | 输出Token/题 | 耗时/题 | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 90.98% | 3.639 | 480710 | 3934 | 55.3s | 31.97% |
| 冻结AI工具 | 90.98% | 3.639 | 240003 | 3202 | 35.9s | 27.32% |

- 准确率变化：**+0.00%**
- 成对结果：**1胜 / 59平 / 1负**，净分 **+0**
- 平均输入Token变化：**-50.07%**
- 平均耗时变化：**-35.06%**
- Baseline工具调用：`{"bm25_search": 373, "get_doc_structure": 157, "regex_search": 225, "read_section": 318, "vector_search": 12}`
- Candidate工具调用：`{"document_inventory_search": 67, "get_doc_structure": 73, "read_section": 246, "regex_search": 255, "bm25_search": 144, "vector_search": 2}`

## 逐题变化

| case_id | Baseline | Candidate | 变化 | 问题 |
|---|---:|---:|---:|---|
| financebench_id_00678 | 1 | 4 | +3 | Does Boeing have an improving gross margin profile as of FY2022? If gross margin is not a useful metric for a company like this, then state that and explain why. |
| financebench_id_00807 | 1 | 1 | +0 | Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick ratio is not relevant to measure liquidity, please state that and explain why. |
| financebench_id_00941 | 4 | 4 | +0 | Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2023? |
| financebench_id_01858 | 4 | 4 | +0 | Does 3M maintain a stable trend of dividend distribution? |
| financebench_id_04735 | 4 | 4 | +0 | You are an investment banker and your only resource(s) to answer the following question is (are): the statement of financial position and the cash flow statement. Here's the question: what is the FY2015 operating cash flow ratio for Adobe? Operating cash flow ratio is defined as: cash from operations / total current liabilities. Round your answer to two decimal places. |
| financebench_id_07507 | 4 | 4 | +0 | What is Adobe's year-over-year change in unadjusted operating income from FY2015 to FY2016 (in units of percents and round to one decimal place)? Give a solution to the question by using the income statement. |
| financebench_id_01319 | 4 | 4 | +0 | What is the quantity of restructuring costs directly outlined in AES Corporation's income statements for FY2022? If restructuring costs are not explicitly outlined then state 0. |
| financebench_id_00540 | 1 | 1 | +0 | Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio for the FY2022; if conventional inventory management is not meaningful for the company then state that and explain why. |
| financebench_id_10420 | 1 | 1 | +0 | Based on the information provided primarily in the statement of financial position and the statement of income, what is AES's FY2022 return on assets (ROA)? ROA is defined as: FY2022 net income / (average total assets between FY2021 and FY2022). Round your answer to two decimal places. |
| financebench_id_06655 | 4 | 4 | +0 | What is Amazon's FY2017 days payable outstanding (DPO)? DPO is defined as: 365 * (average accounts payable between FY2016 and FY2017) / (FY2017 COGS + change in inventory between FY2016 and FY2017). Round your answer to two decimal places. Address the question by using the line items and information shown within the balance sheet and the P&L statement. |
| financebench_id_08135 | 4 | 4 | +0 | What is Amazon's year-over-year change in revenue from FY2016 to FY2017 (in units of percents and round to one decimal place)? Calculate what was asked by utilizing the line items clearly shown in the statement of income. |
| financebench_id_03882 | 4 | 4 | +0 | What is Amcor's year end FY2020 net AR (in USD millions)? Address the question by adopting the perspective of a financial analyst who can only use the details shown within the balance sheet. |
| financebench_id_01079 | 4 | 4 | +0 | What are major acquisitions that AMCOR has done in FY2023, FY2022 and FY2021? |
| financebench_id_01148 | 4 | 4 | +0 | What industry does AMCOR primarily operate in? |
| financebench_id_00684 | 4 | 4 | +0 | Does AMCOR have an improving gross margin profile as of FY2023? If gross margin is not a useful metric for a company like this, then state that and explain why. |
| financebench_id_03069 | 4 | 4 | +0 | Answer the following question as if you are an equity research analyst and have lost internet connection so you do not have access to financial metric providers. According to the details clearly outlined within the P&L statement and the statement of cash flows, what is the FY2015 depreciation and amortization (D&A from cash flow statement) % margin for AMD? |
| financebench_id_04254 | 4 | 4 | +0 | Basing your judgments off of the cash flow statement and the income statement, what is American Water Works's FY2021 unadjusted operating income + depreciation and amortization from the cash flow statement (unadjusted EBITDA) in USD millions? |
| financebench_id_00070 | 4 | 4 | +0 | Does American Water Works have positive working capital based on FY2022 data? If working capital is not a useful or relevant metric for this company, then please state that and explain why. |
| financebench_id_00517 | 4 | 4 | +0 | Are there any product categories / service categories that represent more than 20% of Boeing's revenue for FY2022? |
| financebench_id_01091 | 4 | 4 | +0 | Has Boeing reported any materially important ongoing legal battles from FY2022? |
| financebench_id_01290 | 4 | 4 | +0 | Who are the primary customers of Boeing as of FY2022? |
| financebench_id_00464 | 4 | 4 | +0 | Is Boeing's business subject to cyclicality? |
| financebench_id_00494 | 4 | 4 | +0 | What production rate changes is Boeing forecasting for FY2023? |
| financebench_id_00585 | 1 | 1 | +0 | How does Boeing's effective tax rate in FY2022 compare to FY2021? |
| financebench_id_09724 | 4 | 4 | +0 | What is Coca Cola's FY2021 COGS % margin? Calculate what was asked by utilizing the line items clearly shown in the income statement. |
| financebench_id_02981 | 4 | 4 | +0 | Taking into account the information outlined in the income statement, what is the FY2019 - FY2021 3 year average unadjusted operating income % margin for Corning? Answer in units of percents and round to one decimal place. |
| financebench_id_05915 | 4 | 4 | +0 | What is the FY2018 fixed asset turnover ratio for CVS Health? Fixed asset turnover ratio is defined as: FY2018 revenue / (average PP&E between FY2017 and FY2018). Round your answer to two decimal places. Calculate what was asked by utilizing the line items clearly shown in the P&L statement and the balance sheet. |
| financebench_id_00822 | 4 | 4 | +0 | Were there any board member nominees who had substantially more votes against joining than the other nominees? |
| financebench_id_04103 | 4 | 4 | +0 | What is the FY2019 cash conversion cycle (CCC) for General Mills? CCC is defined as: DIO + DSO - DPO. DIO is defined as: 365 * (average inventory between FY2018 and FY2019) / (FY2019 COGS). DSO is defined as: 365 * (average accounts receivable between FY2018 and FY2019) / (FY2019 Revenue). DPO is defined as: 365 * (average accounts payable between FY2018 and FY2019) / (FY2019 COGS + change in inventory between FY2018 and FY2019). Round your answer to two decimal places. Address the question by using the line items and information shown within the income statement and the balance sheet. |
| financebench_id_03471 | 4 | 4 | +0 | By drawing conclusions from the information stated only in the statement of financial position, what is General Mills's FY2020 working capital ratio? Define working capital ratio as total current assets divided by total current liabilities. Round your answer to two decimal places. |
| financebench_id_04854 | 4 | 4 | +0 | According to the information provided in the statement of cash flows, what is the FY2020 free cash flow (FCF) for General Mills? FCF here is defined as: (cash from operations - capex). Answer in USD millions. |
| financebench_id_10136 | 4 | 4 | +0 | We want to calculate a financial metric. Please help us compute it by basing your answers off of the cash flow statement and the income statement. Here's the question: what is the FY2022 retention ratio (using total cash dividends paid and net income attributable to shareholders) for General Mills? Round answer to two decimal places. |
| financebench_id_00956 | 4 | 4 | +0 | Are JnJ's FY2022 financials that of a high growth company? |
| financebench_id_00669 | 4 | 4 | +0 | What drove gross margin change as of FY2022 for JnJ? If gross margin is not a useful metric for a company like this, then please state that and explain why. |
| financebench_id_00711 | 4 | 4 | +0 | Roughly how many times has JnJ sold its inventory in FY2022? Calculate inventory turnover ratio for FY2022; if conventional inventory management is not meaningful for the company then state that and explain why. |
| financebench_id_01488 | 4 | 4 | +0 | Which business segment of JnJ will be treated as a discontinued operation from August 30, 2023 onward? |
| financebench_id_01490 | 4 | 4 | +0 | What is the amount of the gain accruing to JnJ as a result of the separation of its Consumer Health business segment, as of August 30, 2023? |
| financebench_id_01491 | 4 | 4 | +0 | What is the amount of the cash proceeds that JnJ realised from the separation of Kenvue (formerly Consumer Health business segment), as of August 30, 2023? |
| financebench_id_01487 | 4 | 4 | +0 | Did JnJ's net earnings as a percent of sales increase in Q2 of FY2023 compared to Q2 of FY2022? |
| financebench_id_00394 | 4 | 4 | +0 | In 2022 Q2, which of JPM's business segments had the highest net income? |
| financebench_id_04412 | 4 | 4 | +0 | We need to calculate a reasonable approximation (or exact number if possible) of a financial metric. Basing your judgment by information plainly provided in the balance sheet and the P&L statement, what is Lockheed Martin's FY2020 asset turnover ratio? Asset turnover ratio is defined as: FY2020 revenue / (average total assets between FY2019 and FY2020). Round your answer to two decimal places. |
| financebench_id_03718 | 4 | 4 | +0 | What is Lockheed Martin's 2 year total revenue CAGR from FY2020 to FY2022 (in units of percents and round to one decimal place)? Provide a response to the question by primarily using the statement of income. |
| financebench_id_03849 | 4 | 4 | +0 | What is the FY2018 - FY2020 3 year average of capex as a % of revenue for MGM Resorts? Answer in units of percents and round to one decimal place. Please utilize information provided primarily within the statement of cash flows and the statement of income. |
| financebench_id_01254 | 4 | 4 | +0 | Has MGM Resorts paid dividends to common shareholders in FY2022? |
| financebench_id_00382 | 4 | 4 | +0 | Which region had the Highest EBITDAR Contribution for MGM during FY2022? |
| financebench_id_01911 | 0 | 0 | +0 | What was MGM's interest coverage ratio using FY2022 Adjusted EBIT as the numerator and annual Interest Expense as the denominator? |
| financebench_id_01912 | 4 | 4 | +0 | Which region had the worst topline performance for MGM during FY2022? |
| financebench_id_00407 | 4 | 4 | +0 | Which type of debt received the largest investment among the short term investments for MGM in H1 FY2023? |
| financebench_id_04700 | 4 | 4 | +0 | What is the FY2016 COGS for Microsoft? Please state answer in USD millions. Provide a response to the question by primarily using the statement of income. |
| financebench_id_04080 | 4 | 4 | +0 | When primarily referencing the income statement and the statement of financial position, what is the FY2021 inventory turnover ratio for Nike? Inventory turnover ratio is defined as: (FY2021 COGS) / (average inventory between FY2020 and FY2021). Round your answer to two decimal places. |
| financebench_id_01163 | 4 | 4 | +0 | Among operations, investing, and financing activities, which brought in the most (or lost the least) cash flow for Nike in FY2023? |
| financebench_id_00080 | 1 | 1 | +0 | Does Paypal have positive working capital based on FY2022 data? If working capital is not a useful or relevant metric for this company, then please state that and explain why. |
| financebench_id_04980 | 4 | 4 | +0 | What is the FY2021 capital expenditure amount (in USD billions) for PepsiCo? Respond to the question by assuming the perspective of an investment analyst who can only use the details shown within the statement of cash flows. |
| financebench_id_00705 | 4 | 4 | +0 | By how much did Pepsico increase its unsecured five year revolving credit agreement on May 26, 2023? |
| financebench_id_00882 | 4 | 4 | +0 | As of May 26, 2023, what is the total amount Pepsico may borrow under its unsecured revolving credit agreements? |
| financebench_id_01474 | 4 | 4 | +0 | As of FY2023Q1, why did Pepsico raise full year guidance for FY2023? |
| financebench_id_01476 | 4 | 4 | +0 | As of FY2023Q1, by how many percentage points did Pepsico raise full year guidance in respect of core constant currency EPS growth? |
| financebench_id_00302 | 4 | 4 | +0 | Did Pfizer grow its PPNE between FY20 and FY21? |
| financebench_id_00702 | 4 | 4 | +0 | Were there any potential events that are not in Pfizer's standard business operations that substantially increased net income in 2019? |
| financebench_id_02416 | 4 | 4 | +0 | What are three main companies acquired by Pfizer mentioned in this 10K report? |
| financebench_id_00799 | 4 | 1 | -3 | Has AMCOR's quick ratio improved or declined between FY2023 and FY2022? If the quick ratio is not something that a financial analyst would ask about a company like this, then state that and explain why. |

## 最终解释约束

该test结果只能用于报告泛化能力，不能再回流到Repair Agent。如果需要继续研发，必须换用新的开发集或新的数据集。
