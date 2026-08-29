---
schema: "discovery-call-output/v2.5"
artifact_type: "comprehensive_report"
context_id: "{{context_id}}"
latest_run_id: "{{latest_run_id}}"
customer_id: "{{customer_id}}"
customer_display_name: {{customer_display_name_yaml}}
organization_scope: {{organization_scope_yaml}}
safe_name: "{{safe_name}}"
route: "strategy"
depth: "deep"
business_mode: "strategic_account"
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
review_status: "not_required"
connector_status: "not_applicable"
freshness_status: "{{freshness_status}}"
content_version: "{{content_version}}"
evidence_cutoff_date: "{{evidence_cutoff_date}}"
updated_at: "{{updated_at}}"
runtime_owner: {{runtime_owner_yaml}}
workflow_stage: "{{workflow_stage}}"
---

# {{客户中文规范名称}}No-Go客户研究与行动准备报告

> 用户业务模式：战略客户包｜内部研究档位：深度版｜信息截止：{{evidence_cutoff_date}}
## 1. 决策摘要

| 核心问题 | 当前结论 | claim_id | 对业务决策的意义 |
|---|---|---|---|
| 客户主体 | {{verified/insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I-###}} | {{maintain_no_go/internal_review_required/close_opportunity/no_external_action}} |
| 责任角色 | {{verified/insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-L/I-###}} | {{maintain_no_go/internal_review_required/close_opportunity/no_external_action}} |
| 当前任务 | {{verified/insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/N-###}} | {{maintain_no_go/internal_review_required/close_opportunity/no_external_action}} |
| 最小推进动作 | {{与策略30天action逐字一致}} | {{CLM-I/L/N-###}} | no_external_action |

## 2. 任务上下文与成果状态

| 模块 | selected_in_run | run_action | module_status | review_status | connector_status | freshness_status | content_version | latest_run_id | updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | gaps/blockers | 成果链接 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 机构研究 | {{true/false}} | {{created/reused/updated/not_called}} | {{状态}} | {{状态}} | not_applicable | {{状态}} | {{版本}} | {{run_id}} | {{时间}} | {{状态}} | {{正文实际引用且存在于当前ledger的去重排序claim_id列表；无则none}} | {{none/stale/invalidated}} | {{none/受控gap-blocker码及当前claim_id的去重排序列表}} | {{链接显示文本必须为“机构研究”}} |
| 人物研究 | {{true/false}} | {{created/reused/updated/not_called}} | {{状态}} | {{状态}} | not_applicable | {{状态}} | {{版本}} | {{run_id}} | {{时间}} | {{状态}} | {{正文实际引用且存在于当前ledger的去重排序claim_id列表；无则none}} | {{none/stale/invalidated}} | {{none/受控gap-blocker码及当前claim_id的去重排序列表}} | {{链接显示文本必须为“人物研究”}} |
| 内部检索 | {{true/false}} | {{created/reused/updated/not_called}} | {{状态}} | {{状态}} | {{状态}} | {{状态}} | {{版本}} | {{run_id}} | {{时间}} | {{状态}} | {{正文实际引用且存在于当前ledger的去重排序claim_id列表；无则none}} | {{none/stale/invalidated}} | {{none/受控gap-blocker码及当前claim_id的去重排序列表}} | {{链接显示文本必须为“内部检索”}} |
| 交流策略 | true | {{created/reused/updated}} | completed | {{pending/approved/changes_requested}} | not_applicable | current | {{版本}} | {{run_id}} | {{时间}} | synced | {{正文实际引用且存在于当前ledger的去重排序claim_id列表；无则none}} | none | none | {{链接显示文本必须为“交流策略”}} |
| 会前速览 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |
| 客户信内部审核稿 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |
| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |

## 3. 综合判断链

| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 验证问题或动作 |
|---|---|---|---|---|---|
| 发展阶段 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 核心矛盾 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 决策者关注 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 信息化支撑 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |
| 最小推进动作 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} | {{四项受控动作之一}} |

## 4. G-C-P 推演

| 模块 | 结论 | claim_id | 边界 | 置信度 |
|---|---|---|---|---|
| G：目标任务 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} |
| C：承接能力 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} |
| P：政策与项目风险 | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{insufficient_evidence/conflicted_evidence/disqualified/not_applicable}} | {{高/中/低}} |

## 4.1 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/验证问题 |
|---|---|---|---|
| Budget | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} |
| Authority | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} |
| Need | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} |
| Timing/采购时序 | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} |
| 竞争位置 | {{unverified/insufficient/disqualified/not_applicable}} | {{CLM-I/L/N-###}} | {{unverified/insufficient/disqualified/not_applicable}} |

- 建议：no_go
- 投入强度：低；依据：{{evidence_insufficient/qualification_failed/authorization_missing/resource_limit}}
- 继续投入的前提/停止条件：{{evidence_still_insufficient/qualification_failed/authorization_unavailable/resource_limit_reached}}

## 4.2 执行与下一步

| action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 继续/调整/no-go条件 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|
| {{与策略30天action逐字一致}} | {{stop/archive/observe/recheck}} | none | none | {{与策略30天owner一致}} | {{与策略30天due_date一致}} | {{与策略30天依赖一致}} | {{与策略30天完成标准一致}} | {{与策略30天触发一致}} | {{与策略30天候选标志一致}} |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {{updated_at}} | {{content_version}} | {{latest_run_id}} | {{run_summary}} | {{runtime_owner}} |
