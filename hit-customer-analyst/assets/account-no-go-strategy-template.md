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
strategy_variant: "account_planning"
strategic_question: "{{strategic_question}}"
planning_horizon: "{{planning_horizon}}"
minimum_next_step: "{{停止主动投入/归档当前机会/被动观察证据变化/内部复核机会资格}}"
---

# {{客户中文规范名称}}账户经营No-Go策略

## 1. 战略问题与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 待决策问题 | {{strategic_question}} | {{CLM-I/L/N-###}} |
| 经营周期 | {{planning_horizon}} | {{CLM-I/L/N-###}} |
| 最小推进动作 | {{与minimum_next_step逐字一致}} | {{CLM-I/L/N-###}} |
| 完成标准 | no_go_decision_recorded | {{CLM-I/L/N-###}} |

## 2. 判断链与证据边界

| 环节 | 当前判断 | claim_id | 反证/替代解释 | 置信度 | 验证方式 |
|---|---|---|---|---|---|
| 客户发展或履职阶段 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 核心任务或矛盾 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 数字化支撑点 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |

## 3. 利益相关者与决策结构

| 角色层级 | 当前可核实职责 | 事项/阶段 | 影响方式 | 证据 claim_id | 缺口与验证动作 |
|---|---|---|---|---|---|
| {{known_role/unknown_role/decision_role_unverified}} | {{verified/unverified/conflicted}} | {{qualification/monitoring/closure}} | {{verified/unverified/not_applicable}} | {{CLM-I/L/N-###}} | {{四项受控动作之一}} |

## 4. 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/反证 | 下一验证动作 |
|---|---|---|---|---|
| Budget | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} | {{四项受控动作之一}} |
| Authority | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} | {{四项受控动作之一}} |
| Need | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} | {{四项受控动作之一}} |
| Timing/采购时序 | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} | {{四项受控动作之一}} |
| 竞争位置 | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} | {{四项受控动作之一}} |

- 建议：no_go
- 投入强度：低
- 建议理由：{{evidence_insufficient/qualification_failed/authorization_missing/resource_limit}}

## 5. 情景与触发条件

| 情景 | 触发信号 | 可能影响 | 应对动作 | owner | 复核日期 |
|---|---|---|---|---|---|
| 基准情景 | evidence_unchanged | maintain_no_go | 被动观察证据变化 | {{登记我方owner}} | {{YYYY-MM-DD}} |
| 上行情景 | new_verified_evidence | reopen_internal_review | 内部复核机会资格 | {{登记我方owner}} | {{YYYY-MM-DD}} |
| 下行情景 | disqualifying_evidence | close_opportunity | 归档当前机会 | {{登记我方owner}} | {{YYYY-MM-DD}} |

## 6. 30/60/90天账户动作

| 周期 | action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 调整/停止触发 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|---|
| 30天 | {{四项受控动作之一}} | {{stop/archive/observe/recheck}} | none | none | {{登记我方owner}} | {{YYYY-MM-DD}} | {{受控依赖}} | {{与disposition固定映射}} | {{与disposition固定映射}} | {{是/否}} |
| 60天 | {{四项受控动作之一}} | {{stop/archive/observe/recheck}} | none | none | {{登记我方owner}} | {{YYYY-MM-DD}} | {{受控依赖}} | {{与disposition固定映射}} | {{与disposition固定映射}} | {{是/否}} |
| 90天 | {{四项受控动作之一}} | {{stop/archive/observe/recheck}} | none | none | {{登记我方owner}} | {{YYYY-MM-DD}} | {{受控依赖}} | {{与disposition固定映射}} | {{与disposition固定映射}} | {{是/否}} |

## 7. 验证计划

| 待验证主张/假设 | 当前状态 | 验证问题或动作 | 目标对象/来源 | owner | due_date | 通过/停止信号 |
|---|---|---|---|---|---|---|
| {{CLM-I/L/N-###}} | {{conflicted/unknown/stale/H}} | {{四项受控动作之一}} | {{internal_evidence/public_evidence/none}} | {{登记我方owner}} | {{YYYY-MM-DD}} | {{keep_no_go/reopen_internal_review/archive}} |

## 8. 风险、承诺边界与停止条件

| 风险/停止条件 | 依据 claim_id | 业务后果 | 预防或降级动作 | 升级角色 |
|---|---|---|---|---|
| {{evidence_insufficient/authorization_missing/resource_limit/qualification_failed}} | {{CLM-I/L/N-###}} | {{maintain_no_go/close_opportunity/internal_review_required}} | {{四项受控动作之一}} | {{登记我方owner}} |

- 停止继续投入的最低条件：{{evidence_still_insufficient/qualification_failed/authorization_unavailable/resource_limit_reached}}
- 禁止承诺：all_unapproved_commitments

## 9. CRM/PIMS候选

| 候选类型 | 内容 | 数据属性 | owner | due_date | 写回状态 |
|---|---|---|---|---|---|
| action | {{四项受控动作之一}} | 建议 | {{登记我方owner}} | {{YYYY-MM-DD}} | candidate_only |
| verification | {{四项受控动作之一}} | 事实缺口 | {{登记我方owner}} | {{YYYY-MM-DD}} | candidate_only |
