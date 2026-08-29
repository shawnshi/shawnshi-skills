---
schema: "discovery-call-output/v2.5"
artifact_type: "briefing_delivery"
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
delivery_state: "draft_for_review"
page_proxy: "markdown-one-page/v1"
---

# {{客户中文规范名称}}会前速览

{{生成提示：成稿按NFKC规范化并折叠空白后的Markdown源码计数（含标题、表格和列表标记），须满足3200总字符、80非空源码行、单节900字符及一句话判断80字符上限；这是保守的一页代理，不等同于真实分页。完成前删除本行。}}

本页核心内容必须直接可见；禁止Markdown链接/图片、HTML、代码块和不可见Unicode格式字符。

> 一页交付物｜结论、事实与建议分开｜最多5条事实、3个问题、1个主动作

以下7个二级章节均为正式交付契约，不得删除、改名或把多个章节压成一段关键词。机会表必须保留5个固定判断行，交流节奏表必须保留4个固定时段；缺项时应保留“证据缺口/待核实”并说明验证方式，不能静默删行。

## 一句话判断

{{客户当前任务或矛盾；本次交流切口；最小推进动作；不超过80字；至少引用1个CLM-I/L/N-###}}

## 会前必须知道

| 事实 | 事实类型与claim_id | 对本次拜访的意义 |
|---|---|---|
| {{最多5条已核实事实}} | {{只填F或F2；至少1个CLM-I/L/N-###}} | {{一句话}} |

## 机会与边界

| 项目 | 当前判断 | 依据claim_id |
|---|---|---|
| Need | {{已核实/假设/待问}} | {{至少1个CLM-I/L/N-###}} |
| Authority | {{已核实角色与缺口}} | {{至少1个CLM-I/L/N-###}} |
| Budget/Procurement | {{有证据/未知；不得猜测}} | {{至少1个CLM-I/L/N-###}} |
| Competition | {{存量格局/待核实}} | {{至少1个CLM-I/L/N-###}} |
| 建议 | {{严格填写：建议=win/conditional_win/monitor/no_go；投入强度=低/中/高；边界=具体依据或停止条件}} | {{至少1个CLM-I/L/N-###}} |

## 建议交流节奏

| 时间 | 议题/动作 | 目标信号 |
|---:|---|---|
| 0—5分钟 | {{开场并确认客户目标}} | {{目标被确认或修正}} |
| 5—20分钟 | {{围绕核心任务交流}} | {{形成有效反馈}} |
| 20—25分钟 | {{验证关键假设与异议}} | {{确认或否定信号}} |
| 25—30分钟 | {{收口并确认下一步}} | {{明确动作、owner与日期}} |

## 三个现场问题

1. {{验证核心任务}}
2. {{确认角色、预算或采购时序}}
3. {{形成最小下一步}}

## 最小推进动作

- 动作：{{唯一主动作}}
- 依据claim_id：{{至少1个CLM-I/L/N-###}}
- Owner：{{真人/稳定角色}}
- Due date：{{YYYY-MM-DD}}
- 红线：{{不得承诺或不得触碰事项}}

## 未决风险

{{最多3项；写明阻断影响与解除条件}}
