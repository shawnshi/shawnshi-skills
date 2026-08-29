# Skill 3：交流策略与账户经营准备 v2.10.0

## 执行门禁与成果契约

在会前速览、标准拜访包、战略客户包需要交流或账户经营准备时调用。本模式所需研究成果须可用，未调用模块原因透明。会前速览和标准拜访包固定使用`strategy_variant: scheduled_visit`；战略客户包根据是否已有明确拜访选择`scheduled_visit`或`account_planning`，没有会议信息时默认后者。两种分支都必须明确最小推进动作；只有scheduled_visit要求拜访对象/层级和拜访目标，account_planning改为要求战略问题和经营周期。

新建context至少一个institution/leader/internal模块承载claim/source台账；续建至少一个范围匹配且completed/current、逐claim TTL未过期的历史研究成果登记为selected/reused。partial/blocked载体只登记缺口，不能支撑关键策略；completed策略至少引用一个可核验F/F2事实锚点，其证据清单、支持source内容SHA和机器重算TTL必须匹配。

进入执行后，在本run隔离候选工作区按`strategy_variant`选择模板：

- `scheduled_visit`：[交流策略模板](../assets/visit-strategy-report-template.md)；
- `account_planning`：[账户经营策略模板](../assets/account-strategy-report-template.md)。

三个策略模块模板（含`no_go`变体）不得声明或持久化`ready_for_use`。该字段只属于包级`comprehensive_report`，且只能由主流程完成综合门禁后执行mark-ready写入；策略模块的`module_status/review_status/freshness_status`不能替代包级可用状态。

两者创建同一兼容文件名：

```text
{{客户安全名称}}交流策略与议题设计.md
```

续跑若沿用原分支，必须保留原`strategy_variant`并恢复对应模板和必填字段；若用户新增信息导致分支切换，初始化器必须用目标模板重建策略文件，清除旧分支专属字段和审核签名，并把综合报告的包级`ready_for_use`失效为`"false"`，同时删除旧run的`search-plan.json/source-cache.json/evidence-manifest.json/run-metrics.json`后重新规划。不得把旧分支正文或机器证据静默带入新分支。

本 Skill 版本为2.10.0；为兼容历史成果，输出YAML frontmatter的`schema`继续固定为`discovery-call-output/v2.5`。执行与审核状态分离：

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
5. `scheduled_visit`提炼不超过3个议题，按实际会长设计包含开场、核心议题、验证、收口的时间化议程；列出已知参会角色和我方RACI，形成材料/演示、展示时点、owner、版本/授权、备用方案和“不展示”项。目标、机会资格、议程、RACI、材料、会后行动和CRM/PIMS各使用模板规定的固定表及精确表数；不得在合法表后追加另一张改名会议表。未确认人员标待确认，不擅自补齐。
6. `account_planning`形成正式角色层级的利益相关者与决策结构、基准/上行/下行情景、30/60/90天账户动作和验证计划；动作表固定为`周期、action、action_disposition、external_interaction、resource_commitment、owner、due_date、依赖、完成标准、调整/停止触发、CRM/PIMS候选`十一列，每行十一项均不得为空或使用占位符，动作章节只能有一张表。其余核心章节也各有且仅有一张模板固定表。投入结论同时固定写明`建议、投入强度、建议理由、停止继续投入的最低条件`；建议为`no_go`时，只允许`stop→停止主动投入`、`archive→归档当前机会`、`observe→被动观察证据变化`、`recheck→内部复核机会资格`四组逐字匹配的受控动作，且`external_interaction`和`resource_commitment`均须为`none`；依赖只允许`none/无/无依赖/内部复核/内部证据更新/公开证据变化`，情景、验证计划与CRM中的action/verification也只能引用受控动作。策略与综合报告只允许模板定义的章节、表格和列表；不得用新增H2/H3、改名表、代码块、隐藏链接或治理字段重引影子动作和会议计划。
7. 两个分支都只保留1个主推进动作；scheduled_visit最多增加1个备选动作和不超过5个现场问题，account_planning把其余不确定项放入验证计划。
8. 检查价格、案例授权、效果、上线时间、评级、高层出席和资源等承诺。
9. 完成后设`completed/pending/current`，清空通用审核四字段并向主流程返回同步载荷；不得自行编辑综合报告。

### 依据导航与缺口闭合契约

`scheduled_visit`和非`no_go`的`account_planning`如输出“依据导航与缺口”，必须使用固定双表：

- 导航表固定为`序号｜claim_id｜来源成果｜使用位置`。来源成果整格必须恰有一个本地Markdown链接，不能附加文字、图片或第二个链接。`CLM-I-*`固定显示`机构研究成果`并精确链接当前工作区实际机构研究文件；`CLM-L-*`固定显示`人物研究成果`并精确链接实际人物研究文件；`CLM-N-*`固定显示`内部检索成果`并精确链接实际内部检索文件。禁止`http(s)`、`mailto`、绝对路径、跨目录路径、别名显示文本和不存在的目标。
- scheduled使用位置只允许`target/assumption/agenda/qualification/roles/materials/questions/risk/action/crm`；account使用位置只允许`strategic_question/judgment_chain/stakeholder/qualification/scenario/action/verification/risk/crm`。
- 缺口表固定为`claim_ref｜claim_type_ref｜provenance_ref｜evidence_state｜impact_type｜verification_mode｜owner｜due_date`。主张类型、provenance必须与权威claim台账一致；其余值只用模板枚举，owner使用登记我方角色，due_date为日期。缺口表任何单元格均禁止Markdown链接或图片，不得写对客动作、产品提交、试用、报价、工期或其他自由承诺。

### `no_go`闭合代码契约

