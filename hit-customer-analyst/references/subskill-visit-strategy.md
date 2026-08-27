# Skill 3：交流策略与账户经营准备 v2.7.0

## 执行门禁与成果契约

在会前速览、标准拜访包、战略客户包需要交流或账户经营准备时调用。本模式所需研究成果须可用，未调用模块原因透明。会前速览和标准拜访包固定使用`strategy_variant: scheduled_visit`；战略客户包根据是否已有明确拜访选择`scheduled_visit`或`account_planning`，没有会议信息时默认后者。两种分支都必须明确最小推进动作；只有scheduled_visit要求拜访对象/层级和拜访目标，account_planning改为要求战略问题和经营周期。

新建context至少一个institution/leader/internal模块承载claim/source台账；续建至少一个范围匹配且completed/current、逐claim TTL未过期的历史研究成果登记为selected/reused。partial/blocked载体只登记缺口，不能支撑关键策略；completed策略至少引用一个可核验F/F2事实锚点，其证据清单、支持source内容SHA和机器重算TTL必须匹配。

进入执行后，在本run隔离候选工作区按`strategy_variant`选择模板：

- `scheduled_visit`：[交流策略模板](../assets/visit-strategy-report-template.md)；
- `account_planning`：[账户经营策略模板](../assets/account-strategy-report-template.md)。

两者创建同一兼容文件名：

```text
{{客户安全名称}}交流策略与议题设计.md
```

本 Skill 版本为2.7.0；为兼容历史成果，输出YAML frontmatter的`schema`继续固定为`discovery-call-output/v2.5`。执行与审核状态分离：

- 开始执行：`module_status: running`、`review_status: not_started`；
- 内容完成：`module_status: completed`、`review_status: pending`；
- 关键输入冲突：`module_status: blocked`、`review_status: not_started`，文件写明阻塞、已尝试动作和补充问题；
- 人工审核通过：保持`module_status: completed`，将`review_status`改为`approved`；
- 用户未选择：保持`not_called`，不生成文件。

`connector_status`通常为`not_applicable`。frontmatter必须结构化持久化`strategy_variant`和以下条件字段，且与正文一致：

| strategy_variant | 必填业务字段 |
|---|---|
| scheduled_visit | `target_contact_level、visit_objective、minimum_next_step` |
| account_planning | `strategic_question、planning_horizon、minimum_next_step` |

条件字段须非空、非占位。account_planning不得把未知会议对象、时间、参会人或材料补成事实。审核通过时还须绑定`reviewer/reviewed_at/reviewed_content_version/reviewed_body_sha256`；非approved时四字段清空。模块只更新独立候选文件，并向主流程返回分支、目标、机会资格、推进/验证动作、风险、状态和相对路径；不得复制完整研究底稿，不得直接改正式Markdown。

## 输入

读取同一`context_id`下的机构、人物、内部检索成果，以及用户确认、判断链、G-C-P、冲突和异常审核项。正文引用已登记的`claim_id`；主张台账再关联`source_id`。新增判断不得创建孤立ID。

## 执行步骤

1. 核对所有输入文件的`context_id`、`customer_id`和`safe_name`一致。
2. 复核主体、人物、项目阶段、存量系统、采购归因和承诺边界；关键冲突影响目标时标`blocked`。
3. 固化判断链：`发展阶段→核心矛盾→决策者关注→信息化支撑点→最小推进动作`。
4. 完成G-C-P和BANT，补充采购时序、竞争位置、win/no-go、投入强度、停止条件；未知项转为验证问题或验证任务。
5. `scheduled_visit`提炼不超过3个议题，按实际会长设计包含开场、核心议题、验证、收口的时间化议程；列出已知参会角色和我方RACI，形成材料/演示、展示时点、owner、版本/授权、备用方案和“不展示”项。未确认人员标待确认，不擅自补齐。
6. `account_planning`形成正式角色层级的利益相关者与决策结构、基准/上行/下行情景、30/60/90天账户动作和验证计划；每个有效动作写owner、due_date、依赖和完成标准，并明确调整或停止投入的触发条件。不得生成会议话术、时间化议程、参会分工或展示材料。
7. 两个分支都只保留1个主推进动作；scheduled_visit最多增加1个备选动作和不超过5个现场问题，account_planning把其余不确定项放入验证计划。
8. 检查价格、案例授权、效果、上线时间、评级、高层出席和资源等承诺。
9. 完成后设`completed/pending/current`，清空通用审核四字段并向主流程返回同步载荷；不得自行编辑综合报告。

若关键依赖后续变为`stale`或`invalidated`，保留既有`module_status`，同时把本成果的`freshness_status`设为对应值、`review_status`设为`changes_requested`并通知主流程同步成果登记。`pending`或`approved`策略只允许`freshness_status: current`。

## 表达边界

- 用客户发展和履职任务语言，不用产品功能清单开场；
- 不批评客户、存量厂商或人员；
- 不输出绕过采购、审批、监管和审计的建议；
- 不复制内部敏感信息到准备外发的材料；
- 证据不足的陈述改写为现场问题；
- 关系、价格底线和竞争判断只作为内部风险。

## 完成检查

标记`completed/pending`前确认：

- 文件存在、非空且YAML frontmatter字段完整；
- `strategy_variant`为`scheduled_visit`或`account_planning`，对应条件字段已结构化填写且不是模板占位符；
- 至少一个范围匹配且 current 的研究成果提供实际 claim/source 台账；新建上下文不得只生成策略文件；
- 判断链、G-C-P、分支目标和最小推进动作一致；
- BANT、采购时序、竞争位置、win/no-go和投入建议有证据或明确缺口；
- scheduled_visit的时间化议程、参会分工、材料计划、开场/收口和会后action/owner/due_date完整；
- account_planning的利益相关者与决策结构、情景、30/60/90天账户动作、验证计划、停止条件和CRM/PIMS候选完整，且没有虚构会议字段；
- 所有正文`claim_id`可在同一工作目录的主张台账中找到，且其`source_id`可在来源台账中找到；
- 返回载荷只含摘要、状态、异常项、关键主张ID和相对路径；
- 不存在未处理模板占位符；
- 运行`python3 scripts/validate_outputs.py <候选工作目录> --profile candidate`通过，或将未通过项列入阻塞说明。
- approved时通用审核四字段完整且与当前正文和版本匹配；否则`ready_for_use`不能因closed而变为true。

人工审核对象包括目标准确性、人物/角色适配、历史事实、机会资格、投入与停止条件、推进/验证动作和承诺边界；scheduled_visit另审核议题、议程与分工、材料授权，account_planning另审核情景和30/60/90天计划。审核前不得标`approved`；SLA超时不得自动批准。
