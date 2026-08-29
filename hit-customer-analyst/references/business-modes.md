# 四种业务模式与兼容映射 v2.10.0

## 1. 使用原则

只向用户呈现“会前速览、标准拜访包、战略客户包、一封信”。`route`、`depth`、模块枚举和`refresh`是内部执行参数，不要求用户选择或理解。

`protected_workflow`与`public_draft`同样是内部执行档，不向用户增加第五种模式。认证能力完整时按正式工作区链执行；认证能力不足时，前三种模式只有在公开资料、内部草稿、无冲突且无敏感材料条件下，才能按[公开资料草稿执行档](public-draft-runtime.md)在对话中交付。`public_draft`不生成正式文件、审核状态或可外发成果；一封信不允许该降级。

若用户已明确成果，直接选模式；只有两种模式会实质改变交付时才问一个问题。用户同时要求研究和拜访准备时，选择覆盖最终用途的较完整模式，不拆成多个上下文。用户只要求客户研究时也不新增“纯研究”模式：快速摸排/1页选会前速览，常规研究选标准拜访包，账户全景或投入决策选战略客户包。只有会前速览和标准拜访包可在未给具体会期时，以后续交流的角色层级、验证目标和最小动作组织成果；战略客户包无已确认会议时必须走`account_planning`，改用战略问题、经营周期和账户动作，不得把会议字段当作占位符。

稳定值：

| 用户名称 | `business_mode` |
|---|---|
| 会前速览 | `briefing` |
| 标准拜访包 | `standard_visit` |
| 战略客户包 | `strategic_account` |
| 一封信 | `letter` |

## 2. 模式定义

受控预算：

| 模式 | 公开查询上限 | 内部查询上限 | 有效直接来源参考 | 总用户成果页数 |
|---|---:|---:|---:|---:|
| 会前速览 | 12 | 8 | 3—5 | 1 |
| 标准拜访包 | 30 | 20 | 8—12 | 8—15；前三页为核心摘要 |
| 战略客户包 | 60 | 40 | 15—25 | 20—35 |
| 一封信 | 12 | 8 | 3—5 | 1—3 |

来源数量只作覆盖预警，不能替代质量门禁；达到关键问题饱和应提前停止。

### 会前速览

适用于临近会议、首次快速摸排或基于既有成果的事实复核。

- 固定内部映射：`visit_prep + quick`。即使只是快速摸排，也用“后续可能交流的对象层级、目标和最小动作”组织1页成果。
- 默认模块：institution、strategy（产出visit_strategy成果）；点名人物时加leader；存在可执行授权且内部信息会改变议题时加internal。对象只明确到角色层级时，策略仍可围绕该层级、目标和最小动作生成，不得补造姓名。
- 用户交付：按`markdown-one-page/v1`代理预算生成独立`artifact_type: briefing_delivery`成果；不得只在对话中输出临时排版。该预算按NFKC规范化并折叠空白后的Markdown源码计数（包含标题、表格和列表标记）：总字符≤3200、非空源码行≤80、每个固定章节≤900字符、一句话结论≤80字符；不承诺特定Word/PDF渲染器恰好一张纸。
- 审计交付：总报告状态/版本、briefing动作分区及实际研究模块底稿，默认不在用户正文中展开。
- 内容上限：1—5条已核实事实、3个现场问题、1个最小推进动作；每条事实明确标F/F2并引用合法claim，一句话结论、机会判断/建议和主动作也必须列出依据claim。`recommendation、investment_intensity、primary_action、owner、due_date`五元组必须与策略、综合报告及候选manifest逐字段一致。
- 交付文件必须有稳定文件头、版本/正文哈希和可信actor审核谱系；宿主签名事件绑定的`--approve-artifact briefing ... --actor-id ... --action-event-id ...`通过前只能标为待审阅草稿。
- 若剩余时间不足以完成关键身份或采购阶段核验，交付“事实简报＋阻塞项”，`ready_for_use=false`，不得用常识补齐。

### 标准拜访包

适用于一次明确的重要拜访，需要从研究到会议执行的完整准备。

