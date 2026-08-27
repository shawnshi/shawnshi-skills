---
schema: "discovery-call-output/v2.5"
artifact_type: "visit_strategy"
context_id: "{{context_id}}"
latest_run_id: "{{latest_run_id}}"
customer_id: "{{customer_id}}"
customer_display_name: {{customer_display_name_yaml}}
organization_scope: {{organization_scope_yaml}}
safe_name: "{{safe_name}}"
module_status: "{{module_status}}"
review_status: "{{review_status}}"
connector_status: "{{connector_status}}"
freshness_status: "{{freshness_status}}"
content_version: "{{content_version}}"
evidence_cutoff_date: "{{evidence_cutoff_date}}"
updated_at: "{{updated_at}}"
runtime_owner: {{runtime_owner_yaml}}
reviewer: ""
reviewed_at: ""
reviewed_content_version: ""
reviewed_body_sha256: ""
reviewer_actor_id: ""
reviewer_role: ""
reviewer_authority_id: ""
reviewer_identity_provider: ""
review_action_event_id: ""
strategy_variant: "scheduled_visit"
target_contact_level: "{{target_contact_level}}"
visit_objective: "{{visit_objective}}"
minimum_next_step: "{{minimum_next_step}}"
---

# {{客户中文规范名称}}交流策略与议题设计

> 内部使用｜拜访对象/层级：{{target_contact_level}}｜拜访时间：{{时间/待确认}}｜ready_for_use：{{true/false}}

`strategy_variant`固定为`scheduled_visit`；`target_contact_level`、`visit_objective`和`minimum_next_step`必须与 frontmatter 一致，不得只在自由文本中隐含。

## 1. 目标与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 主要目标 | {{visit_objective}} | {{CLM-I/L/N-###}} |
| 最小推进动作 | {{minimum_next_step}} | {{CLM-I/L/N-###}} |
| 成功标准 | {{会议结束时可观察的结果}} | {{CLM-I/L/N-###}} |

## 2. 对象假设与验证

| 假设 | claim_id | 风险 | 验证问题 |
|---|---|---|---|
| {{内容}} | {{CLM-L/I/N-###}} | {{内容}} | {{开放式问题}} |

## 3. 议题与节奏

| 顺序 | 议题 | 进入依据 claim_id | 建议表达 | 观察信号 |
|---|---|---|---|---|
| 1 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{内容}} |

## 4. 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 待验证问题 |
|---|---|---|---|
| Budget | {{预算来源/状态/口径/未知}} | {{CLM-I/N-###}} | {{问题}} |
| Authority | {{业务/技术/预算/采购/验收角色}} | {{CLM-I/L/N-###}} | {{问题}} |
| Need | {{任务、压力与可观察结果}} | {{CLM-I/L/N-###}} | {{问题}} |
| Timing/采购时序 | {{关键节点}} | {{CLM-I/N-###}} | {{问题}} |
| 竞争位置 | {{存量、竞争、我司匹配与短板}} | {{CLM-I/N-###}} | {{问题}} |

- 建议：{{win/conditional_win/monitor/no_go}}
- 投入强度：{{低/中/高}}
- 前提与停止条件：{{内容}}

## 5. 时间化议程与参会分工

| 时间 | 环节/议题 | 客户对象 | 我方owner | 目标信号 |
|---:|---|---|---|---|
| {{0—5分钟}} | {{开场}} | {{角色}} | {{姓名/稳定角色}} | {{内容}} |
| {{5—25分钟}} | {{核心议题}} | {{角色}} | {{姓名/稳定角色}} | {{内容}} |
| {{最后5分钟}} | {{收口}} | {{角色}} | {{姓名/稳定角色}} | {{最小推进动作}} |

| 参会人/角色 | RACI | 负责内容 | 备用安排 |
|---|---|---|---|
| {{姓名/稳定角色/待确认}} | {{R/A/C/I}} | {{内容}} | {{内容}} |

## 6. 材料与演示计划

| 材料/演示 | 用途与展示时点 | owner | 版本/授权 | 备用/不展示边界 |
|---|---|---|---|---|
| {{内容}} | {{内容}} | {{姓名/角色}} | {{版本、external_use}} | {{内容}} |

## 7. 问题清单

1. {{用于验证关键假设的问题}}
2. {{用于确认角色与流程的问题}}
3. {{用于形成最小下一步的问题}}

## 8. 红线、异议与承诺边界

| 场景 | 风险依据 claim_id | 建议回应 | 禁止承诺 | 升级角色 |
|---|---|---|---|---|
| {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{内容}} | {{角色}} |

## 9. 会后行动

| action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |
|---|---|---|---|---|---|
| {{唯一主动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{内容}} | {{内容}} | {{是/否}} |
| {{最多一个备选}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{触发条件}} | {{内容}} | {{是/否}} |

## 10. 依据导航与缺口

本成果引用研究模块中的 claim_id；不在此重复定义主张或来源。

| 序号 | claim_id | 来源成果 | 使用位置 |
|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{相对链接}} | {{章节}} |

| 缺口 | 影响 | 现场验证/责任角色 |
|---|---|---|
| {{内容}} | {{内容}} | {{内容}} |

## 11. 审核与可用状态

- review_status：{{pending/approved/changes_requested}}
- reviewer：{{姓名（稳定角色/账号）/待定}}
- reviewed_at：{{带时区时间/空}}
- ready_for_use：{{true/false}}
- review_due_at：{{带时区时间}}
- 未通过原因/解除条件：{{内容/无}}