`no_go`不是普通自由文本策略的低投入版本。初始化阶段尚无建议结论，始终只创建普通`account_planning`脚手架；候选与发布阶段从策略和综合报告解析出一致的结构化建议后，再由可信配置中的`template_by_recommendation`确定模板对。`win/conditional_win/monitor`只允许选择`default`，`no_go`只允许选择[No-Go账户策略模板](../assets/account-no-go-strategy-template.md)和[No-Go综合报告模板](../assets/account-no-go-comprehensive-template.md)；未知建议、缺键、多键或缺失模板一律关闭失败，不猜测回退。

同一结构化决策对象同时渲染正式策略和综合审计载体。除用户已在签名intake提供并与frontmatter绑定的战略问题、周期外，`no_go`正式策略正文只能出现专用模板九个固定章节、固定表、枚举、精确claim/source引用、登记我方owner和日期，不得保留说明段、导航缺口、自由备注或任何审计标题。审核状态只保留在frontmatter及宿主签名治理记录中。综合报告是审计与状态载体，保留任务状态表、刷新和版本记录；除专用模板八个核心章节外，只可按下表闭集增加“高价值发现”和“关键缺口与验证计划”，不得增加异常审核队列、主张与来源导航或其他影子章节。

| 位置 | 允许值或固定映射 |
|---|---|
| 建议/投入 | `no_go`；投入强度`低` |
| 建议理由 | `evidence_insufficient / qualification_failed / authorization_missing / resource_limit` |
| 最低停止条件 | `evidence_still_insufficient / qualification_failed / authorization_unavailable / resource_limit_reached` |
| 禁止承诺 | `all_unapproved_commitments` |
| 动作 | `stop→停止主动投入`；`archive→归档当前机会`；`observe→被动观察证据变化`；`recheck→内部复核机会资格` |
| 完成/触发 | `stop→no_go_recorded/reopen_internal_review`；`archive→opportunity_archived/reopen_internal_review`；`observe→evidence_watch_recorded/archive_if_unchanged`；`recheck→qualification_review_recorded/keep_no_go_if_unresolved` |
| 依赖 | `none / 无 / 无依赖 / 内部复核 / 内部证据更新 / 公开证据变化` |
| 判断/反证 | `insufficient_evidence / conflicted_evidence / disqualified / not_applicable`；综合摘要另允许`verified` |
| 资格 | `unverified / insufficient / disqualified / not_applicable` |
| 三情景 | 基准=`evidence_unchanged/maintain_no_go/被动观察证据变化`；上行=`new_verified_evidence/reopen_internal_review/内部复核机会资格`；下行=`disqualifying_evidence/close_opportunity/归档当前机会` |
| 验证 | 来源`internal_evidence / public_evidence / none`；信号`keep_no_go / reopen_internal_review / archive`；动作只用上述四项 |
| 风险 | 风险`evidence_insufficient / authorization_missing / resource_limit / qualification_failed`；后果`maintain_no_go / close_opportunity / internal_review_required`；降级动作只用上述四项 |
| CRM | 仅`action/verification`；内容只用上述动作；数据属性分别固定为`建议/事实缺口`；写回状态`candidate_only` |
| owner | 仅登记的我方角色，或`姓名（登记我方角色）`；客户角色、裸姓名和动作句均禁止 |
| 综合摘要影响 | `maintain_no_go / internal_review_required / close_opportunity / no_external_action` |
| 高价值发现/关键缺口 | 高价值发现只允许`F/F2`；缺口验证只允许`internal_review/public_refresh`，不得用`authorized_customer_contact` |

策略首个30天动作与综合报告唯一动作必须十个字段逐项一致。claim/source单元格必须逐字匹配ID并能在权威台账回查；不得在ID后追加文本。`no_go`综合报告不得生成“主张与来源导航”自由扩展，证据由各固定表中的claim引用回查。

当前登记我方角色闭集为：`账户负责人、客户负责人、客户责任岗、战略账户责任岗、方案顾问、售前顾问、方案负责人、方案责任岗、技术负责人、技术经理、技术架构师、产品经理、客户成功、证据负责人、运行负责人、测试负责人、商务审核岗、拜访策略审核岗、人物事实审核岗、客户信事实复核岗、会前简报事实审核岗、交付就绪审核岗`。实名只能写成`姓名（上述登记角色）`；裸姓名、客户方主任/院长等角色以及任何动作句均不接受。扩展角色必须先同步更新机器契约、模板和正反例，不能在成稿中临时新增。

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
- account_planning的利益相关者与决策结构、情景、验证计划完整且各核心章节恰有一张固定表；30/60/90天动作严格满足十一列契约和单表约束；建议、投入强度、建议理由、停止条件齐全且互不矛盾；no_go动作逐字匹配受控文案、两个承诺标志均为`none`，依赖、情景、验证及CRM也未引入面客或资源投入；策略文件及综合报告均没有会议议程、参会分工、材料/演示计划等分支污染；
- 所有正文`claim_id`可在同一工作目录的主张台账中找到，且其`source_id`可在来源台账中找到；
- 返回载荷只含摘要、状态、异常项、关键主张ID和相对路径；
- 不存在未处理模板占位符；
- 运行`python3 scripts/validate_outputs.py <候选工作目录> --profile candidate`通过，或将未通过项列入阻塞说明。
- approved时通用审核四字段完整且与当前正文和版本匹配；否则综合报告的包级`ready_for_use`不能因closed而变为true。

人工审核对象包括目标准确性、人物/角色适配、历史事实、机会资格、投入与停止条件、推进/验证动作和承诺边界；scheduled_visit另审核议题、议程与分工、材料授权，account_planning另审核情景和30/60/90天计划。审核前不得标`approved`；SLA超时不得自动批准。