- 默认内部映射：`visit_prep + standard`。
- 默认模块：institution、strategy；具名对象已由intake唯一锁定时按需加leader，存在可执行授权且内部信息相关时加internal。只有角色/层级而无姓名时不选择leader，角色级决策结构由institution和strategy承载，不输出具名画像。
- 用户交付：以`visit_strategy`作为正式业务交付，呈现3页以内决策摘要、交流策略与行动；`comprehensive_report`只作审计与状态载体，研究底稿作为依据附件。
- 必含：目标、最小成功动作、关键事实、判断链、机会资格、30/60分钟议程、我方分工、材料计划、现场问题、红线和会后行动。
- 关键人物未确认时可按对象层级继续，但不得输出具名画像。

### 战略客户包

适用于重点客户经营、重大项目、复杂决策结构、高层战略交流或是否继续投入的决策。

- 固定内部映射：`strategy + deep`。策略成果必须结构化记录`strategy_variant`，只允许`scheduled_visit`或`account_planning`。
- 会议意图与具体时间分开记录：`meeting_status`只允许`confirmed|tentative|none|unknown`；`meeting_time`另存唯一带时区时间段或显式未知。`confirmed`使用`scheduled_visit`，即使具体时间待定也不降成账户规划；未提供状态的兼容输入只有在存在唯一确切会议时间时才派生`scheduled_visit`。该分支要求对象/层级、目标、最小推进动作，并输出议题、时间化议程、参会分工、材料和会后行动。
- `tentative`保守使用`account_planning`，确认后重新预检再转`scheduled_visit`；`none/unknown`且无其他可信会议事实时也使用`account_planning`。`none/unknown`与确切时间并存必须阻断澄清，不能自行选有利口径。对象和目标本身不构成会议事实。
- 暂无已确认会议，或用户只要求进入、加码、维持、调整、退出等账户决策时使用`account_planning`；默认经营周期为90天，用户给出其他周期时沿用。该分支只要求战略问题、经营周期和最小推进动作，输出利益相关者与决策结构、情景、30/60/90天账户动作、验证计划和停止条件。不得为成稿追问会期、会议对象、参会人员、议程或材料，也不得生成这些内容的占位符。
- `account_planning`与`scheduled_visit`只能在新一轮已绑定用户请求的intake明确会议事实后转换。转换时重建目标分支策略载体、删除旧分支字段并清空原审核/就绪绑定；旧的`search-plan`四件套作废，必须依当前intake重新规划后才能继续研究。
- 默认模块：institution、strategy；具名对象已由intake唯一锁定时按需加leader，存在可执行授权且有价值时加internal。只有角色/层级而无姓名时，角色级利益相关者与决策结构由institution和account_planning策略承载，不创建leader成果或补造姓名。
- 用户交付：以`visit_strategy`作为正式业务交付，呈现完整客户全景、决策结构、机会资格、采购时序、竞争位置、情景、win/no-go和投入建议；`comprehensive_report`只作审计与状态载体。
- 必须允许`monitor`或`no_go`，不得为形成机会而强行匹配产品。
- `account_planning`初始化只创建普通脚手架；候选与发布阶段由`template_by_recommendation`确定性选择模板对。`win/conditional_win/monitor`映射`default`，`no_go`映射专用闭合模板，其他值一律关闭失败。
- 同一客户不同项目、院区或预算主体必须通过`organization_scope/project_id`分开。

### 一封信

适用于高层邀约、方案交流、项目跟进，或包含关键合作事实、产品效果、排期、资源、案例等需要研究和审批的正式信件。

- 固定内部映射：`letter + standard`；受控查询预算按一封信模式单独收紧，不通过修改depth规避门禁。
- 新上下文至少调用一个必要研究模块作为claim/source载体；续建优先复用当前有效成果。
- 用户交付：先生成内部待审核稿。只有实名审批绑定完整且用户再次明确要求“生成外发版”时，才生成纯净外发文件；永不自动发送。
- 普通感谢、通知、材料转发和无关键事实的通用写作不触发本技能。
- 命中虚构审批、患者信息、未授权邮件/CRM、未经核验的排期/效果/价格、直接外发或非真人责任人时，不进入普通补问或制稿：固定返回“拒绝项、逐项原因、可做部分、所需补充材料、实名审批路径”五段，普通问题数为0且不产生业务副作用。患者/CRM授权仅能支持`internal_review_draft`并固定`external_allowed=false`，不能推进外发、审批、ready或release。

