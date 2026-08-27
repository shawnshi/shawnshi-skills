# 医疗 IT 方案 TCO / ROI 增量现金流模型

仅当任务存在技术方案成本比较或明确 TCO 问题时使用。本模板可形成可审计的 ROI 计算输入，但不单独得出投资组合优先级、预算取舍或商业模式建议；此类结论由 `hit-digital-strategy-partner` 主导。本模板不提供默认折现率、折旧期、维保比例、人力成本或临床收益。

## 1. 先定义决策边界与基准

| 字段 | 内容 |
| :--- | :--- |
| 决策问题 | `{{DECISION_QUESTION}}` |
| 分析主体与适用地区 | `{{ENTITY_AND_REGION}}` |
| 基准方案 | `{{COUNTERFACTUAL_IF_PROPOSAL_IS_NOT_APPROVED}}` |
| 拟议方案 | `{{PROPOSED_OPTION}}` |
| 起止日期与时间粒度 | `{{START_END_PERIOD}}` |
| 币种、含税口径与价格日期 | `{{CURRENCY_TAX_PRICE_DATE}}` |
| 名义/实际现金流口径 | `{{NOMINAL_OR_REAL}}` |
| 折现率及来源 | `{{DISCOUNT_RATE_AND_SOURCE}}` |
| 纳入/排除成本、收益和风险 | `{{INCLUSIONS_AND_EXCLUSIONS}}` |
| 共同成本分摊和残值口径 | `{{ALLOCATION_AND_RESIDUAL_VALUE}}` |

基准是“不批准拟议投资时会发生什么”的反事实，不等同于零成本。它应包括维持现状的必要支出、已批准更改及可核验的风险暴露。基准与拟议方案必须使用相同范围、时间、币种和价格口径。

## 2. 符号与公式

对每个时期 `t`：

`Incremental_Cost_t = Proposed_Cost_t - Baseline_Cost_t`

`Incremental_Benefit_t = Proposed_Benefit_t - Baseline_Benefit_t`

`Net_Cash_Flow_t = Incremental_Benefit_t - Incremental_Cost_t`

因此：

- `Incremental_Cost > 0` 表示拟议方案增加成本；`< 0` 表示节省成本。
- `Incremental_Benefit > 0` 表示拟议方案增加经验证收益。
- `TCO_Delta = Proposed_TCO - Baseline_TCO`；正数表示拟议方案 TCO 更高。
- `Cost_Saving = Baseline_TCO - Proposed_TCO`；正数表示节省。不将 `TCO_Delta` 与 `Cost_Saving` 混用。

净现值：

`NPV = sum(Net_Cash_Flow_t / (1 + r)^t, t=0..N)`

`NPV > 0` 表示在已声明的基准、边界、折现率和假设下，拟议方案的增量价值为正；这不等于临床效果承诺。

投资回报率：

`ROI = (PV_Incremental_Benefits - PV_Incremental_Costs) / PV_Incremental_Costs`

仅在 `PV_Incremental_Costs > 0`、收益可货币化且口径一致时计算。若拟议方案同时减少成本且增加收益，直接报告 NPV 和现金流，不生成无意义的 ROI。

回收期是累计现金流（选择折现或未折现，必须明记）首次从负值达到非负值的时点。未在分析周期内达到时报告“分析期内未回收”，不外推。

## 3. 输入变量合同

| variable_id | 指标 | baseline_value | proposed_value | unit | source/locator | as_of | region/scope | method | evidence_or_assumption | owner | sensitivity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `{{VARIABLE_ID}}` | `{{METRIC}}` | `{{VALUE_OR_RANGE}}` | `{{VALUE_OR_RANGE}}` | `{{UNIT}}` | `{{SOURCE}}` | `{{DATE}}` | `{{SCOPE}}` | `{{METHOD}}` | `{{EVIDENCE_ID_OR_A_ID}}` | `{{OWNER}}` | `{{RANGE}}` |

