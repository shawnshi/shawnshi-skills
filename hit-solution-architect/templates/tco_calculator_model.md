# 医疗 IT 方案 TCO / ROI 变量模型

本模板只定义计算结构，不提供默认折旧周期、维保比例、人力成本或临床收益。项目数字必须来自客户材料、合同、公开文件或明确标注的情景假设。

## 1. 计算边界

先记录：

- 分析主体与适用地区
- 基准方案和拟议方案
- 起止日期、币种和折现口径
- 纳入与排除的成本、收益和风险

常用公式：

`TCO_delta = Baseline_TCO - Proposed_TCO`

`Net_Benefit = Verified_Benefits - Incremental_Costs`

`ROI = Net_Benefit / Incremental_Costs`

只有在分母、时间范围和证据充分时才计算 ROI；否则保留变量和取数计划。

## 2. 输入变量合同

| variable_id | 指标 | value_or_range | unit | source | as_of | region | evidence_or_assumption | sensitivity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `[COST_HW]` | 硬件采购 | `[待客户确认]` | `[CURRENCY]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-001]` | `[RANGE]` |
| `[COST_SW]` | 软件许可或订阅 | `[待客户确认]` | `[CURRENCY/PERIOD]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-002]` | `[RANGE]` |
| `[COST_MAINT]` | 维保与支持 | `[待客户确认]` | `[CURRENCY/PERIOD]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-003]` | `[RANGE]` |
| `[COST_LABOR]` | 内外部人力 | `[待客户确认]` | `[CURRENCY/PERIOD]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-004]` | `[RANGE]` |
| `[COST_MIGRATION]` | 迁移、联调和双轨运行 | `[待客户确认]` | `[CURRENCY]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-005]` | `[RANGE]` |
| `[COST_DOWNTIME]` | 停机与恢复成本 | `[待客户确认]` | `[CURRENCY]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-006]` | `[RANGE]` |
| `[BENEFIT_01]` | 经验证的收益变量 | `[待客户确认]` | `[UNIT]` | `[SOURCE]` | `[DATE]` | `[REGION]` | `[EVIDENCE_OR_A-007]` | `[RANGE]` |

可以增删变量，但不能用“行业常识”替代缺失值。示例编号和占位符不是业务事实。

## 3. 按项目周期呈现现金流

周期由项目决定，不固定为三年或五年。

| 成本或收益项 | `[PERIOD_0]` | `[PERIOD_1]` | `[PERIOD_N]` | 计算公式 | 证据或假设编号 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| CAPEX | `[VALUE]` | `[VALUE]` | `[VALUE]` | `[FORMULA]` | `[SOURCE_OR_A-ID]` |
| OPEX | `[VALUE]` | `[VALUE]` | `[VALUE]` | `[FORMULA]` | `[SOURCE_OR_A-ID]` |
| 迁移与退役成本 | `[VALUE]` | `[VALUE]` | `[VALUE]` | `[FORMULA]` | `[SOURCE_OR_A-ID]` |
| 经验证收益 | `[VALUE]` | `[VALUE]` | `[VALUE]` | `[FORMULA]` | `[SOURCE_OR_A-ID]` |
| 净现金流 | `[VALUE]` | `[VALUE]` | `[VALUE]` | `收益 - 成本` | `[MODEL_VERSION]` |

## 4. 情景与敏感性

| 场景 | 变化的变量 | 取值依据 | 结果 | 解释 |
| :--- | :--- | :--- | :--- | :--- |
| 悲观 | `[VARIABLE_IDS]` | `[SOURCE_OR_ASSUMPTION]` | `[RESULT]` | `[IMPACT]` |
| 基准 | `[VARIABLE_IDS]` | `[SOURCE_OR_ASSUMPTION]` | `[RESULT]` | `[IMPACT]` |
| 乐观 | `[VARIABLE_IDS]` | `[SOURCE_OR_ASSUMPTION]` | `[RESULT]` | `[IMPACT]` |

临床质量、医护时间和患者结局不能自动货币化。只有在指标定义、基线、测量方法、时间范围和责任人均明确时，才将其作为收益变量。

## 5. 发布前检查

- 每个实际数字都有单位、来源、资料日期和适用地区。
- 假设与事实分开，假设具有编号和敏感性范围。
- 缺失数据保留为占位符并在最终发布前处理。
- 公式、币种、税费、折现和时间范围一致。
- 不把示例变量、固定比例或经验数字当作项目事实。
