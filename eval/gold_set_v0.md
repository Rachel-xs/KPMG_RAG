# Gold Set v0 — Microsoft 10-Q Draft

**Owner:** Yulei Ding · RAG team

**Status:** Draft — pending human review.

30 newly drafted questions: **12 basic / 10 comparative / 8 deep**, including **10 quantitative** questions. The original team set of 12 questions and the pilot corpus were unavailable; this is a new starter set, not a verified expansion of that earlier set.

## Source

- Company: Microsoft Corporation (MSFT), CIK `0000789019`.
- Filing: 10-Q, accession `0001193125-26-191507`, filed 2026-04-29; period ended 2026-03-31.
- [Original SEC HTML report](https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm)
- [Data-team HTML copy](https://github.com/michaelliruoxi/data_engineering_kpmg/blob/8dd4e2abf2cf2275323ee55e8af7394eea46a946/data/raw/sec/0001193125-26-191507/msft-20260331.htm)
- Source SHA-256: `a615ae0de8fe27dd8d1032978b1c810305d3cf7a864b386807cd25a73fc70d59`

All questions are grounded in this single filing. Comparative questions use periods or segments disclosed within it. There is no cross-company or cross-document coverage yet. Quarterly periods end March 31; nine-month periods begin July 1. Fiscal 2026 ends June 30, 2026. Amounts are USD millions unless specified otherwise.

## Review and scoring conventions

- Basic: direct lookup or definition. Comparative: explicit period, segment, or measure comparison. Deep: multi-step derivation or integration of multiple evidence regions. Labels are provisional, not measured difficulty.
- Quantitative means an exact numerical answer or calculation is required. There are 3 basic, 4 comparative, and 3 deep quantitative questions.
- Verify every answer point against the cited evidence; accept faithful paraphrases and equivalent units. Keep periods, signs, GAAP/non-GAAP distinctions, and percentage versus percentage-point changes explicit.
- Round final percentage calculations to two decimals; tolerance is 0.01 percentage/percentage point. Exact displayed USD-million lookup and difference answers have zero tolerance.
- Ask a second teammate to review before promoting any sample to approved gold. No human review or RAG evaluation has been performed.
- Chunk IDs are pending the pilot-corpus handoff. Source XPath locators refer to the pinned HTML parsed with lxml, not cleaned-text offsets. Evidence quotations below collapse whitespace.
- Keep this file’s questions, answers, and grading metadata out of the searchable corpus to prevent benchmark leakage.
- Some questions share evidence; aggregate scores are correlated. Diversify and version the set when additional documents arrive.

## Questions

### GSv0-MSFT-001 — basic · quantitative

**Question:** What was Microsoft’s total revenue for the three months ended March 31, 2026? State the amount in USD millions.

**Reference answer:** USD 82,886 million.

**Required answer points:**
- 82,886
- USD millions
- Three months, not nine months

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [income](#evidence-income)

**Calculation:** `revenue`

**Inputs:** `revenue = 82886`

**Expected calculation result:** 82886 USD million; absolute tolerance 0.

**Review status:** Pending human review.

### GSv0-MSFT-002 — basic · quantitative

**Question:** What was Microsoft’s GAAP net income for the three months ended March 31, 2026, in USD millions?

**Reference answer:** USD 31,778 million.

**Required answer points:**
- 31,778
- GAAP net income
- USD millions

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [income](#evidence-income)

**Calculation:** `net_income`

**Inputs:** `net_income = 31778`

**Expected calculation result:** 31778 USD million; absolute tolerance 0.

**Review status:** Pending human review.

### GSv0-MSFT-003 — basic · quantitative

**Question:** What was Microsoft’s net cash from operations for the nine months ended March 31, 2026, in USD millions?

**Reference answer:** USD 127,494 million.

**Required answer points:**
- 127,494
- Nine-month period
- USD millions

**Period:** `nine_months_ended_2026-03-31`

**Evidence:** [cashflow](#evidence-cashflow)

**Calculation:** `operating_cash_flow`

**Inputs:** `operating_cash_flow = 127494`

**Expected calculation result:** 127494 USD million; absolute tolerance 0.

**Review status:** Pending human review.

### GSv0-MSFT-004 — basic

**Question:** Name Microsoft’s reportable segments in this filing.

**Reference answer:** Productivity and Business Processes; Intelligent Cloud; More Personal Computing.

**Required answer points:**
- All three named segments

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segment_definitions](#evidence-segment-definitions)

**Review status:** Pending human review.

### GSv0-MSFT-005 — basic

**Question:** Which reportable segment includes LinkedIn?

**Reference answer:** Productivity and Business Processes.

**Required answer points:**
- Productivity and Business Processes

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segment_definitions](#evidence-segment-definitions)

**Review status:** Pending human review.

### GSv0-MSFT-006 — basic

**Question:** Which reportable segment includes Azure and other cloud services?

**Reference answer:** Intelligent Cloud, within Server products and cloud services.

**Required answer points:**
- Intelligent Cloud
- Server products and cloud services

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segment_definitions](#evidence-segment-definitions)

**Review status:** Pending human review.

### GSv0-MSFT-007 — basic

**Question:** Which reportable segment includes Xbox hardware and Xbox content and services?

**Reference answer:** More Personal Computing, within Gaming.

**Required answer points:**
- More Personal Computing
- Gaming

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segment_definitions](#evidence-segment-definitions)

**Review status:** Pending human review.

### GSv0-MSFT-008 — basic

**Question:** What categories make up Microsoft Cloud revenue as defined in the filing?

**Reference answer:** Microsoft 365 Commercial cloud, Azure and other cloud services, the commercial portion of LinkedIn, and Dynamics 365.

**Required answer points:**
- Microsoft 365 Commercial cloud
- Azure and other cloud services
- Commercial portion of LinkedIn
- Dynamics 365

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [cloud_definition](#evidence-cloud-definition)

**Review status:** Pending human review.

### GSv0-MSFT-009 — basic

**Question:** What does revenue allocated to remaining performance obligations include?

**Reference answer:** Unearned revenue and amounts expected to be invoiced and recognized as revenue in future periods.

**Required answer points:**
- Unearned revenue
- Future invoicing and recognition

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [rpo](#evidence-rpo)

**Review status:** Pending human review.

### GSv0-MSFT-010 — basic

**Question:** Which investment-related items are excluded from the adjusted net income and adjusted diluted EPS measures?

**Reference answer:** Net gains and losses from investments in OpenAI.

**Required answer points:**
- Net gains and losses
- Investments in OpenAI

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [tax_nongaap](#evidence-tax-nongaap)

**Review status:** Pending human review.

### GSv0-MSFT-011 — basic

**Question:** What accounting method does Microsoft use for its OpenAI investment, and what method is used to calculate its equity-method income or loss?

**Reference answer:** The equity method, using hypothetical liquidation at book value (HLBV) to calculate income or loss because liquidation rights and priorities differ from the underlying ownership interest.

**Required answer points:**
- Equity method
- HLBV
- Liquidation rights differ from ownership interest

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [openai_accounting](#evidence-openai-accounting)

**Review status:** Pending human review.

### GSv0-MSFT-012 — basic

**Question:** How does Microsoft define cash equivalents in its investment policy?

**Reference answer:** Highly liquid interest-earning investments with a maturity of three months or less at the date of purchase.

**Required answer points:**
- Highly liquid interest-earning investments
- Maturity at date of purchase

**Period:** `accounting_policy`

**Evidence:** [cash_equivalents](#evidence-cash-equivalents)

**Review status:** Pending human review.

### GSv0-MSFT-013 — comparative · quantitative

**Question:** Calculate Microsoft’s year-over-year total revenue growth for the three months ended March 31, 2026. Use the displayed amounts and round the percentage to two decimals.

**Reference answer:** Revenue increased by USD 12,820 million, from 70,066 to 82,886 million, a 18.30% increase.

**Required answer points:**
- Same three-month periods
- Increase
- 18.30%

**Period:** `three_months_ended_2026-03-31_vs_2025-03-31`

**Evidence:** [income](#evidence-income)

**Calculation:** `(current - prior) / prior * 100`

**Inputs:** `current = 82886`, `prior = 70066`

**Expected calculation result:** 18.30 percent; absolute tolerance 0.01.

**Review status:** Pending human review.

### GSv0-MSFT-014 — comparative · quantitative

**Question:** For the nine months ended March 31 in 2026 and 2025, calculate operating cash flow less cash additions to property and equipment. Use that specific definition, not a company-defined non-GAAP measure. Did this cash surplus increase or decrease?

**Reference answer:** The specified surplus was USD 47,348 million in 2026 (127,494 - 80,146), versus 46,043 million in 2025 (93,515 - 47,472). It increased by USD 1,305 million.

**Required answer points:**
- 2026: 47,348
- 2025: 46,043
- Increase of 1,305 USD million
- Cash capex definition; not total asset additions

**Period:** `nine_months_ended_2026-03-31_vs_2025-03-31`

**Evidence:** [cashflow](#evidence-cashflow)

**Calculation:** `(ocf_current - capex_current) - (ocf_prior - capex_prior)`

**Inputs:** `ocf_current = 127494`, `capex_current = 80146`, `ocf_prior = 93515`, `capex_prior = 47472`

**Expected calculation result:** 1305 USD million; absolute tolerance 0.

**Review status:** Pending human review.

### GSv0-MSFT-015 — comparative · quantitative

**Question:** Compare quarterly operating margins for Productivity and Business Processes and Intelligent Cloud for the three months ended March 31, 2026. Calculate operating income divided by segment revenue, round to two decimals, and identify the higher margin.

**Reference answer:** Productivity and Business Processes: 59.90% (20,973 / 35,013). Intelligent Cloud: 39.66% (13,753 / 34,681). PBP is higher by 20.24 percentage points.

**Required answer points:**
- PBP 59.90%
- IC 39.66%
- PBP higher
- Percentage-point distinction

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segments](#evidence-segments)

**Calculation:** `(pbp_income / pbp_revenue - ic_income / ic_revenue) * 100`

**Inputs:** `pbp_income = 20973`, `pbp_revenue = 35013`, `ic_income = 13753`, `ic_revenue = 34681`

**Expected calculation result:** 20.24 percentage point; absolute tolerance 0.01.

**Review status:** Pending human review.

### GSv0-MSFT-016 — comparative · quantitative

**Question:** How much did total cash, cash equivalents, and short-term investments change from June 30, 2025 to March 31, 2026? Use USD millions and calculate the percentage change relative to June 30, 2025.

**Reference answer:** They decreased by USD 16,293 million, from 94,565 to 78,272 million, a 17.23% decrease.

**Required answer points:**
- Decrease 16,293 USD million
- -17.23%
- Point-in-time balances

**Period:** `2026-03-31_vs_2025-06-30`

**Evidence:** [balance](#evidence-balance)

**Calculation:** `(current - prior) / prior * 100`

**Inputs:** `current = 78272`, `prior = 94565`

**Expected calculation result:** -17.23 percent; absolute tolerance 0.01.

**Review status:** Pending human review.

### GSv0-MSFT-017 — comparative

**Question:** For the quarter ended March 31, 2026, contrast the reported revenue trends in Intelligent Cloud and More Personal Computing, including their principal drivers.

**Reference answer:** Intelligent Cloud revenue increased, driven by Azure. More Personal Computing revenue decreased due to lower hardware sales across Devices and Gaming, partly offset by Search advertising growth.

**Required answer points:**
- IC increased; Azure
- MPC decreased; Devices/Gaming hardware
- Search advertising offset

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [quarter_overview](#evidence-quarter-overview)

**Review status:** Pending human review.

### GSv0-MSFT-018 — comparative

**Question:** How did Microsoft’s reported quarterly gross-margin-percentage trends differ between Productivity and Business Processes and Intelligent Cloud?

**Reference answer:** PBP’s gross margin percentage increased slightly because of Microsoft 365 Commercial cloud efficiency gains despite AI investment and usage. IC’s decreased because of continued AI infrastructure investment, partly offset by Azure efficiency gains.

**Required answer points:**
- PBP slight increase
- IC decrease
- Efficiency versus AI investment

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [segment_quarter_a](#evidence-segment-quarter-a)

**Review status:** Pending human review.

### GSv0-MSFT-019 — comparative

**Question:** Compare Microsoft’s explanations for More Personal Computing revenue in the three-month and nine-month periods ended March 31, 2026.

**Reference answer:** Quarterly revenue decreased because lower Devices and Gaming hardware sales outweighed part of Search advertising growth. Nine-month revenue was relatively unchanged, with Search advertising growth offset by Gaming decline.

**Required answer points:**
- Quarter decreased
- Nine months relatively unchanged
- Distinct offsetting drivers

**Period:** `three_and_nine_months_ended_2026-03-31`

**Evidence:** [quarter_overview](#evidence-quarter-overview)

**Review status:** Pending human review.

### GSv0-MSFT-020 — comparative

**Question:** Contrast the main drivers of Microsoft’s higher effective tax rate in the three-month and nine-month periods ended March 31, 2026.

**Reference answer:** Both periods were affected by changes in the U.S./foreign mix of earnings and tax expenses. The nine-month increase also reflected deferred tax expense attributable to the OpenAI recapitalization dilution gain.

**Required answer points:**
- Mix of earnings/tax expenses in both
- Additional OpenAI-related deferred tax expense in nine months

**Period:** `three_and_nine_months_ended_2026-03-31`

**Evidence:** [tax_nongaap](#evidence-tax-nongaap)

**Review status:** Pending human review.

### GSv0-MSFT-021 — comparative

**Question:** Compare the directions of the OpenAI investment effects on current-year quarterly versus nine-month net income and diluted EPS.

**Reference answer:** Quarterly results were negatively affected by OpenAI investment net losses; nine-month results were positively affected by net gains. These are different reporting durations, not contradictory results.

**Required answer points:**
- Quarterly negative
- Nine-month positive
- Keep durations distinct

**Period:** `three_and_nine_months_ended_2026-03-31`

**Evidence:** [quarter_overview](#evidence-quarter-overview), [reconciliation_liquidity](#evidence-reconciliation-liquidity)

**Review status:** Pending human review.

### GSv0-MSFT-022 — comparative

**Question:** Contrast the stated drivers of nine-month operating cash flow and investing cash outflow changes versus the prior year.

**Reference answer:** Operating cash flow increased with higher customer receipts and lower income-tax payments, partly offset by higher supplier payments. Investing outflow increased with higher cash additions to property and equipment, other investing to facilitate component purchases, and lower cash from net investment purchases, sales, and maturities.

**Required answer points:**
- Customer receipts and tax payments
- Supplier-payment offset
- Property/equipment additions
- Component purchases and investment activity

**Period:** `nine_months_ended_2026-03-31_vs_2025-03-31`

**Evidence:** [cash_drivers](#evidence-cash-drivers)

**Review status:** Pending human review.

### GSv0-MSFT-023 — deep · quantitative

**Question:** Reconcile Microsoft’s change in cash and cash equivalents for the nine months ended March 31, 2026 using operating, financing, investing, and foreign-exchange cash flows. Then reconcile the ending cash balance to the balance sheet. Use USD millions.

**Reference answer:** 127,494 - 40,767 - 84,669 - 195 = 1,863 million increase. Beginning cash 30,242 + 1,863 = ending cash 32,105 million, which agrees with the March 31, 2026 balance sheet.

**Required answer points:**
- Correct cash-flow signs
- FX -195 included
- Change 1,863
- Ending 32,105 agrees with balance sheet

**Period:** `nine_months_ended_2026-03-31`

**Evidence:** [cashflow](#evidence-cashflow), [balance](#evidence-balance)

**Calculation:** `ocf + financing + investing + fx`

**Inputs:** `ocf = 127494`, `financing = -40767`, `investing = -84669`, `fx = -195`

**Expected calculation result:** 1863 USD million; absolute tolerance 0.

**Review status:** Pending human review.

### GSv0-MSFT-024 — deep · quantitative

**Question:** Reconcile the three segments’ year-over-year quarterly revenue changes to Microsoft’s total change for the three months ended March 31, 2026. Calculate Intelligent Cloud’s share of the net total increase and explain its primary driver.

**Reference answer:** PBP increased 5,069 million, IC increased 7,930 million, and MPC decreased 179 million. Their sum is 12,820 million, matching the consolidated increase. IC contributed 61.86% of the net increase, driven by Azure and other cloud services.

**Required answer points:**
- 5,069 + 7,930 - 179 = 12,820
- IC share 61.86% of net increase
- Azure driver
- USD millions

**Period:** `three_months_ended_2026-03-31_vs_2025-03-31`

**Evidence:** [segments](#evidence-segments), [income](#evidence-income), [segment_quarter_a](#evidence-segment-quarter-a)

**Calculation:** `(ic_current - ic_prior) / (total_current - total_prior) * 100`

**Inputs:** `ic_current = 34681`, `ic_prior = 26751`, `total_current = 82886`, `total_prior = 70066`

**Expected calculation result:** 61.86 percent; absolute tolerance 0.01.

**Review status:** Pending human review.

### GSv0-MSFT-025 — deep · quantitative

**Question:** Derive Microsoft’s revenue for the first six months of fiscal 2026 and fiscal 2025 from the nine-month and third-quarter columns. Calculate the year-over-year growth for those six-month periods. State the date ranges and use USD millions.

**Reference answer:** July 1–December 31, 2025 (first six months of FY2026): 241,832 - 82,886 = 158,946 million. July 1–December 31, 2024 (FY2025): 205,283 - 70,066 = 135,217 million. Growth was 17.55%. The quarter must be subtracted, not added to the overlapping nine-month amount.

**Required answer points:**
- FY2026 dates July–December 2025
- FY2025 dates July–December 2024
- 158,946 and 135,217
- 17.55%
- Avoid double-counting

**Period:** `six_months_ended_2025-12-31_vs_2024-12-31`

**Evidence:** [income](#evidence-income)

**Calculation:** `((nine_current - quarter_current) / (nine_prior - quarter_prior) - 1) * 100`

**Inputs:** `nine_current = 241832`, `quarter_current = 82886`, `nine_prior = 205283`, `quarter_prior = 70066`

**Expected calculation result:** 17.55 percent; absolute tolerance 0.01.

**Review status:** Pending human review.

### GSv0-MSFT-026 — deep

**Question:** Explain why More Personal Computing’s quarterly operating income increased even though its revenue decreased. Connect the consolidated revenue narrative with the segment’s cost and margin explanations.

**Reference answer:** Lower Devices and Gaming hardware sales reduced revenue, partly offset by Search advertising growth. Lower hardware sales also reduced cost of revenue; gross margin increased with Search advertising and Gaming, and the sales mix shifted toward higher-margin businesses. These improvements more than offset higher operating expenses, allowing operating income to increase.

**Required answer points:**
- Revenue decline and search offset
- Lower hardware cost of revenue
- Higher-margin mix/gross margin
- Higher operating expenses did not erase gain

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [quarter_overview](#evidence-quarter-overview), [segment_quarter_b](#evidence-segment-quarter-b)

**Review status:** Pending human review.

### GSv0-MSFT-027 — deep

**Question:** Explain how Microsoft’s quarterly gross margin in dollars could increase while its gross margin percentage decreased. Use the income statement and management’s reported drivers without assuming that margin dollars and margin percentage are the same measure.

**Reference answer:** Revenue and gross-margin dollars both increased, but revenue grew faster than gross-margin dollars, so gross margin as a share of revenue declined. Management attributed percentage pressure to continued AI infrastructure investment and growing AI usage, partially offset by Microsoft Cloud efficiency gains.

**Required answer points:**
- Distinguish dollars from ratio
- Revenue grew faster than margin dollars
- AI investment and usage pressure
- Cloud efficiency offset

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [income](#evidence-income), [quarter_overview](#evidence-quarter-overview)

**Review status:** Pending human review.

### GSv0-MSFT-028 — deep

**Question:** Why should Microsoft Cloud revenue not be added to the reportable segments’ revenues when constructing total company revenue? Identify the relevant components and explain the overlap.

**Reference answer:** Microsoft Cloud is a cross-cutting revenue grouping, not an additional segment. It includes Microsoft 365 Commercial cloud, Azure and other cloud services, commercial LinkedIn, and Dynamics 365. These are already included in PBP and IC product/service revenue and therefore in consolidated segment revenue; adding Cloud again would double-count.

**Required answer points:**
- Cross-cutting grouping
- Cloud components
- Existing PBP/IC revenues
- Double-counting

**Period:** `three_months_ended_2026-03-31`

**Evidence:** [cloud_definition](#evidence-cloud-definition), [segment_definitions](#evidence-segment-definitions), [segments](#evidence-segments)

**Review status:** Pending human review.

### GSv0-MSFT-029 — deep

**Question:** Connect the OpenAI recapitalization accounting with the nine-month GAAP versus adjusted net-income comparison. Why does excluding OpenAI effects reduce current-year net income but increase prior-year net income?

**Reference answer:** The recapitalization decreased Microsoft’s proportionate ownership and produced a dilution gain. Nine-month current-year OpenAI investment effects were net gains, primarily from that dilution gain, so removing their after-tax effect lowers adjusted net income. Prior-year effects were net losses, so excluding them raises adjusted net income. The adjustment excludes OpenAI gains/losses, not all investment income.

**Required answer points:**
- Dilution gain despite lower ownership
- Current-year gains removed
- Prior-year losses added back
- After-tax distinction
- OpenAI-specific adjustment

**Period:** `nine_months_ended_2026-03-31_vs_2025-03-31`

**Evidence:** [openai_accounting](#evidence-openai-accounting), [openai_gains](#evidence-openai-gains), [reconciliation_liquidity](#evidence-reconciliation-liquidity), [tax_nongaap](#evidence-tax-nongaap)

**Review status:** Pending human review.

### GSv0-MSFT-030 — deep

**Question:** Explain why commercial remaining performance obligations and balance-sheet unearned revenue should not be treated as interchangeable measures or added together as independent revenue pools.

**Reference answer:** Remaining performance obligations include both unearned revenue and amounts expected to be invoiced and recognized in future periods, while unearned revenue mainly reflects advance billings/payments before recognition. Commercial RPO is also a commercial-scope measure, whereas balance-sheet unearned revenue is company-wide. They overlap and differ in invoicing status and scope; adding them double-counts overlapping commitments and neither is current-period recognized revenue.

**Required answer points:**
- RPO includes unearned and future invoicing
- Advance billing/payment distinction
- Commercial versus company-wide scope
- Overlap; not current-period revenue

**Period:** `as_of_2026-03-31`

**Evidence:** [rpo](#evidence-rpo), [unearned](#evidence-unearned), [balance](#evidence-balance)

**Review status:** Pending human review.

## Evidence catalog

All evidence below comes from the source HTML linked above. Table and paragraph blocks preserve context; they are not proposed retrieval chunks or finalized passage relevance labels.

### Evidence income

**Section:** Part I Item 1 — Income Statements

**Original HTML XPath:** `/html/body/div[9]/table`

(In millions, except per share amounts) (Unaudited) Three Months EndedMarch 31, Nine Months EndedMarch 31, 2026 2025 2026 2025 Revenue: Product $ 15,089 $ 15,319 $ 47,462 $ 46,810 Service and other 67,797 54,747 194,370 158,473 Total revenue 82,886 70,066 241,832 205,283 Cost of revenue: Product 2,733 3,037 9,160 10,187 Service and other 24,095 18,882 67,689 53,630 Total cost of revenue 26,828 21,919 76,849 63,817 Gross margin 56,058 48,147 164,983 141,466 Research and development 8,915 8,198 25,565 23,659 Sales and marketing 6,814 6,212 19,115 18,369 General and administrative 1,931 1,737 5,669 5,233 Operating income 38,398 32,000 114,634 94,205 Other income (expense), net 942 (623 ) 7,253 (3,194 ) Income before income taxes 39,340 31,377 121,887 91,011 Provision for income taxes 7,562 5,553 23,904 16,412 Net income $ 31,778 $ 25,824 $ 97,983 $ 74,599 Earnings per share: Basic $ 4.28 $ 3.47 $ 13.19 $ 10.03 Diluted $ 4.27 $ 3.46 $ 13.14 $ 9.99 Weighted average shares outstanding: Basic 7,426 7,434 7,430 7,434 Diluted 7,445 7,461 7,457 7,466

### Evidence balance

**Section:** Part I Item 1 — Balance Sheets

**Original HTML XPath:** `/html/body/div[15]/table`

(In millions) (Unaudited) March 31,2026 June 30,2025 Assets Current assets: Cash and cash equivalents $ 32,105 $ 30,242 Short-term investments 46,167 64,323 Total cash, cash equivalents, and short-term investments 78,272 94,565 Accounts receivable, net of allowance for doubtful accounts of $794 and $944 60,041 69,905 Inventories 1,219 938 Other current assets 35,797 25,723 Total current assets 175,329 191,131 Property and equipment, net of accumulated depreciation of $111,723 and $93,653 283,228 204,966 Operating lease right-of-use assets 24,403 24,823 Equity and other investments 33,683 15,405 Goodwill 119,661 119,509 Intangible assets, net 19,325 22,604 Other long-term assets 38,599 40,565 Total assets $ 694,228 $ 619,003 Liabilities and stockholders’ equity Current liabilities: Accounts payable $ 37,513 $ 27,724 Current portion of long-term debt 8,839 2,999 Accrued compensation 11,270 13,709 Short-term income taxes 3,563 7,211 Short-term unearned revenue 50,924 64,555 Other current liabilities 24,552 25,020 Total current liabilities 136,661 141,218 Long-term debt 31,423 40,152 Long-term income taxes 27,941 25,986 Long-term unearned revenue 2,753 2,710 Deferred income taxes 2,899 2,835 Operating lease liabilities 16,703 17,437 Other long-term liabilities 61,481 45,186 Total liabilities 279,861 275,524 Commitments and contingencies Stockholders’ equity: Common stock and paid-in capital – shares authorized 24,000; outstanding 7,429 and 7,434 115,069 109,095 Retained earnings 302,526 237,731 Accumulated other comprehensive loss (3,228 ) (3,347 ) Total stockholders’ equity 414,367 343,479 Total liabilities and stockholders’ equity $ 694,228 $ 619,003

### Evidence cashflow

**Section:** Part I Item 1 — Cash Flows Statements

**Original HTML XPath:** `/html/body/div[18]/table`

(In millions) (Unaudited) Three Months EndedMarch 31, Nine Months EndedMarch 31, 2026 2025 2026 2025 Operations Net income $ 31,778 $ 25,824 $ 97,983 $ 74,599 Adjustments to reconcile net income to net cash from operations: Depreciation, amortization, and other 10,167 7,734 27,512 20,116 Stock-based compensation expense 3,081 2,980 9,283 8,901 Net recognized losses (gains) on investments and derivatives (1,280 ) 708 (7,304 ) 3,387 Deferred income taxes 2,602 (2,244 ) 9,539 (4,835 ) Changes in operating assets and liabilities: Accounts receivable (4,707 ) (2,461 ) 8,347 5,598 Inventories (161 ) 52 (283 ) 390 Other current assets 758 1,076 215 642 Other long-term assets (932 ) (518 ) (2,614 ) (3,368 ) Accounts payable 2,320 1,179 2,903 1,221 Unearned revenue (166 ) (1,032 ) (13,067 ) (12,923 ) Income taxes 2,296 1,298 (1,568 ) (1,081 ) Other current liabilities 2,539 2,839 (166 ) 576 Other long-term liabilities (1,616 ) (391 ) (3,286 ) 292 Net cash from operations 46,679 37,044 127,494 93,515 Financing Repayments of debt, maturities of 90 days or less 0 0 0 (5,746 ) Repayments of debt 0 (2,250 ) (3,000 ) (3,216 ) Common stock issued 541 546 1,489 1,508 Common stock repurchased (4,627 ) (4,781 ) (17,692 ) (13,874 ) Common stock cash dividends paid (6,756 ) (6,169 ) (19,687 ) (17,913 ) Other, net (509 ) (382 ) (1,877 ) (1,614 ) Net cash used in financing (11,351 ) (13,036 ) (40,767 ) (40,855 ) Investing Additions to property and equipment (30,876 ) (16,745 ) (80,146 ) (47,472 ) Acquisition of companies, net of cash acquired and divestitures, and purchases of intangible and other assets (258 ) (981 ) (1,291 ) (4,235 ) Purchases of investments (12,006 ) (4,474 ) (39,522 ) (8,144 ) Maturities of investments 11,976 6,721 30,424 11,461 Sales of investments 6,358 2,161 15,311 6,688 Other, net (2,599 ) 604 (9,445 ) (325 ) Net cash used in investing (27,405 ) (12,714 ) (84,669 ) (42,027 ) Effect of foreign exchange rates on cash and cash equivalents (114 ) 52 (195 ) (120 ) Net change in cash and cash equivalents 7,809 11,346 1,863 10,513 Cash and cash equivalents, beginning of period 24,296 17,482 30,242 18,315 Cash and cash equivalents, end of period $ 32,105 $ 28,828 $ 32,105 $ 28,828

### Evidence segments

**Section:** Note 16 — Segment Information and Geographic Data

**Original HTML XPath:** `/html/body/div[84]/div/*[name()='ix:continuation']/div[2]/*[name()='ix:nonnumeric']/table`

(In millions) Three Months Ended March 31, Nine Months Ended March 31, 2026 2025 2026 2025 Productivity and Business Processes Revenue $ 35,013 $ 29,944 $ 102,149 $ 87,698 Cost of revenue 6,197 5,517 18,028 16,380 Operating expenses 7,843 7,048 22,142 20,538 Operating income $ 20,973 $ 17,379 $ 61,979 $ 50,780 Intelligent Cloud Revenue $ 34,681 $ 26,751 $ 98,485 $ 76,387 Cost of revenue 15,120 10,307 41,000 28,326 Operating expenses 5,808 5,349 16,468 15,612 Operating income $ 13,753 $ 11,095 $ 41,017 $ 32,449 More Personal Computing Revenue $ 13,192 $ 13,371 $ 41,198 $ 41,198 Cost of revenue 5,511 6,095 17,821 19,111 Operating expenses 4,009 3,750 11,739 11,111 Operating income $ 3,672 $ 3,526 $ 11,638 $ 10,976 Total Revenue $ 82,886 $ 70,066 $ 241,832 $ 205,283 Cost of revenue 26,828 21,919 76,849 63,817 Operating expenses 17,660 16,147 50,349 47,261 Operating income $ 38,398 $ 32,000 $ 114,634 $ 94,205

### Evidence segment-definitions

**Section:** Note 16 — Segment definitions and allocation policies

**Original HTML XPath:** `/html/body/div[81]`

Our reportable segments are described below.Productivity and Business ProcessesOur Productivity and Business Processes segment consists of products and services in our portfolio of productivity, communication, and information services, spanning a variety of devices and platforms. This segment primarily comprises:•Microsoft 365 Commercial products and cloud services, including Microsoft 365 Commercial cloud, comprising Microsoft 365 Commercial, Enterprise Mobility + Security, the cloud portion of Windows Commercial, the per-user portion of Power BI, Exchange, SharePoint, Microsoft Teams, Microsoft 365 Security and Compliance, and Microsoft 365 Copilot; and Microsoft 365 Commercial products, comprising Windows Commercial on-premises and Office licensed on-premises. •Microsoft 365 Consumer products and cloud services, including Microsoft 365 Consumer subscriptions, Office licensed on-premises, and other consumer services.•LinkedIn, including Talent Solutions, Marketing Solutions, Premium Subscriptions, and Sales Solutions.•Dynamics products and cloud services, including Dynamics 365, comprising a set of intelligent, cloud-based applications across ERP, CRM, Power Apps, and Power Automate; and on-premises ERP and CRM applications.Intelligent CloudOur Intelligent Cloud segment consists of our public, private, and hybrid server products and cloud services that power modern business and developers. This segment primarily comprises:•Server products and cloud services, including Azure and other cloud services, comprising cloud and AI consumption-based services, GitHub cloud services, Nuance Healthcare cloud services, virtual desktop offerings, and other cloud services; and Server products, comprising SQL Server, Windows Server, Visual Studio, System Center, related Client Access Licenses, and other on-premises offerings.•Enterprise and partner services, including Enterprise Support Services, Industry Solutions, Nuance professional services, Microsoft Partner Network, and Learning Experience.More Personal ComputingOur More Personal Computing segment consists of products and services that put customers at the center of the experience with our technology. This segment primarily comprises:•Windows and Devices, including Windows OEM licensing (Windows Pro and non-Pro licenses sold through the OEM channel) and Devices, comprising Surface and PC accessories.•Gaming, including Xbox hardware and Xbox content and services, comprising first- and third-party content (including games and in-game content), Xbox Game Pass and other subscriptions, Xbox Cloud Gaming, advertising, and other cloud services.•Search advertising (formerly Search and news advertising), comprising Bing, Copilot, Microsoft News, Microsoft Edge, and third-party affiliates.Revenue and costs are generally directly attributed to our segments. However, due to the integrated structure of our business, certain revenue recognized and costs incurred by one segment may benefit other segments. Revenue from certain contracts is allocated among the segments based on the relative value of the underlying products and services, which can include allocation based on actual prices charged, prices when sold separately, or estimated costs plus a profit margin. Cost of revenue is allocated in certain cases based on a relative revenue methodology. Operating expenses that are allocated primarily include those relating to our investments in AI infrastructure and training, as well as marketing of products and services, from which multiple segments benefit and are generally allocated based on relative gross margin.

### Evidence quarter-overview

**Section:** Part I Item 2 — Results of Operations: quarter and nine months

**Original HTML XPath:** `/html/body/div[105]`

Adjusted net income and adjusted diluted earnings per share (“EPS”) are non-GAAP financial measures. These non-GAAP financial measures exclude net gains and losses from investments in OpenAI. Refer to the Non-GAAP Financial Measures section below for a reconciliation of our financial results reported in accordance with GAAP to non-GAAP financial results.Three Months Ended March 31, 2026 Compared with Three Months Ended March 31, 2025Revenue increased $12.8 billion or 18% driven by growth in Microsoft Cloud. Intelligent Cloud revenue increased driven by Azure. Productivity and Business Processes revenue increased driven by Microsoft 365 Commercial cloud. More Personal Computing revenue decreased with lower hardware sales across Devices and Gaming, offset in part by growth in Search advertising.Cost of revenue increased $4.9 billion or 22% driven by growth in Microsoft Cloud.Gross margin increased $7.9 billion or 16% with growth across each of our segments.•Gross margin percentage decreased driven by continued investments in AI infrastructure and growing AI product usage, offset in part by efficiency gains across the Microsoft Cloud.•Microsoft Cloud gross margin percentage decreased to 66% driven by continued investments in AI infrastructure and growing AI product usage, offset in part by efficiency gains in Azure and Microsoft 365 Commercial cloud.Operating expenses increased $1.5 billion or 9% primarily driven by continued investments in research and development compute capacity, AI talent, and data to support product development across the portfolio. Total company headcount declined year-over-year.Operating income increased $6.4 billion or 20% driven by growth in Productivity and Business Processes and Intelligent Cloud.Revenue, gross margin, and operating income included a favorable foreign currency impact of 3%, 3%, and 4%, respectively. Cost of revenue included an unfavorable foreign currency impact of 2%.Current year net income and diluted EPS were negatively impacted by net losses from investments in OpenAI, which resulted in a decrease in net income of $14 million. Prior year net income and diluted EPS were negatively impacted by net losses from investments in OpenAI, which resulted in a decrease in net income and diluted EPS of $583 million and $0.08, respectively.Nine Months Ended March 31, 2026 Compared with Nine Months Ended March 31, 2025Revenue increased $36.5 billion or 18% driven by growth in Microsoft Cloud. Intelligent Cloud revenue increased driven by Azure. Productivity and Business Processes revenue increased driven by Microsoft 365 Commercial cloud. More Personal Computing revenue was relatively unchanged with growth in Search advertising offset by a decline in Gaming.Cost of revenue increased $13.0 billion or 20% driven by growth in Microsoft Cloud.Gross margin increased $23.5 billion or 17% with growth across each of our segments.•Gross margin percentage decreased slightly primarily driven by continued investments in AI infrastructure and growing AI product usage, offset in part by efficiency gains across the Microsoft Cloud.•Microsoft Cloud gross margin percentage decreased to 67% driven by continued investments in AI infrastructure and growing AI product usage, offset in part by efficiency gains in Azure and Microsoft 365 Commercial cloud.Operating expenses increased $3.1 billion or 7% driven by continued investments in research and development compute capacity, AI talent, and data to support product development across the portfolio, impairment and other related expenses in our Gaming business, and higher Copilot advertising expenses. Total company headcount declined year-over-year.Operating income increased $20.4 billion or 22% driven by growth in Productivity and Business Processes and Intelligent Cloud.

### Evidence segment-quarter-a

**Section:** Part I Item 2 — Quarterly PBP and Intelligent Cloud results

**Original HTML XPath:** `/html/body/div[111]`

Operating income increased $3.6 billion or 21%.•Cost of revenue increased $680 million or 12% driven by investments in AI infrastructure to support Microsoft 365 Copilot seat and usage growth.•Gross margin increased $4.4 billion or 18% driven by growth in Microsoft 365 Commercial cloud. Gross margin percentage increased slightly driven by efficiency gains in Microsoft 365 Commercial cloud even with continued investments in AI infrastructure and growing AI product usage.•Operating expenses increased $795 million or 11% driven by continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio, as well as higher Copilot advertising expenses.Revenue, gross margin, and operating income included a favorable foreign currency impact of 4%, 5%, and 7%, respectively. Operating expenses included an unfavorable foreign currency impact of 2%.Intelligent CloudRevenue increased $7.9 billion or 30%.•Server products and cloud services revenue increased $7.8 billion or 32% driven by Azure and other cloud services. Azure and other cloud services revenue grew 40% driven by demand for services across the platform with continued growth across all workloads. Server products revenue increased slightly, primarily driven by higher purchases of licenses running in multi-cloud environments, offset in part by renewals with lower in-period revenue recognition from the mix of contracts and continued customer shift to cloud.•Enterprise and partner services revenue increased $141 million or 7% driven by growth in Enterprise Support Services.Operating income increased $2.7 billion or 24%.•Cost of revenue increased $4.8 billion or 47% driven by investments in AI infrastructure to support growing customer demand and increased GitHub Copilot usage.•Gross margin increased $3.1 billion or 19% driven by growth in Azure. Gross margin percentage decreased driven by the continued investments in AI infrastructure, offset in part by efficiency gains in Azure.•Operating expenses increased $459 million or 9% primarily driven by continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio.Revenue included a favorable foreign currency impact of 2%. Cost of revenue and operating expenses included an unfavorable foreign currency impact of 3% and 2%, respectively.More Personal ComputingRevenue decreased $179 million or 1%.•Windows and Devices revenue decreased $103 million or 2%. Windows OEM and Devices revenue decreased 2% driven by a decline in Devices, offset in part by growth in Windows OEM as OEM partners continue to build inventory due to increasing memory pricing.

### Evidence segment-quarter-b

**Section:** Part I Item 2 — Quarterly More Personal Computing and nine-month PBP results

**Original HTML XPath:** `/html/body/div[114]`

•Gaming revenue decreased $380 million or 7% driven by declines in Xbox content and services and Xbox hardware. Xbox content and services revenue decreased 5% on a prior year comparable that benefited from strong first-party content performance. Xbox hardware revenue decreased 33% driven by lower volume of consoles sold.•Search advertising revenue increased $304 million or 9%. Search advertising revenue excluding traffic acquisition costs increased 12% driven by higher search volume and revenue per search, as well as continued benefit from third-party partnerships.Operating income increased $146 million or 4%.•Cost of revenue decreased $584 million or 10% primarily driven by lower hardware sales.•Gross margin increased $405 million or 6% driven by growth in Search advertising and Gaming. Gross margin percentage increased driven by sales mix shift to higher margin businesses.•Operating expenses increased $259 million or 7% driven by impairment and other related expenses in our Gaming business and continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio.Revenue, gross margin, and operating income included a favorable foreign currency impact of 2%, 2%, and 3%, respectively.Nine Months Ended March 31, 2026 Compared with Nine Months Ended March 31, 2025Productivity and Business ProcessesRevenue increased $14.5 billion or 16%.•Microsoft 365 Commercial products and cloud services revenue increased $10.6 billion or 17%. Microsoft 365 Commercial cloud revenue grew 18% with growth in revenue per user driven by Microsoft 365 E5 and Microsoft 365 Copilot, and continued Microsoft 365 Commercial seat growth. Microsoft 365 Commercial products revenue grew 10% driven by an increase in Office 2024 transactional purchasing, as well as growth in the Windows Commercial on-premises components of Microsoft 365 suite sales.•Microsoft 365 Consumer products and cloud services revenue increased $1.4 billion or 27%. Microsoft 365 Consumer cloud revenue grew 29% driven by growth in revenue per user and continued growth in Microsoft 365 Consumer subscribers.•LinkedIn revenue increased $1.4 billion or 11% with growth across all lines of business.•Dynamics products and cloud services revenue increased $941 million or 17% driven by growth in Dynamics 365. Dynamics 365 revenue grew 20% with growth across all workloads.Operating income increased $11.2 billion or 22%.•Cost of revenue increased $1.6 billion or 10% driven by investments in AI infrastructure to support Microsoft 365 Copilot seat and usage growth.•Gross margin increased $12.8 billion or 18% driven by growth in Microsoft 365 Commercial cloud. Gross margin percentage increased driven by efficiency gains in Microsoft 365 Commercial cloud even with continued investments in AI infrastructure and growing AI product usage.•Operating expenses increased $1.6 billion or 8% driven by continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio, as well as higher Copilot advertising expenses.Revenue, gross margin, and operating income included a favorable foreign currency impact of 2%, 3%, and 4%, respectively.

### Evidence segment-nine

**Section:** Part I Item 2 — Nine-month Intelligent Cloud and More Personal Computing results

**Original HTML XPath:** `/html/body/div[117]`

Intelligent CloudRevenue increased $22.1 billion or 29%.•Server products and cloud services revenue increased $21.8 billion or 31% driven by Azure and other cloud services. Azure and other cloud services revenue grew 40% driven by demand for services across the platform with continued growth across all workloads. Server products revenue increased 1% primarily driven by higher purchases of licenses running in multi-cloud environments.•Enterprise and partner services revenue increased $381 million or 7% driven by growth in Enterprise Support Services.Operating income increased $8.6 billion or 26%.•Cost of revenue increased $12.7 billion or 45% driven by investments in AI infrastructure to support growing customer demand.•Gross margin increased $9.4 billion or 20% driven by growth in Azure. Gross margin percentage decreased driven by the continued investments in AI infrastructure, offset in part by efficiency gains in Azure.•Operating expenses increased $856 million or 5% driven by continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio.Cost of revenue included an unfavorable foreign currency impact of 2%.More Personal ComputingRevenue was relatively unchanged.•Windows and Devices revenue increased slightly. Windows OEM and Devices revenue increased 2% driven by Windows OEM growth of 8% with inventory levels that remained elevated, offset in part by a decline in Devices. •Gaming revenue decreased $1.1 billion or 6% driven by declines in Xbox hardware and Xbox content and services. Xbox hardware revenue decreased 31% driven by lower volume of consoles sold. Xbox content and services revenue decreased 3% on a prior year comparable that benefited from strong first-party content performance, offset in part by growth in Xbox Game Pass.•Search advertising revenue increased $1.0 billion or 10%. Search advertising revenue excluding traffic acquisition costs increased 13% driven by higher search volume and revenue per search, as well as continued benefit from third-party partnerships.Operating income increased $662 million or 6%.•Cost of revenue decreased $1.3 billion or 7% driven by lower hardware sales, offset in part by growth in Search advertising.•Gross margin increased $1.3 billion or 6% driven by growth in Search advertising and Windows OEM. Gross margin percentage increased driven by sales mix shift to higher margin businesses.•Operating expenses increased $628 million or 6% driven by impairment and other related expenses in our Gaming business and continued investments in research and development compute capacity, AI talent, and data to support product development that benefits the entire portfolio.Operating income included a favorable foreign currency impact of 2%.

### Evidence opex

**Section:** Part I Item 2 — Operating Expenses

**Original HTML XPath:** `/html/body/div[120]`

OPERATING EXPENSESResearch and Development (In millions, except percentages) Three Months EndedMarch 31, PercentageChange Nine Months EndedMarch 31, PercentageChange 2026 2025 2026 2025 Research and development $ 8,915 $ 8,198 9% $ 25,565 $ 23,659 8% As a percent of revenue 11% 12% (1)ppt 11% 12% (1)ppt Research and development expenses include payroll, employee benefits, stock-based compensation expense, and other headcount-related expenses associated with product development. Research and development expenses also include technology development costs, including AI training and other infrastructure costs, third-party development and programming costs, and the amortization of purchased software code and services content.Three Months Ended March 31, 2026 Compared with Three Months Ended March 31, 2025Research and development expenses increased $717 million or 9% driven by continued investments in compute capacity, AI talent, and data to support product development across the portfolio, with headcount declining year-over-year.Nine Months Ended March 31, 2026 Compared with Nine Months Ended March 31, 2025Research and development expenses increased $1.9 billion or 8% driven by continued investments in compute capacity, AI talent, and data to support product development across the portfolio, as well as impairment and other related expenses in our Gaming business, with headcount declining year-over-year.Sales and Marketing (In millions, except percentages) Three Months EndedMarch 31, PercentageChange Nine Months EndedMarch 31, PercentageChange 2026 2025 2026 2025 Sales and marketing $ 6,814 $ 6,212 10% $ 19,115 $ 18,369 4% As a percent of revenue 8% 9% (1)ppt 8% 9% (1)ppt Sales and marketing expenses include payroll, employee benefits, stock-based compensation expense, and other headcount-related expenses associated with sales and marketing personnel, and the costs of advertising, promotions, trade shows, seminars, and other programs.Three Months Ended March 31, 2026 Compared with Three Months Ended March 31, 2025Sales and marketing expenses increased $602 million or 10% primarily driven by higher Copilot advertising expenses, with headcount declining year-over-year. Sales and marketing included an unfavorable foreign currency impact of 3%.Nine Months Ended March 31, 2026 Compared with Nine Months Ended March 31, 2025Sales and marketing expenses increased $746 million or 4% driven by higher Copilot advertising expenses, with headcount declining year-over-year. Sales and marketing included an unfavorable foreign currency impact of 2%.General and Administrative (In millions, except percentages) Three Months EndedMarch 31, PercentageChange Nine Months EndedMarch 31, PercentageChange 2026 2025 2026 2025 General and administrative $ 1,931 $ 1,737 11% $ 5,669 $ 5,233 8% As a percent of revenue 2% 2% 0ppt 2% 3% (1)ppt

### Evidence tax-nongaap

**Section:** Part I Item 2 — Income Taxes and Non-GAAP Financial Measures

**Original HTML XPath:** `/html/body/div[126]`

INCOME TAXESEffective Tax RateOur effective tax rate was 19% and 18% for the three months ended March 31, 2026 and 2025, respectively, and 20% and 18% for the nine months ended March 31, 2026 and 2025, respectively. The increase in our effective tax rate for the three months ended March 31, 2026 compared to the prior year was primarily due to changes in the mix of our earnings and tax expenses between the U.S. and foreign countries. The increase in our effective tax rate for the nine months ended March 31, 2026 compared to the prior year was primarily due to changes in the mix of our earnings and tax expenses between the U.S. and foreign countries and deferred tax expense attributable to the dilution gain from the OpenAI Recapitalization.Our effective tax rate was lower than the U.S. federal statutory rate for the three and nine months ended March 31, 2026, primarily due to earnings taxed at lower rates in foreign jurisdictions resulting from producing and distributing our products and services through our foreign regional operations center in Ireland.Uncertain Tax PositionsWe remain under audit by the IRS for tax years 2014 to 2017. With respect to the audit for tax years 2004 to 2013, on September 26, 2023, we received Notices of Proposed Adjustment (“NOPAs”) from the IRS. The primary issues in the NOPAs relate to intercompany transfer pricing. In the NOPAs, the IRS is seeking an additional tax payment of $28.9 billion plus penalties and interest. As of March 31, 2026, we believe our allowances for income tax contingencies are adequate. We disagree with the proposed adjustments and will vigorously contest the NOPAs through the IRS’s administrative appeals office and, if necessary, judicial proceedings. We do not expect a final resolution of these issues in the next 12 months. Based on the information currently available, we do not anticipate a significant increase or decrease to our income tax contingencies for these issues within the next 12 months.We are subject to income tax in many jurisdictions outside the U.S., some of which are currently under audit by local tax authorities. The resolution of these audits is not expected to be material to our consolidated financial statements. Our operations in Ireland remain subject to examination for tax years 2021 and thereafter.NON-GAAP FINANCIAL MEASURESAdjusted other income (expense), net, adjusted net income, and adjusted diluted EPS are non-GAAP financial measures which exclude net (gains) losses from investments in OpenAI. We believe these non-GAAP measures aid investors by providing additional insight into our financial performance and help clarify trends affecting our business. For comparability of reporting, management considers non-GAAP measures in conjunction with GAAP financial results in evaluating business performance. These non-GAAP financial measures presented should not be considered a substitute for, or superior to, the measures of financial performance prepared in accordance with GAAP.

### Evidence reconciliation-liquidity

**Section:** Part I Item 2 — Non-GAAP reconciliation and Liquidity

**Original HTML XPath:** `/html/body/div[129]`

The following table reconciles our financial results reported in accordance with GAAP to non-GAAP financial results: (In millions, except percentages and per share amounts) Three Months EndedMarch 31, PercentageChange Nine Months EndedMarch 31, PercentageChange 2026 2025 2026 2025 Other income (expense), net $ 942 $ (623 ) 251% $ 7,253 $ (3,194 ) 327% Net (gains) losses from investments in OpenAI 19 768 (98)% (5,898 ) 2,692 (319)% Adjusted other income (expense), net (non-GAAP) $ 961 $ 145 563% $ 1,355 $ (502 ) 370% Net income $ 31,778 $ 25,824 23% $ 97,983 $ 74,599 31% Net (gains) losses from investments in OpenAI, net of tax of $(5), $(185), $1,415, and $(647) 14 583 (98)% (4,483 ) 2,045 (319)% Adjusted net income (non-GAAP) $ 31,792 $ 26,407 20% $ 93,500 $ 76,644 22% Diluted earnings per share $ 4.27 $ 3.46 23% $ 13.14 $ 9.99 32% Net (gains) losses from investments in OpenAI 0 0.08 (100)% (0.60 ) 0.28 (314)% Adjusted diluted earnings per share (non-GAAP) $ 4.27 $ 3.54 21% $ 12.54 $ 10.27 22% LIQUIDITY AND CAPITAL RESOURCESWe expect existing cash, cash equivalents, short-term investments, cash flows from operations, and access to capital markets to continue to be sufficient to fund our operating activities and cash commitments for investing and financing activities, such as dividends, share repurchases, debt maturities, and material capital expenditures, for at least the next 12 months and thereafter for the foreseeable future. Cash, Cash Equivalents, and InvestmentsCash, cash equivalents, and short-term investments totaled $78.3 billion and $94.6 billion as of March 31, 2026 and June 30, 2025, respectively. Equity and other investments were $33.7 billion and $15.4 billion as of March 31, 2026 and June 30, 2025, respectively. Our short-term investments are primarily intended to facilitate liquidity and capital preservation. They consist predominantly of highly liquid investment-grade fixed-income securities, diversified among industries and individual issuers. The investments are predominantly U.S. dollar-denominated securities, but also include foreign currency-denominated securities to diversify risk. Our fixed-income investments are exposed to interest rate risk and credit risk. The credit risk and average maturity of our fixed-income portfolio are managed to achieve economic returns that correlate to certain fixed-income indices. The settlement risk related to these investments is insignificant given that the short-term investments held are primarily highly liquid investment-grade fixed-income securities.ValuationIn general, and where applicable, we use quoted prices in active markets for identical assets or liabilities to determine the fair value of our financial instruments. This pricing methodology applies to our Level 1 investments, such as U.S. government securities, common and preferred stock, and mutual funds. If quoted prices in active markets for identical assets or liabilities are not available to determine fair value, then we use quoted prices for similar assets and liabilities or inputs other than the quoted prices that are observable either directly or indirectly. This pricing methodology applies to our Level 2 investments, such as commercial paper, certificates of deposit, U.S. agency securities, foreign government bonds, mortgage- and asset-backed securities, corporate notes and bonds, and municipal securities. Level 3 investments are valued using internally-developed models with unobservable inputs. Assets and liabilities measured at fair value on a recurring basis using unobservable inputs are an immaterial portion of our portfolio.

### Evidence cash-drivers

**Section:** Part I Item 2 — Cash Flows; nine months

**Original HTML XPath:** `/html/body/div[132]/p[3]`

Cash from operations increased $34.0 billion to $127.5 billion for the nine months ended March 31, 2026, primarily due to an increase in cash received from customers and a decrease in cash used to pay income taxes, offset in part by an increase in cash paid to suppliers. Cash used in financing decreased $88 million to $40.8 billion for the nine months ended March 31, 2026, primarily due to a $6.0 billion decrease in cash used for repayments of debt, offset in part by a $3.8 billion increase in common stock repurchases and a $1.8 billion increase in dividends paid. Cash used in investing increased $42.6 billion to $84.7 billion for the nine months ended March 31, 2026, primarily due to a $32.7 billion increase in additions to property and equipment, a $9.1 billion increase in other investing primarily to facilitate the purchase of components, and a $3.8 billion decrease in cash from net investment purchases, sales, and maturities.

### Evidence unearned

**Section:** Part I Item 2 — Unearned Revenue

**Original HTML XPath:** `/html/body/div[132]/p[7]`

Unearned revenue comprises mainly unearned revenue related to volume licensing programs, which may include cloud services and Software Assurance (“SA”). Unearned revenue is generally invoiced annually at the beginning of each contract period for multi-year agreements and recognized ratably over the coverage period. Unearned revenue also includes payments for other offerings for which we have been paid in advance and earn the revenue when we transfer control of the product or service.

### Evidence rpo

**Section:** Note 11 — Remaining Performance Obligations

**Original HTML XPath:** `/html/body/div[66]/div[1]/*[name()='ix:continuation']/p`

Revenue allocated to remaining performance obligations, which includes unearned revenue and amounts expected to be invoiced and recognized as revenue in future periods, was $633 billion as of March 31, 2026. Estimating revenue that will be allocated to remaining performance obligations can involve significant judgments, including identifying and assessing variable consideration and potential renegotiation of commitments. We consider factors such as the nature of the terms and duration of the contract across our portfolio of contracts. Revenue allocated to remaining performance obligations related to the commercial portion of revenue was $627 billion as of March 31, 2026, with a weighted average duration of approximately 2.5 years. We expect to recognize approximately 30% of our total company remaining performance obligation revenue and 25% of our commercial remaining performance obligation revenue over the next 12 months and the remainder thereafter.

### Evidence openai-accounting

**Section:** Note 1 — Investments: OpenAI equity method

**Original HTML XPath:** `/html/body/div[27]/div/*[name()='ix:continuation']/div[1]/*[name()='ix:continuation']/p[4]`

We have a long-term strategic partnership with OpenAI. In October 2025, we signed a new definitive agreement with OpenAI that extends this partnership. Additionally, OpenAI formed a public benefit corporation and completed a recapitalization (“OpenAI Recapitalization”). We have an investment of approximately 27 percent of OpenAI on an as-converted basis accounted for under the equity method of accounting. As a result of the OpenAI Recapitalization, we had a decrease in our proportionate ownership of OpenAI and recorded a dilution gain in other income (expense), net. Refer to Note 3 – Other Income (Expense), Net for additional information. We calculate our equity method income or loss using the hypothetical liquidation at book value (“HLBV”) method because our liquidation rights and priorities differ from our underlying ownership interest. Under the HLBV method, we recognize income or loss based on the change in the amount we would receive if the net assets of the investee were distributed at book value. We have made total funding commitments of $13 billion, of which $11.8 billion has been funded as of March 31, 2026.

### Evidence openai-gains

**Section:** Note 3 — Other Income (Expense), Net

**Original HTML XPath:** `/html/body/div[36]/div[1]/*[name()='ix:continuation']/p[1]`

Other income (expense), net included $19 million of net losses and $5.9 billion of net gains for the three and nine months ended March 31, 2026, respectively, and $768 million and $2.7 billion of net losses for the three and nine months ended March 31, 2025, respectively, from investments in OpenAI, primarily net recognized gains (losses) on our equity method investment reflected in Other, net. The net gains recorded for the nine months ended March 31, 2026 primarily relate to the dilution gain from the OpenAI Recapitalization.

### Evidence cloud-definition

**Section:** Note 16 — Microsoft Cloud revenue

**Original HTML XPath:** `/html/body/div[87]/div/*[name()='ix:continuation']/div[1]/*[name()='ix:nonnumeric']/p[4]`

Our Microsoft Cloud revenue, which includes Microsoft 365 Commercial cloud, Azure and other cloud services, the commercial portion of LinkedIn, and Dynamics 365, was $54.5 billion and $155.1 billion for the three and nine months ended March 31, 2026, respectively, and $42.4 billion and $122.2 billion for the three and nine months ended March 31, 2025, respectively. These amounts are included in Server products and cloud services, Microsoft 365 Commercial products and cloud services, LinkedIn, and Dynamics products and cloud services in the table above.

### Evidence cash-equivalents

**Section:** Note 1 — Investments

**Original HTML XPath:** `/html/body/div[24]/div/*[name()='ix:nonnumeric']/div[4]/*[name()='ix:nonnumeric']/p[2]`

We consider all highly liquid interest-earning investments with a maturity of three months or less at the date of purchase to be cash equivalents. The fair values of these investments approximate their carrying values. In general, investments with original maturities of greater than three months and remaining maturities of less than one year are classified as short-term investments. Investments with maturities beyond one year may be classified as short-term based on their highly liquid nature and because such marketable securities represent the investment of cash that is available for current operations.

## Validation and handoff

Current local checks passed: 30 samples; 12/10/8 category distribution; 10 quantitative samples; 253 structural, formula, and source checks; 19 evidence-region matches against the original HTML; CSV/JSONL agreement; and independent XBRL corroboration of 9 consolidated numerical facts and periods. These checks do not establish full human answer verification, database access, extraction completeness, or retrieval performance.

Next: human review, pilot-corpus coverage check, source-to-chunk ID mapping, and retrieval/answer evaluation. If the earlier 12 questions become available, reconcile duplicates before treating this as their expanded version.

**AI assistance:** Codex assisted in drafting questions, reference answers, evidence annotations, and validation. Students remain responsible for verification, understanding, and any required acknowledgment.
