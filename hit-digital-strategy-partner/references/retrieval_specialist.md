# 战略研究检索规则

## 检索目标

为当前决策收集最小充分证据。检索次数、来源数量、数字数量和“非共识观点”数量都不是质量目标。

## 来源优先级

1. 法律法规、监管机构和政府部门原文；
2. 医疗机构、采购平台、公司公告和正式技术文件；
3. 同行评议论文、注册研究和可验证数据集；
4. 研究机构原文；
5. 媒体和二手资料，用于定位原始来源或补充背景。

政策、市场、价格、厂商状态和临床证据具有时效性，使用前核验当前版本、发布日期、事件日期、适用地区和访问日期。

## 统一证据记录

每条记录只承载一个可判断的事实或来源主张，使用不可变 ID：`EV-<领域>-<三位序号>`，例如 `EV-POL-001`、`EV-FIN-003`、`EV-CLN-012`。领域建议使用 `POL`（政策）、`FIN`（财务）、`CLN`（临床）、`OPS`（运营）、`TEC`（技术）、`VEN`（厂商）、`MKT`（市场）和 `SEC`（安全）；同一项目内不得复用 ID。

```yaml
evidence_id: EV-OPS-001
record_type: verified_fact | source_claim
claim: 单一、可核验的陈述
source_title: null
publisher: null
source_type: primary | secondary | user_material
published_at: null
event_or_data_period: null
accessed_at: null
region_and_population: null
locator: 原始链接、文件名+页码/表格/字段
method_and_denominator: null
limitations: null
independence_group: null
strength: high | medium | low
status: active | disputed | superseded
supersedes: null
```

- 用户提供的数据也要记录文件/工作表/字段和数据周期，不能只写“内部资料”。
- `independence_group` 标识共同原始来源；两个材料只是相互转述时仍算一个证据链。
- 同一来源支持不同主张时使用不同证据 ID；修订记录使用新 ID 并以 `supersedes` 连接，不修改旧记录以掩盖历史。
- 付费墙摘要、搜索摘要和厂商营销材料不能单独支撑高影响结论。
- 假设、分析判断、信息缺口和建议分别使用 `AS-`、`JG-`、`GP-`、`RC-` 前缀，不伪装成证据。

## 并行检索与合并

三个以上独立研究面并行时，由协调者先分配领域前缀或不重叠的 ID 段，并定义信息截止日和停止条件。

1. 每个研究者只写自己的分片文件或返回结构化记录，不覆盖共享证据表。
2. 协调者按 `locator + claim + event_or_data_period` 去重，并检查同源转述、地区、口径和日期。
3. 对相互冲突的记录全部保留，标为 `disputed`，附上冲突原因和待裁决人；禁止最后写入者覆盖。
4. 合并后冻结证据 ID。结论、模型变量、风险和建议只引用冻结 ID；新增证据使用新 ID。
5. 汇总时报告各研究面已覆盖范围、仍缺口和截止条件，不用来源数量冒充证据充分性。

## 停止条件

以下任一条件成立即可停止扩展检索：

- 决策所需的关键事实已被可靠来源覆盖；
- 新来源只重复已有信息；
- 关键缺口属于未公开数据，继续检索的预期收益很低；
- 用户给定的时间或范围预算已达到。

若来源不足，报告缺口及已查渠道。不要用旧数据、无来源数字或强行反向观点填补。
