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

# {{客户中文规范名称}}客户研究与拜访准备报告

> 用户业务模式：{{会前速览/标准拜访包/战略客户包/一封信}}｜内部研究档位：{{快速版/标准版/深度版}}｜信息截止：{{YYYY-MM-DD}}
> ready_for_use：{{true/false}}｜closed仅表示本次生成结束，不表示已审核或可外发。

会前速览的用户正文另按1页模板交付；本文件保留必要审计。标准拜访包和战略客户包展开判断链、G-C-P、机会资格和执行计划。第2、8、9节属于审计区，转换为面向高层的Word/PPT时可放附录，但不得从权威Markdown删除。

## 1. 决策摘要

| 核心问题 | 当前结论 | claim_id | 对拜访的意义 |
|---|---|---|---|
| 主体与边界 | {{内容}} | {{CLM-I-001}} | {{内容}} |
| 当前重点任务 | {{内容}} | {{CLM-I-002}} | {{内容}} |
| 决策影响者 | {{内容}} | {{CLM-L-001/待确认}} | {{内容}} |
| 项目与采购窗口 | {{内容}} | {{CLM-I-003/待确认}} | {{内容}} |
| 主要机会与风险 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} |
| 最小推进动作 | {{仅一个主动作}} | {{CLM-I/L/N-###}} | {{内容}} |

## 2. 任务上下文与成果状态

> 以下为机器审计与恢复信息，不属于1页速览正文。

| 模块 | selected_in_run | run_action | module_status | review_status | connector_status | freshness_status | content_version | latest_run_id | updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | gaps/blockers | 成果链接 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 机构研究 | {{institution_selected_in_run}} | {{institution_run_action}} | {{institution_status}} | {{institution_review_status}} | {{institution_connector_status}} | {{institution_freshness_status}} | {{institution_content_version}} | {{institution_latest_run_id}} | {{institution_updated_at}} | {{institution_summary_sync_status}} | {{institution_key_claim_ids}} | {{institution_downstream_invalidation}} | {{institution_gaps_blockers}} | {{institution_link}} |
| 人物研究 | {{leader_selected_in_run}} | {{leader_run_action}} | {{leader_status}} | {{leader_review_status}} | {{leader_connector_status}} | {{leader_freshness_status}} | {{leader_content_version}} | {{leader_latest_run_id}} | {{leader_updated_at}} | {{leader_summary_sync_status}} | {{leader_key_claim_ids}} | {{leader_downstream_invalidation}} | {{leader_gaps_blockers}} | {{leader_link}} |
| 内部检索 | {{internal_selected_in_run}} | {{internal_run_action}} | {{internal_status}} | {{internal_review_status}} | {{internal_connector_status}} | {{internal_freshness_status}} | {{internal_content_version}} | {{internal_latest_run_id}} | {{internal_updated_at}} | {{internal_summary_sync_status}} | {{internal_key_claim_ids}} | {{internal_downstream_invalidation}} | {{internal_gaps_blockers}} | {{internal_link}} |
| 交流策略 | {{strategy_selected_in_run}} | {{strategy_run_action}} | {{strategy_status}} | {{strategy_review_status}} | {{strategy_connector_status}} | {{strategy_freshness_status}} | {{strategy_content_version}} | {{strategy_latest_run_id}} | {{strategy_updated_at}} | {{strategy_summary_sync_status}} | {{strategy_key_claim_ids}} | {{strategy_downstream_invalidation}} | {{strategy_gaps_blockers}} | {{strategy_link}} |
| 会前速览 | {{briefing_selected_in_run}} | {{briefing_run_action}} | {{briefing_status}} | {{briefing_review_status}} | {{briefing_connector_status}} | {{briefing_freshness_status}} | {{briefing_content_version}} | {{briefing_latest_run_id}} | {{briefing_updated_at}} | {{briefing_summary_sync_status}} | {{briefing_key_claim_ids}} | {{briefing_downstream_invalidation}} | {{briefing_gaps_blockers}} | {{briefing_link}} |
| 客户信内部审核稿 | {{letter_selected_in_run}} | {{letter_run_action}} | {{letter_status}} | {{letter_review_status}} | {{letter_connector_status}} | {{letter_freshness_status}} | {{letter_content_version}} | {{letter_latest_run_id}} | {{letter_updated_at}} | {{letter_summary_sync_status}} | {{letter_key_claim_ids}} | {{letter_downstream_invalidation}} | {{letter_gaps_blockers}} | {{letter_link}} |
| 客户信外发版 | {{external_letter_selected_in_run}} | {{external_letter_run_action}} | {{external_letter_status}} | {{external_letter_review_status}} | {{external_letter_connector_status}} | {{external_letter_freshness_status}} | {{external_letter_content_version}} | {{external_letter_latest_run_id}} | {{external_letter_updated_at}} | {{external_letter_summary_sync_status}} | {{external_letter_key_claim_ids}} | {{external_letter_downstream_invalidation}} | {{external_letter_gaps_blockers}} | {{external_letter_link}} |

`selected_in_run=false`表示本轮未调用；已有历史文件可保留其原状态和链接。只有从未生成过的模块才写`module_status=not_called`并留空成果列。“成果链接”是第15列也是唯一链接列：Markdown目标即`artifact_path`，显示文本即`link`，不得另加第16列。

### 2.1 本次RACI与审核SLA

| 角色 | 姓名（稳定角色/账号） | 本次责任 | 截止时间/状态 |
|---|---|---|---|
| account_owner | {{内容}} | 客户目标和下一步负责 | {{内容}} |
| runtime_owner | {{runtime_owner}} | 研究、合并和修订 | {{内容}} |
| evidence_reviewer | {{内容}} | 事实与证据复核 | {{review_due_at}} |
| commercial_reviewer | {{内容/不适用}} | 机会、承诺和投入复核 | {{review_due_at/不适用}} |
| external_approver | {{内容/不适用}} | 外发审批 | {{review_due_at/不适用}} |
| authorization_owner | {{内容/不适用}} | 内部数据授权 | {{authorization_expires_at/不适用}} |

## 3. 综合判断链

| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 现场验证问题 |
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

| 维度 | 当前判断 | claim_id | 缺口/现场问题 |
|---|---|---|---|
| Budget | {{来源、状态、口径；未知则不猜}} | {{CLM-I/N-###}} | {{内容}} |
| Authority | {{业务/技术/预算/采购/验收角色}} | {{CLM-I/L/N-###}} | {{内容}} |
| Need | {{客户任务与可观察结果}} | {{CLM-I/L/N-###}} | {{内容}} |
| Timing/采购时序 | {{规划→预算→采购→实施→验收}} | {{CLM-I/N-###}} | {{内容}} |
| 竞争位置 | {{存量/竞争/我司匹配与短板}} | {{CLM-I/N-###}} | {{内容}} |

- 建议：{{win/conditional_win/monitor/no_go}}
- 投入强度：{{低/中/高}}；依据：{{内容}}
- 继续投入的前提/停止条件：{{内容}}

## 4.2 拜访执行与下一步

| 时间 | 议题/动作 | 我方owner | 材料/演示 | 目标信号 |
|---:|---|---|---|---|
| {{0—5分钟}} | {{开场}} | {{真人/稳定角色}} | {{材料/无}} | {{内容}} |
| {{5—25分钟}} | {{核心议题}} | {{真人/稳定角色}} | {{版本与授权}} | {{内容}} |
| {{最后5分钟}} | {{收口}} | {{真人/稳定角色}} | {{内容}} | {{最小推进动作}} |

| action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |
|---|---|---|---|---|---|
| {{唯一主动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{内容}} | {{内容}} | {{是/否}} |

## 5. 高价值发现

快速版最多5条，标准/深度最多8条。claim 类型只能为 `F/F2/A/H/R`；`public/U/N` 只表示 provenance。

| 序号 | claim_id | claim_type | provenance | 发现 | 业务影响 | 置信度 |
|---|---|---|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{F/F2/A/H/R}} | {{public/U/N}} | {{内容}} | {{内容}} | {{高/中/低}} |

## 6. 异常审核队列

| 审核项 | 类型 | 待审核内容 | claim_id/source_id | 风险 | runtime_owner | 审核结论 |
|---|---|---|---|---|---|---|
| {{REV-001}} | {{冲突/低置信度/内部敏感/承诺/外发事实}} | {{内容}} | {{CLM-... / SRC-...}} | {{影响}} | {{角色}} | {{not_started/pending/approved/changes_requested}} |

### 可用状态

- ready_for_use：{{true/false}}
- 必要审核人：{{姓名（稳定角色/账号）}}
- review_due_at：{{带时区时间}}
- 未通过原因/解除条件：{{内容/无}}

## 7. 关键缺口与现场验证

| 缺口 | 优先级 | 待核实事项 | 影响 | 验证方式 | 责任角色/时点 |
|---|---|---|---|---|---|
| {{GAP-001}} | {{高/中/低}} | {{内容}} | {{影响}} | {{现场/内部/补检}} | {{内容}} |

## 8. 主张与来源导航

本节只导航，不重新定义主张或来源；权威双台账位于独立研究成果。

| 序号 | claim_id | 对应成果 | 用途 |
|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{相对链接}} | {{摘要/判断链/GCP}} |

| 序号 | source_id | 对应成果 | 状态 |
|---|---|---|---|
| 1 | {{SRC-I/L/N-###}} | {{相对链接}} | {{current/stale/invalidated}} |

## 8.1 刷新结果记录

每个完成合并的 refresh run 追加一行；非 refresh run 不新增行。五类结果单元格只允许填写逗号分隔的 claim/source ID 列表，或精确值 `none`，不得写自由文本或占位符。

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {{updated_at}} | {{content_version}} | {{latest_run_id}} | {{run_summary}} | {{runtime_owner}} |
