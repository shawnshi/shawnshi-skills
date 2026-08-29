---
schema: "discovery-call-output/v2.5"
artifact_type: "institution_research"
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

# {{客户中文规范名称}}机构研究报告

> 档位：{{快速版/标准版/深度版}}｜信息截止：{{YYYY-MM-DD}}｜内部使用

## 1. 主体确认与边界

| 项目 | 结论 | claim_id | 状态 |
|---|---|---|---|
| 规范名称/别名 | {{内容}} | {{CLM-I-001}} | {{已核实/待核实}} |
| 官网、主管单位与范围 | {{内容}} | {{CLM-I-002}} | {{已核实/待核实}} |
| 排除的同名主体 | {{内容}} | {{CLM-I-003/无}} | {{内容}} |

## 2. 发展阶段与核心矛盾

| 判断 | 结论 | claim_id | 反证/边界 | 置信度 |
|---|---|---|---|---|
| 发展阶段 | {{内容}} | {{CLM-I-###}} | {{内容}} | {{高/中/低}} |
| 核心矛盾 | {{内容}} | {{CLM-I-###}} | {{内容}} | {{高/中/低}} |
| 数字化支撑点 | {{内容}} | {{CLM-I-###}} | {{内容}} | {{高/中/低}} |

## 3. 政策、规划与公开项目

| 时间 | 事项 | 当前状态 | claim_id | 商务意义 |
|---|---|---|---|---|
| {{日期}} | {{内容}} | {{规划/采购/建设/验收/运营}} | {{CLM-I-###}} | {{内容}} |

## 4. 业务、评价与数字化基础

| 维度 | 当前事实/判断 | claim_id | 缺口与时效 |
|---|---|---|---|
| 业务运行与专业能力 | {{按客户类型填写}} | {{CLM-I-###}} | {{内容}} |
| 评价/监管压力 | {{内容}} | {{CLM-I-###}} | {{内容}} |
| 存量系统与数据基础 | {{内容}} | {{CLM-I-###}} | {{内容}} |
| 供应商与合作生态 | {{机构格局；不得推断个人偏好}} | {{CLM-I-###}} | {{内容}} |

## 5. 招采轨迹与采购时序

| 项目/包件 | 编号 | 阶段与日期 | 预算/金额口径 | 供应商/联合体 | claim_id | 下一节点 |
|---|---|---|---|---|---|---|
| {{内容}} | {{编号/未公开}} | {{意向/公告/中标/合同/实施/验收/运维}} | {{内容/未公开}} | {{内容/未公开}} | {{CLM-I-###}} | {{内容}} |

## 6. 组织与决策结构

| 角色/部门 | 职责与影响 | claim_id | 待核实点 |
|---|---|---|---|
| {{内容}} | {{内容}} | {{CLM-I-###}} | {{内容}} |

## 7. 机会、风险与验证问题

| 类型 | 判断 | claim_id | 行动/验证问题 |
|---|---|---|---|
| 机会 | {{内容}} | {{CLM-I-###}} | {{内容}} |
| 风险 | {{内容}} | {{CLM-I-###}} | {{内容}} |

## 8. 覆盖矩阵

| 维度 | 状态 | 关键claim_id/缺口 |
|---|---|---|
| 主体/历史定位 | {{已覆盖/有线索待核实/本次未核验/不适用}} | {{内容}} |
| 组织领导/业务运行/专业能力 | {{状态}} | {{内容}} |
| 战略任务/评价压力/政策约束 | {{状态}} | {{内容}} |
| 数字化/招采轨迹/合作生态 | {{状态}} | {{内容}} |

## 9. 主张台账

`claim_type` 仅限 `F/F2/A/H/R`；`provenance` 仅限 `public/U/N`。F 对应 `verified_single`，F2 对应 `corroborated`。

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| {{CLM-I-001}} | {{F/F2/A/H/R}} | {{public/U/N}} | {{asserted/verified_single/corroborated/conflicted/stale/invalidated/unusable}} | {{可独立判断的主张}} | {{日期与口径}} | {{SRC-I-001}} | {{SRC-I-002/无}} | {{高/中/低}} | {{内容}} |

## 10. 来源台账

台账14列逐列投影验签machine source；定位只写raw HTTP(S) URL或受控stable-id，所有单元格禁止Markdown链接/图片、反引号、HTML和Cf；备注只用`none/capture_limitation/metadata_unavailable/scope_limited`。`source_fingerprint`必须精确写`sha256:<64位小写content_sha256>`。F2只按已验签machine source的`source_group/canonical_locator/content_sha256/upstream_id`判定，必须存在同一对四项同时有效且逐项不同；Markdown值不得建立独立性。

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| {{SRC-I-001}} | {{纯文本标题}} | {{纯文本单位}} | {{raw HTTP(S) URL或受控stable-id}} | {{日期}} | {{日期}} | {{S/A/B/C/internal}} | {{独立来源组}} | {{public/internal-authorized/restricted}} | {{范围}} | {{none/受控审计码}} | {{sha256:64位小写SHA-256}} | {{上游来源ID/unknown:SRC-I-001}} | {{true/false；外发是否已授权}} |

## 11. 覆盖、缺口与停止条件

- 覆盖渠道：{{内容}}
- 未覆盖渠道及原因：{{内容}}
- 冲突与稀缺预警：{{内容}}
- 停止原因：{{收益递减/时间盒/来源耗尽}}
- TTL复核：{{机构/采购等关键主张的到期日与处置}}