以下任一项成立时视为高风险信件：

1. 院级/局级领导或公司高管署名；
2. 提及金额、免费范围、排期、上线、效果、评级、资源或高层出席；
3. 使用非公开合作事实、项目状态或客户反馈；
4. 使用客户名称、案例、数据或成果作为外部背书；
5. 要求对方作出会议、项目、采购、试点或资源决定；
6. 收件对象、机构、合作事实或授权存在冲突。

## 3. 兼容映射

| `business_mode` | 默认route | 默认depth | 可兼容变化 |
|---|---|---|---|
| briefing | visit_prep | quick | 固定映射 |
| standard_visit | visit_prep | standard | 固定映射；已有研究可复用 |
| strategic_account | strategy | deep | 固定映射；无会议时输出账户动作 |
| letter | letter | standard | 固定映射；使用一封信专属预算 |

`refresh`只表示后台增量动作：

- 保留原`business_mode`，不得向用户显示为第五种模式；
- 仅刷新institution、leader、internal证据时，兼容route可写refresh；
- 同一轮还生成/更新策略或信件时，route分别写strategy/letter；
- 旧成果没有`business_mode`时，根据最新有效route/depth和成果推断；无法唯一推断时只问用户要哪种最终成果。

## 4. 用户交付与审计分离

四种模式都必须声明唯一`delivery_contract`，不得临时把综合报告当作用户正文：

| 模式 | formal_artifact | 用户首先看到 | audit_artifact |
|---|---|---|---|
| 会前速览 | `briefing_delivery` | 1页简报 | `comprehensive_report` |
| 标准拜访包 | `visit_strategy` | 决策摘要、策略、行动表 | `comprehensive_report` |
| 战略客户包 | `visit_strategy` | 完整客户与机会研判 | `comprehensive_report` |
| 一封信 | `customer_letter_external` | 先审阅内部稿；满足专用门禁后生成的纯净外发版才是正式交付 | `comprehensive_report` |

正式成果在ready/release时必须`completed/current/approved`并登记为本轮selected；会前速览还必须`delivery_state=ready`。`comprehensive_report`是唯一审计与状态载体，保留15列成果登记、审核SLA、异常队列、claim/source导航、刷新与版本记录，不作为标准拜访包或战略客户包的首要交付链接。

`visit_strategy`正文不得出现“任务上下文与成果状态、本次RACI与审核SLA、异常审核队列、主张与来源导航、刷新结果记录、版本与同步记录”等审计标题。策略业务表内的claim_id及受控依据导航用于决策可回查，不等同于复制审计状态。Markdown文件可继续作为权威底稿；如用户需要Word、PPT或邮件正文，在业务审核完成后转换，不改变claim/source和审批谱系。

## 5. 模式升级与降级

- 会前速览发现多主体、重大采购冲突或复杂决策结构时，提示可升级为标准拜访包；不阻塞当前可交付部分。
- 标准拜访包发现重大项目需要多年度、竞争和投入判断时，建议升级为战略客户包。
- 战略客户包时间不足时保持原`business_mode=strategic_account`，只交付透明标记的部分成果或待审核稿，`ready_for_use=false`；不得静默跨模式生成会前速览。确需转为会前速览时，必须取得用户明确确认，并由宿主针对新的`business_mode=briefing`重签intake后另起或受控转换。
- 一封信尚未锁定唯一收件对象或明确称谓时，预检必须阻塞且只问一个对象确认问题，`questions`恰为1，不检索、不初始化、不生成任何业务文件。只有收件对象已锁定，而所需事实或实名审批尚未完成时，才可生成透明标记的待补充/待审核内部稿，`ready_for_use=false`。
