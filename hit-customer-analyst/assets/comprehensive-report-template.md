---
schema: "discovery-call-output/v2.5"
artifact_type: "comprehensive_report"
context_id: "{{context_id}}"
latest_run_id: "{{latest_run_id}}"
customer_id: "{{customer_id}}"
customer_display_name: {{customer_display_name_yaml}}
organization_scope: {{organization_scope_yaml}}
safe_name: "{{safe_name}}"
route: "{{route}}"
depth: "{{depth}}"
business_mode: ""
ready_for_use: "false"
readiness_reviewer: ""
readiness_reviewed_at: ""
readiness_content_version: ""
readiness_body_sha256: ""
readiness_target_body_sha256: ""
readiness_reviewer_actor_id: ""
readiness_reviewer_role: ""
readiness_reviewer_authority_id: ""
readiness_reviewer_identity_provider: ""
readiness_action_event_id: ""
tenant_id: ""
project_id: ""
authorization_owner: ""
authorization_expires_at: ""
module_status: "{{module_status}}"
review_status: "{{review_status}}"
connector_status: "{{connector_status}}"
freshness_status: "{{freshness_status}}"
content_version: "{{content_version}}"
evidence_cutoff_date: "{{evidence_cutoff_date}}"
updated_at: "{{updated_at}}"
runtime_owner: {{runtime_owner_yaml}}
workflow_stage: "{{workflow_stage}}"
---

# {{客户中文规范名称}}客户研究与行动准备报告

> 用户业务模式：{{会前速览/标准拜访包/战略客户包/一封信}}｜内部研究档位：{{快速版/标准版/深度版}}｜信息截止：{{YYYY-MM-DD}}
## 1. 决策摘要

