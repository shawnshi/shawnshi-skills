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
minimum_next_step: "{{minimum_next_step}}"
---

# {{客户中文规范名称}}账户经营策略与验证计划

> 内部使用｜经营周期：{{planning_horizon}}｜本轮不是已排定会议准备｜ready_for_use：{{true/false}}

`strategic_question`、`planning_horizon`和`minimum_next_step`必须与 frontmatter 一致。未确认的预算、角色和项目窗口保留为缺口或验证任务，不得补造会议、参会人员或客户承诺。

## 1. 战略问题与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 待决策问题 | {{strategic_question}} | {{CLM-I/L/N-###}} |
| 经营周期 | {{planning_horizon}} | {{CLM-I/L/N-###}} |
| 最小推进动作 | {{minimum_next_step}} | {{CLM-I/L/N-###}} |
| 完成标准 | {{本周期结束时可观察的结果}} | {{CLM-I/L/N-###}} |

## 2. 判断链与证据边界

| 环节 | 当前判断 | claim_id | 反证/替代解释 | 置信度 | 验证方式 |
|---|---|---|---|---|---|
| 客户发展或履职阶段 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{高/中/低}} | {{方式}} |
| 核心任务或矛盾 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{高/中/低}} | {{方式}} |
| 数字化支撑点 | {{内容}} | {{CLM-I/L/N-###}} | {{内容}} | {{高/中/低}} | {{方式}} |

## 3. 利益相关者与决策结构

| 角色层级 | 当前可核实职责 | 事项/阶段 | 影响方式 | 证据 claim_id | 缺口与验证动作 |
|---|---|---|---|---|---|
| {{正式角色/待核实角色}} | {{内容}} | {{发起/预算/技术/采购/实施/验收}} | {{决策/审批/影响/执行}} | {{CLM-I/L/N-###}} | {{内容}} |

不得把会议出席、讲话、领导小组成员或在任期间采购结果直接写成预算权、采购决定权或个人厂商偏好。

## 4. 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/反证 | 下一验证动作 |
|---|---|---|---|---|
| Budget | {{预算来源、状态、口径或未知}} | {{CLM-I/N-###}} | {{内容}} | {{动作}} |
| Authority | {{各阶段正式角色或未知}} | {{CLM-I/L/N-###}} | {{内容}} | {{动作}} |
| Need | {{客户任务、压力和可观察结果}} | {{CLM-I/L/N-###}} | {{内容}} | {{动作}} |
| Timing/采购时序 | {{已发生、计划、推测和未公开节点}} | {{CLM-I/N-###}} | {{内容}} | {{动作}} |
| 竞争位置 | {{存量、切换成本、我司匹配与短板}} | {{CLM-I/N-###}} | {{内容}} | {{动作}} |

- 建议：{{win/conditional_win/monitor/no_go}}
- 投入强度：{{低/中/高}}
- 建议理由：{{依据、缺口和反证}}

## 5. 情景与触发条件

| 情景 | 触发信号 | 可能影响 | 应对动作 | owner | 复核日期 |
|---|---|---|---|---|---|
| 基准情景 | {{信号}} | {{影响}} | {{动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} |
| 上行情景 | {{信号}} | {{影响}} | {{动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} |
| 下行情景 | {{信号}} | {{影响}} | {{动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} |

## 6. 30/60/90天账户动作

| 周期 | action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|
| 30天 | {{唯一主动作}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{内容}} | {{可观察结果}} | {{是/否}} |
| 60天 | {{后续动作或明确观察条件}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{内容}} | {{可观察结果}} | {{是/否}} |
| 90天 | {{后续动作、调整或退出判断}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{内容}} | {{可观察结果}} | {{是/否}} |

第一行必须与`minimum_next_step`一致；没有明确owner、due_date和完成标准的动作不能计为可执行推进。

## 7. 验证计划

| 待验证主张/假设 | 当前状态 | 验证问题或动作 | 目标对象/来源 | owner | due_date | 通过/停止信号 |
|---|---|---|---|---|---|---|
| {{CLM-I/L/N-###或缺口}} | {{conflicted/unknown/stale/H}} | {{内容}} | {{正式角色/原始来源}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | {{信号}} |

## 8. 风险、承诺边界与停止条件

| 风险/停止条件 | 依据 claim_id | 业务后果 | 预防或降级动作 | 升级角色 |
|---|---|---|---|---|
| {{预算取消/窗口关闭/能力不匹配/交付风险不可接受等}} | {{CLM-I/L/N-###}} | {{内容}} | {{内容}} | {{角色}} |

- 停止继续投入的最低条件：{{明确、可观察的停止条件}}
- 禁止承诺：{{价格、效果、工期、评级、资源、高层出席等未经授权事项}}

## 9. CRM/PIMS候选

| 候选类型 | 内容 | 数据属性 | owner | due_date | 写回状态 |
|---|---|---|---|---|---|
| action | {{唯一主动作及完成标准}} | {{事实/假设/建议}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | candidate_only |
| verification | {{待验证事项}} | {{事实缺口/假设}} | {{真人/稳定角色}} | {{YYYY-MM-DD}} | candidate_only |

默认只生成写回候选；未获得目标系统、三重范围和数据所有者批准时不得实际写回。

## 10. 依据导航与缺口

本成果引用研究模块中的 claim_id；不在此重复定义主张或来源。

| 序号 | claim_id | 来源成果 | 使用位置 |
|---|---|---|---|
| 1 | {{CLM-I/L/N-###}} | {{相对链接}} | {{章节}} |

| 缺口 | 影响 | 责任角色与验证期限 |
|---|---|---|
| {{内容}} | {{内容}} | {{角色；YYYY-MM-DD}} |

## 11. 审核与可用状态

- strategy_variant：account_planning
- review_status：{{pending/approved/changes_requested}}
- reviewer：{{姓名（稳定角色/账号）/待定}}
- reviewed_at：{{带时区时间/空}}
- ready_for_use：{{true/false}}
- review_due_at：{{带时区时间}}
- 未通过原因/解除条件：{{内容/无}}
