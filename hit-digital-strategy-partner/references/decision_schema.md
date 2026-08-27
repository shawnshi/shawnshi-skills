# 决策记录 Schema

本文件用于需要结构化交接、多人并行或正式管理层决策的任务。简短问答不必机械填满所有字段；但任何缺失且会改变结论的字段必须转成信息缺口，不能静默假设。

## 1. 决策上下文

```yaml
decision_id: DC-001
decision_side: hospital_buyer | health_it_vendor_seller | both_separate
decision_owner: 具名岗位或待确认
audience: null
decision_question: 本轮必须拍板的一句话问题
options_in_scope: []
excluded_scope: []
geographies: []
as_of: YYYY-MM-DD
intended_use: internal_discussion | budget_review | procurement | bid | board_decision
time_horizon: null
budget_status: unknown | indicative | allocated | approved
budget_currency: null
success_metrics: []
unacceptable_risks: []
decision_deadline: null
data_context_summary: null
affected_population: null
authority_and_approvals: []
maturity: working_draft | review_ready | decision_ready | approved_for_execution | blocked
```

`decision_side=both_separate` 时必须分别建立买方和卖方价值模型，不得用一个 ROI 抵消另一方的损失。

## 2. 分流字段

### 医疗机构/买方

至少补充：

- 公共服务、临床质量与患者安全目标；
- 法规/评级/政策等强制义务及截止日；
- 预算来源、采购方式、审批与验收约束；
- 受影响的临床/运营流程、业务量和当前基线；
- 内部项目、临床、数据、安全、运维和变革资源；
- 现有系统、数据、接口、基础设施及前置项目依赖；
- 可现金化收益、非现金收益和全生命周期 TCO；
- 患者、员工和业务连续性的不可接受风险。

### 医疗 IT 企业/卖方

至少补充：

- 目标客户、付费方、购买触发点与竞争替代；
- 产品标准能力、缺口、定制比例和可复用性；
- 合同额、收入确认、回款里程碑、直接交付成本和风险准备；
- 售前、研发、实施、接口、数据迁移、运维和支持产能；
- 验收、SLA、质保、赔偿、知识产权、分包及数据责任；
- 毛利/贡献利润、现金回收、峰值营运资金和机会成本；
- 续费、扩展、参考价值与退出/迁移义务；
- 不可承诺的临床效果、产品能力和交付边界。

## 3. 记录类型与标识

| 类型 | ID 前缀 | 定义 | 可支持结论 |
|---|---|---|---|
| 已核实事实/来源主张 | `EV-` | 可定位到来源的单一陈述 | 是，按强度和适用性 |
| 假设 | `AS-` | 尚未核实但为计算或判断所需 | 只能条件性支持 |
| 分析判断 | `JG-` | 基于证据与假设形成的解释 | 必须回指输入 |
| 信息缺口 | `GP-` | 缺失且可能影响结论的信息 | 可能阻断成熟度 |
| 风险 | `RK-` | 触发事件、影响和应对 | 不能与缺口混写 |
| 建议 | `RC-` | 带条件的管理动作 | 必须回指判断/风险 |
| 决策 | `DC-` | 有权主体作出的选择 | 记录主体、日期和条件 |

证据详细字段和并行合并协议见 [retrieval_specialist.md](retrieval_specialist.md)。ID 一旦被其他记录引用即不可重用或改变含义；修订时新增记录并使用 `supersedes`。

假设至少包含：

```yaml
assumption_id: AS-FIN-001
statement: null
range_or_scenarios: null
basis_evidence_ids: []
owner_to_validate: null
validate_by: null
impact_if_wrong: low | medium | high
status: open | validated | rejected | superseded
```

分析判断至少包含 `judgement_id`、`statement`、`evidence_ids`、`assumption_ids`、`alternative_explanation`、`confidence` 和 `falsifier`。不得把判断改写成“事实”以提高语气确定性。

## 4. 方案与建议契约

每个进入比较的方案至少记录：

```yaml
option_id: OP-001
name: null
scope: null
applies_when: []
gate_results: []
benefits: []
cost_model_ref: null
dependencies: []
resource_demand: []
failure_modes: []
reversibility: null
evidence_ids: []
assumption_ids: []
confidence: low | medium | high
```

建议使用条件句，并把执行条件写成可管理的阶段门：

```yaml
recommendation_id: RC-001
action: null
rationale_judgement_ids: []
preconditions: []
owner: null
approver: null
start_window: null
acceptance_metric_and_threshold: []
data_source_and_observation_period: []
benefit_owner: null
remediation_window: null
pause_or_rollback_trigger: []
termination_trigger: []
next_decision_date: null
```

## 5. 冲突与成熟度

- 证据冲突：保留双方记录，标记 `disputed`，说明口径差异和裁决责任人；不能取“更顺眼”的数字。
- 方案冲突：分开陈述价值、风险和资源约束，不以综合分数代替强制/安全/合规门禁。
- 版本冲突：单一协调者合并分片，记录 `supersedes` 和变更理由，不使用最后写入者覆盖。
- 成果成熟度按 [editor.md](editor.md) 的最低条件判定；缺少适用地区、预期用途、关键基线或高风险专业复核时，最多为 `working_draft`，必要时为 `blocked`。
- `approved_for_execution` 只能来自真实有权主体，并记录批准范围和附带条件。