| 核心问题 | 当前结论 | claim_id | 对业务决策的意义 |
|---|---|---|---|
| 主体与边界 | {{内容}} | {{CLM-I-001}} | {{内容}} |
| 当前重点任务 | {{内容}} | {{CLM-I-002}} | {{内容}} |
| 决策影响者 | {{内容}} | {{CLM-L-001/待确认}} | {{内容}} |
| 项目与采购窗口 | {{内容}} | {{CLM-I-003/待确认}} | {{内容}} |
| 主要机会与风险 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} |
| 最小推进动作 | {{仅一个主动作}} | {{CLM-I/L/N-###}} | {{内容}} |

## 2. 任务上下文与成果状态

| 模块 | selected_in_run | run_action | module_status | review_status | connector_status | freshness_status | content_version | latest_run_id | updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | gaps/blockers | 成果链接 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 机构研究 | {{institution_selected_in_run}} | {{institution_run_action}} | {{institution_status}} | {{institution_review_status}} | {{institution_connector_status}} | {{institution_freshness_status}} | {{institution_content_version}} | {{institution_latest_run_id}} | {{institution_updated_at}} | {{institution_summary_sync_status}} | {{institution_key_claim_ids}} | {{institution_downstream_invalidation}} | {{institution_gaps_blockers}} | {{institution_link}} |
| 人物研究 | {{leader_selected_in_run}} | {{leader_run_action}} | {{leader_status}} | {{leader_review_status}} | {{leader_connector_status}} | {{leader_freshness_status}} | {{leader_content_version}} | {{leader_latest_run_id}} | {{leader_updated_at}} | {{leader_summary_sync_status}} | {{leader_key_claim_ids}} | {{leader_downstream_invalidation}} | {{leader_gaps_blockers}} | {{leader_link}} |
| 内部检索 | {{internal_selected_in_run}} | {{internal_run_action}} | {{internal_status}} | {{internal_review_status}} | {{internal_connector_status}} | {{internal_freshness_status}} | {{internal_content_version}} | {{internal_latest_run_id}} | {{internal_updated_at}} | {{internal_summary_sync_status}} | {{internal_key_claim_ids}} | {{internal_downstream_invalidation}} | {{internal_gaps_blockers}} | {{internal_link}} |
| 交流策略 | {{strategy_selected_in_run}} | {{strategy_run_action}} | {{strategy_status}} | {{strategy_review_status}} | {{strategy_connector_status}} | {{strategy_freshness_status}} | {{strategy_content_version}} | {{strategy_latest_run_id}} | {{strategy_updated_at}} | {{strategy_summary_sync_status}} | {{strategy_key_claim_ids}} | {{strategy_downstream_invalidation}} | {{strategy_gaps_blockers}} | {{strategy_link}} |
| 会前速览 | {{briefing_selected_in_run}} | {{briefing_run_action}} | {{briefing_status}} | {{briefing_review_status}} | {{briefing_connector_status}} | {{briefing_freshness_status}} | {{briefing_content_version}} | {{briefing_latest_run_id}} | {{briefing_updated_at}} | {{briefing_summary_sync_status}} | {{briefing_key_claim_ids}} | {{briefing_downstream_invalidation}} | {{briefing_gaps_blockers}} | {{briefing_link}} |
| 客户信内部审核稿 | {{letter_selected_in_run}} | {{letter_run_action}} | {{letter_status}} | {{letter_review_status}} | {{letter_connector_status}} | {{letter_freshness_status}} | {{letter_content_version}} | {{letter_latest_run_id}} | {{letter_updated_at}} | {{letter_summary_sync_status}} | {{letter_key_claim_ids}} | {{letter_downstream_invalidation}} | {{letter_gaps_blockers}} | {{letter_link}} |
| 客户信外发版 | {{external_letter_selected_in_run}} | {{external_letter_run_action}} | {{external_letter_status}} | {{external_letter_review_status}} | {{external_letter_connector_status}} | {{external_letter_freshness_status}} | {{external_letter_content_version}} | {{external_letter_latest_run_id}} | {{external_letter_updated_at}} | {{external_letter_summary_sync_status}} | {{external_letter_key_claim_ids}} | {{external_letter_downstream_invalidation}} | {{external_letter_gaps_blockers}} | {{external_letter_link}} |

### 2.1 本次RACI与审核SLA

| 角色 | 姓名（稳定角色/账号） | 本次责任 | 截止时间/状态 |
|---|---|---|---|
| account_owner | {{受控我方角色/姓名（受控我方角色）}} | account_decision | {{YYYY-MM-DD/带时区时间/pending}} |
| runtime_owner | {{受控我方角色/姓名（受控我方角色）}} | research_execution | {{YYYY-MM-DD/带时区时间/pending}} |
| evidence_reviewer | {{受控我方角色/姓名（受控我方角色）}} | evidence_review | {{YYYY-MM-DD/带时区时间/pending}} |
| commercial_reviewer | {{受控我方角色/姓名（受控我方角色）/not_applicable}} | commercial_review | {{YYYY-MM-DD/带时区时间/pending/not_applicable}} |
| external_approver | {{受控我方角色/姓名（受控我方角色）/not_applicable}} | external_approval | {{YYYY-MM-DD/带时区时间/pending/not_applicable}} |
| authorization_owner | {{受控我方角色/姓名（受控我方角色）/not_applicable}} | data_authorization | {{YYYY-MM-DD/带时区时间/pending/not_applicable}} |

## 3. 综合判断链

| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 验证问题或动作 |
|---|---|---|---|---|---|
| 发展阶段 | {{内容}} | {{CLM-I-###}} | {{内容}} | {{高/中/低}} | {{问题}} |
| 核心矛盾 | {{内容}} | {{CLM-I/N-###}} | {{内容}} | {{高/中/低}} | {{问题}} |
| 决策者关注 | {{内容}} | {{CLM-L/N-###}} | {{内容}} | {{高/中/低}} | {{问题}} |
| 信息化支撑点 | {{内容}} | {{CLM-I/N-###}} | {{边界}} | {{高/中/低}} | {{问题}} |
| 最小推进动作 | {{内容}} | {{CLM-I/L/N-###}} | {{边界}} | {{高/中/低}} | {{问题}} |

## 4. G-C-P 推演

| 模块 | 结论 | claim_id | 边界 | 置信度 |
|---|---|---|---|---|
| G：目标任务 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{高/中/低}} |
| C：承接能力 | {{授权能力类型}} | {{CLM-N-###/无则待匹配}} | {{不得虚构参数}} | {{高/中/低}} |
| P：政策与项目风险 | {{内容}} | {{CLM-I/N-###}} | {{内容}} | {{高/中/低}} |

## 4.1 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/验证问题 |
|---|---|---|---|
| Budget | {{来源、状态、口径；未知则不猜}} | {{CLM-I/N-###}} | {{内容}} |
| Authority | {{业务/技术/预算/采购/验收角色}} | {{CLM-I/L/N-###}} | {{内容}} |
| Need | {{客户任务与可观察结果}} | {{CLM-I/L/N-###}} | {{内容}} |
| Timing/采购时序 | {{规划→预算→采购→实施→验收}} | {{CLM-I/N-###}} | {{内容}} |
| 竞争位置 | {{存量/竞争/我司匹配与短板}} | {{CLM-I/N-###}} | {{内容}} |

- 建议：{{win/conditional_win/monitor/no_go}}
- 投入强度：{{低/中/高}}；依据：{{内容}}
- 继续投入的前提/停止条件：{{内容}}

## 4.2 执行与下一步

| action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 继续/调整/no-go条件 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|
| {{唯一主动作}} | {{advance/adjust/stop/archive/observe/recheck}} | {{none/customer_contact}} | {{none/proposed/approved}} | {{受控我方角色/姓名（受控我方角色）}} | {{YYYY-MM-DD}} | {{内容}} | {{可观察结果}} | {{信号或停止条件}} | {{是/否}} |

## 5. 高价值发现

| 序号 | claim_id | claim_type | provenance | 发现 | impact_type | 业务影响 | 置信度 |
|---|---|---|---|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{F/F2/A/H/R}} | {{public/U/N}} | {{权威claim正文}} | {{decision/verification/risk/resource}} | {{影响机会决策/需要补充验证/存在误判风险/影响资源投入}} | {{高/中/低}} |

## 6. 异常审核队列

| review_id | review_type | claim_or_source_ref | risk_code | owner | review_status |
|---|---|---|---|---|---|
| {{REV-001}} | {{evidence_conflict/low_confidence/internal_sensitive/commitment_review/external_fact_review}} | {{CLM-.../SRC-...}} | {{decision_risk/compliance_risk/confidentiality_risk/commitment_risk}} | {{受控我方角色/姓名（受控我方角色）}} | {{not_started/pending/approved/changes_requested}} |

## 7. 关键缺口与验证计划

| claim_ref | claim_type_ref | provenance_ref | evidence_state | impact_type | verification_mode | owner | due_date |
|---|---|---|---|---|---|---|---|
| {{CLM-I/L/N-###}} | {{F/F2/A/H/R}} | {{public/U/N}} | {{unknown/conflicted/stale/insufficient}} | {{decision/verification/risk/resource}} | {{internal_review/public_refresh/authorized_customer_contact}} | {{受控我方角色/姓名（受控我方角色）}} | {{YYYY-MM-DD}} |

## 8. 主张与来源导航

| 序号 | claim_id | artifact_type | usage_code |
|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{institution_research/leader_research/internal_retrieval}} | {{decision_summary/judgment_chain/gcp/qualification/action/finding/gap}} |

| 序号 | source_id | artifact_type | source_status |
|---|---|---|---|
| 1 | {{SRC-I/L/N-###}} | {{institution_research/leader_research/internal_retrieval}} | {{current/stale/invalidated}} |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {{updated_at}} | {{content_version}} | {{latest_run_id}} | {{run_summary}} | {{runtime_owner}} |
