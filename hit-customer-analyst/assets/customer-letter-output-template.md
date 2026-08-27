---
schema: "discovery-call-output/v2.5"
artifact_type: "customer_letter_internal"
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
letter_scenario: "{{letter_scenario}}"
recipient_role: "{{recipient_role}}"
letter_purpose: "{{letter_purpose}}"
expected_action: "{{expected_action}}"
signer: "{{signer}}"
delivery_channel: "{{delivery_channel}}"
external_output_required: "{{external_output_required}}"
fact_reviewer: ""
fact_reviewed_at: ""
fact_reviewed_content_version: ""
fact_reviewed_body_sha256: ""
fact_reviewed_context_sha256: ""
fact_reviewer_actor_id: ""
fact_reviewer_role: ""
fact_reviewer_authority_id: ""
fact_reviewer_identity_provider: ""
fact_reviewed_run_id: ""
fact_review_action_event_id: ""
approver: {{approver_yaml}}
approved_at: "{{approved_at}}"
approved_content_version: "{{approved_content_version}}"
approved_body_sha256: "{{approved_body_sha256}}"
approved_context_sha256: "{{approved_context_sha256}}"
approval_run_id: ""
approval_action_event_id: ""
approver_actor_id: ""
approver_role: ""
approval_authority_id: ""
approver_identity_provider: ""
external_request_event_id: ""
external_requested_by_actor_id: ""
external_requested_at: ""
revision_action_event_id: ""
revision_run_id: ""
revision_actor_id: ""
revision_at: ""
revision_target_content_version: ""
revision_target_body_sha256: ""
revision_target_context_sha256: ""
---

# {{客户中文规范名称}}客户信（内部待审核稿）

> 业务模式：一封信｜closed不等于approved｜内部稿默认ready_for_use=false｜本文件永不自动发送

## 1. 内部审核摘要（严禁外发）

| 项目 | 内容 |
|---|---|
| 信件场景 | {{letter_scenario}} |
| 收件对象/角色/身份确认状态 | {{recipient_role}} |
| 发信目的 | {{letter_purpose}} |
| 期望动作 | {{expected_action}} |
| 签署人 | {{signer}} |
| 发送渠道 | {{delivery_channel}} |
| 事实依据 claim_id | {{CLM-I/L/N-###}} |
| 个性化依据 claim_id | {{CLM-L/I-###}} |
| 承诺与授权边界 | {{内容}} |
| 敏感内部信息 | {{有/无；说明}} |
| 高风险触发项 | {{高层署名/承诺/内部事实/案例授权/决策请求/冲突}} |
| 关键事实TTL | {{收件人、项目、承诺和案例授权的复核日期}} |
| 审核角色与结论 | {{角色；not_started/pending/approved/changes_requested}} |
| 审核SLA | {{review_due_at；超时不得自动批准}} |

## 2. 外发前门禁（严禁外发）

- [ ] 收件人身份、称谓与机构已确认
- [ ] 每项外部事实可追溯到有效 claim_id
- [ ] 无竞对判断、价格底线、关系评价、内部权限或受限材料
- [ ] 无超出授权的产品能力、项目结果、排期或资源承诺
- [ ] `review_status=approved` 后才可抽取外发版
- [ ] approver可追溯到真人及稳定角色/账号，不是“领导/销售/审核人”等占位
- [ ] 审批戳中的`approver`、`approved_at`、`approved_content_version`、`approved_body_sha256`与`approved_context_sha256`已绑定当前正文和六项结构化信件上下文；任一变化后必须重新审批

外发版只能从与完整审批戳绑定且哈希一致的批准正文生成；缺失、过期或不匹配的审批戳均不得外发。外发正文及外发版禁止包含HTML注释。

## 3. 已批准外发正文边界

`EXTERNAL_BODY_START`

{{称谓}}：

{{纯净外发正文。不得包含本文件其他章节、claim_id、source_id、内部标签或审核说明。}}

{{落款}}

`EXTERNAL_BODY_END`

## 4. 版本与审核记录（严禁外发）

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner | review_status |
|---|---|---|---|---|---|
| {{updated_at}} | {{content_version}} | {{latest_run_id}} | {{内容}} | {{runtime_owner}} | {{review_status}} |

每次正文更新、`approve`和`emit_external`都追加一行，不覆盖历史记录。`approve`与`emit_external`行须分别写明动作；最新一行的时间、版本、run、负责人和审核状态必须与 frontmatter 一致。