按需纳入：硬件、软件/订阅、云与网络、实施、集成、迁移/双轨、测试、培训、内部人力、维保、安全合规、停机/恢复、退役、残值及可核验收益。不得用“行业平均”或经验比例填补未知值。

## 4. 增量现金流

周期由项目决定，不默认三年或五年。

| 现金流项 | `{{PERIOD_0}}` | `{{PERIOD_1}}` | `{{PERIOD_N}}` | 计算公式 | 证据/假设编号 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 基准成本 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `{{FORMULA}}` | `{{IDS}}` |
| 拟议成本 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `{{FORMULA}}` | `{{IDS}}` |
| 增量成本 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `拟议成本 - 基准成本` | `{{MODEL_VERSION}}` |
| 基准可货币化收益 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `{{FORMULA}}` | `{{IDS}}` |
| 拟议可货币化收益 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `{{FORMULA}}` | `{{IDS}}` |
| 增量收益 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `拟议收益 - 基准收益` | `{{MODEL_VERSION}}` |
| 增量净现金流 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `增量收益 - 增量成本` | `{{MODEL_VERSION}}` |
| 折现后净现金流 | `{{VALUE}}` | `{{VALUE}}` | `{{VALUE}}` | `Net_Cash_Flow_t/(1+r)^t` | `{{MODEL_VERSION}}` |

## 5. 风险调整

优先用悲观、基准、乐观情景呈现不确定性。只有当概率和影响有项目证据时，才使用期望损失：

`Expected_Loss = Probability_of_Event × Financial_Impact`

可以将基准与拟议方案的期望损失差额纳入增量现金流，但必须保证事件定义、时间范围和影响口径一致。无可辩护概率时，保留风险区间或情景，不伪造期望值。

| 场景 | 变化的变量 | 取值依据 | NPV | 回收期 | 决策含义 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 悲观 | `{{VARIABLE_IDS}}` | `{{SOURCE_OR_ASSUMPTION}}` | `{{RESULT}}` | `{{RESULT}}` | `{{IMPLICATION}}` |
| 基准 | `{{VARIABLE_IDS}}` | `{{SOURCE_OR_ASSUMPTION}}` | `{{RESULT}}` | `{{RESULT}}` | `{{IMPLICATION}}` |
| 乐观 | `{{VARIABLE_IDS}}` | `{{SOURCE_OR_ASSUMPTION}}` | `{{RESULT}}` | `{{RESULT}}` | `{{IMPLICATION}}` |

## 6. 避免双重计算

对每个收益和成本指定唯一台账编号及现金流落点，并检查：

- 工时节省、人员减少、避免招聘和产能增加不同时全额计入；只计已明确兑现的现金流。
- 业务量增长、收入增长和收款改善不重复计算同一笔业务价值。
- 停机损失避免、SLA 赔偿避免与期望风险损失不重复计入同一事件。
- 订阅费中已包含的维保/云资源、实施费中已包含的项目人力不再单列。
- CAPEX 现金流与会计折旧不在同一现金流模型重复计算；税务影响另行明确。
- 共享平台成本只计拟议方案导致的增量部分；成本转移不自动视为组织收益。
- 临床质量、医护时间和患者结局仅在指标、基线、测量方法、货币化规则、时间范围和责任人均明确时计入；否则作为非财务结果单独呈现。

## 7. 发布前检查

- 基准是可解释的反事实，两个方案的范围、时间、价格和币种口径一致。
- 每个实际数字都有单位、来源定位、资料日期、地区/范围和计算方法。
- 符号、税费、通胀、折现、残值和时点口径一致，公式可重算。
- 事实与假设分开，假设有编号、取值依据、敏感性和失效条件。
- 已执行双计数检查，且财务收益与非财务结果分开。
- 数据不足时只发布变量表、公式、情景和取数计划，不发布确定性 ROI。
