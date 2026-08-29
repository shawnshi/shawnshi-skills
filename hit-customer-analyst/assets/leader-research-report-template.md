---
schema: "discovery-call-output/v2.5"
artifact_type: "leader_research"
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

# {{客户中文规范名称}}关键人物研究报告

> 仅处理职业相关公开信息与获授权材料；禁止私人背景调查。信息截止：{{YYYY-MM-DD}}
> 人物现职/分工默认TTL 30天；具名高层拜访前7天内复核。closed不等于approved。

## 1. 对象确认与同名消歧

| 项目 | 结论 | claim_id | 状态 |
|---|---|---|---|
| 姓名、现职与机构 | {{内容}} | {{CLM-L-001}} | {{已核实/待核实}} |
| 同名排除依据 | {{内容}} | {{CLM-L-002/无}} | {{内容}} |

## 2. 职业履历与职责边界

| 时间 | 公开事实 | claim_id | 与本任务的相关性 |
|---|---|---|---|
| {{日期}} | {{内容}} | {{CLM-L-###}} | {{内容}} |

## 3. 公开表达与关注议题

| 议题 | 可核验表达摘要 | claim_id | 口径边界 |
|---|---|---|---|
| {{内容}} | {{内容}} | {{CLM-L-###}} | {{不得推断私人偏好}} |

## 4. 决策影响与沟通假设

| 判断 | claim_id | 反证/不确定性 | 现场验证问题 |
|---|---|---|---|
| {{内容}} | {{CLM-L-###}} | {{内容}} | {{问题}} |

## 5. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| {{CLM-L-001}} | {{F/F2/A/H/R}} | {{public/U/N}} | {{asserted/verified_single/corroborated/conflicted/stale/invalidated/unusable}} | {{内容}} | {{日期与口径}} | {{SRC-L-001}} | {{SRC-L-002/无}} | {{高/中/低}} | {{内容}} |

## 6. 来源台账

台账14列逐列投影验签machine source；定位只写raw HTTP(S) URL或受控stable-id，所有单元格禁止Markdown链接/图片、反引号、HTML和Cf；备注只用受控审计码。`source_fingerprint`必须精确写`sha256:<64位小写content_sha256>`。F2只按已验签machine source的`source_group/canonical_locator/content_sha256/upstream_id`判定，必须存在同一对四项同时有效且逐项不同；Markdown值不得建立独立性。

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| {{SRC-L-001}} | {{纯文本标题}} | {{纯文本单位}} | {{raw HTTP(S) URL或受控stable-id}} | {{日期}} | {{日期}} | {{S/A/B/C/internal}} | {{独立来源组}} | {{public/internal-authorized/restricted}} | {{范围}} | {{none/受控审计码}} | {{sha256:64位小写SHA-256}} | {{上游来源ID/unknown:SRC-L-001}} | {{true/false；外发是否已授权}} |

## 7. 缺口、风险与停止条件

- 身份冲突：{{内容}}
- 低置信度判断：{{内容}}
- 隐私/伦理边界：{{内容}}
- 停止原因：{{内容}}
- 审核：{{pending/approved/changes_requested}}｜reviewer：{{姓名（稳定角色/账号）/待定}}｜reviewed_at：{{时间/空}}
