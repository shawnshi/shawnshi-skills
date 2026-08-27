---
schema: "discovery-call-output/v2.5"
artifact_type: "internal_retrieval"
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
---

# {{客户中文规范名称}}内部信息检索报告

> 仅记录用户授权范围内的检索；内部命中不能自动升级为事实。检索时间：{{updated_at}}

## 1. 授权、连接与范围

| 项目 | 内容 |
|---|---|
| connector_status | {{connector_status}} |
| tenant_id | {{tenant_id}} |
| customer_id | {{customer_id}} |
| project_id | {{project_id}} |
| authorization_owner | {{姓名（稳定角色/账号）}} |
| authorization_expires_at | {{带时区时间}} |
| 授权范围 | {{系统、文件夹、时间段、权限}} |
| 查询与过滤 | {{查询式、别名、项目号、时间范围}} |
| 未覆盖范围 | {{内容}} |

只使用用户提供或其他已授权材料、且未计划连接器时写`not_applicable`；计划使用连接器但尚未配置时才写`not_configured`。
`connected`只在本run真实工具调用、三重过滤和返回元数据检查均通过后使用；接口文档或计划接入不算实现。

## 2. 命中摘要

| 命中 | 摘要 | claim_id | 权限/适用范围 | 商务影响 |
|---|---|---|---|---|
| {{N-HIT-001}} | {{内容}} | {{CLM-N-001}} | {{internal-authorized/restricted}} | {{内容}} |

如无命中，明确记录 `connector_status=no_hits`、检索范围与查询式，不把未命中解释为不存在。

## 3. 冲突与使用边界

| 项目 | 内部主张 | 外部/其他主张 | claim_id | 处理 |
|---|---|---|---|---|
| {{内容}} | {{内容}} | {{内容}} | {{CLM-N-###}} | {{保留冲突/补证/禁用}} |

## 4. 主张台账

`U/N` 只允许出现在 provenance；主张仍须给出 claim_type 与 verification_status。

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| {{CLM-N-001}} | {{F/F2/A/H/R}} | {{N/U}} | {{asserted/verified_single/corroborated/conflicted/stale/invalidated/unusable}} | {{内容}} | {{日期与适用范围}} | {{SRC-N-001}} | {{SRC-I/L/N-###/无}} | {{高/中/低}} | {{内容}} |

## 5. 来源台账

`F2`要求支持来源中存在至少一对来源：该同一对的`source_group`、`locator/source_locator（URL/稳定定位）`、`source_fingerprint`、`upstream_id`四项都有效且逐项不同；`upstream_id`为`unknown:<source_id>`的来源不能成为该对成员；其他补充支持来源不影响这对成立。不存在这样的同一对时不得标记为`corroborated`。`source_fingerprint`写64位小写SHA-256（可加`sha256:`前缀）或`scheme:stable-id`。

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| {{SRC-N-001}} | {{文档名}} | {{提供者/系统}} | {{稳定文件定位；不得泄露凭证}} | {{日期}} | {{日期}} | internal | {{独立来源组}} | {{internal-authorized/restricted}} | {{范围}} | {{内容}} | {{64位小写SHA-256/sha256:.../scheme:stable-id}} | {{上游来源ID/unknown:SRC-N-001}} | {{true/false；须有明确外发授权}} |

## 6. 检索审计与下一步

- 查询覆盖与停止原因：{{内容}}
- 无命中/权限不足/失败的准确说明：{{内容}}
- 建议补充授权或材料：{{内容}}
- 通用审核：{{pending/approved/changes_requested}}｜reviewer：{{姓名（稳定角色/账号）/待定}}｜reviewed_at：{{时间/空}}
- CRM/PIMS写回：{{not_requested/candidate/pending_approval/written/rejected/failed}}；未实际回读核对不得写written。
