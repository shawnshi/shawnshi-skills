# 信息时效、会后反馈与系统回填 v2.10.0

## 1. TTL规则

TTL是逐claim的可复测属性，不是成果文件的一个统一日期。每条claim在`runtime/evidence-manifest.json`记录`information_type/ttl_class、evidence_anchor_at、date_basis、verified_at、ttl_days、expires_at、supporting_source_ids、verification_status`。TTL从支持该主张的最新有效证据锚点计算；只有访问日期时，从访问日期计算并记`date_basis=retrieved_at`、降低置信度。TTL是复用上限，不替代事件有效期、来源更新或现场确认。

先应用当前业务模式的成果级上限，再应用下表的信息类别上限，取更短者：

| business_mode | institution | leader | procurement | internal |
|---|---:|---:|---:|---:|
| briefing | 90天 | 14天 | 7天 | 30天 |
| standard_visit | 120天 | 14天 | 7天 | 30天 |
| strategic_account | 180天 | 14天 | 7天 | 30天 |
| letter | 90天 | 7天 | 7天 | 14天 |

| 信息类别 | 默认TTL | 使用前附加复核 |
|---|---:|---|
| 机构性质、主管关系、院区/成员边界 | 180天 | 组织调整、合并、更名或新院区出现时立即失效 |
| 机构年度任务、规划重点、运营/评价数据 | 90天 | 新规划、工作要点、年报或考核结果发布时刷新 |
| 人物现职、分工、任职状态 | 30天 | 具名高层拜访前7天内必须再核验一次 |
| 人物长期公开观点 | 180天 | 与本次议题直接相关时补查近12个月新表达 |
| 采购意向、公告、中标、合同和项目阶段 | 14天 | 活跃招采、谈判、验收窗口内按3天复核 |
| 存量系统、供应商和实施/验收状态 | 30天 | 作为策略关键依赖或对外事实前7天内复核 |
| 内部需求、客户反馈、会议共识 | 30天 | 有明确有效期或被后续纪要覆盖时以事件为准 |
| 价格、免费范围、排期、资源和承诺 | 7天 | 每次会议或外发前由责任人重新确认 |
| 我司产品能力、案例授权和效果数据 | 90天或材料有效期孰短 | 外发前确认产品owner、版本和external_use |

法律、政策、采购公告等原文若明确有效期，以明确有效期优先。已知事实发生变化时不等待TTL，立即标`stale`或`invalidated`。

计算时先取当前`business_mode`对该类别的上限，再取信息类别默认TTL，以较短者写入`ttl_days`；明示事件终止或有效期更早时，`expires_at`取更早值。验证器使用工作区`task_timezone`的当前民用时间重算，不信任Markdown或模型手写的到期结论。

## 2. 复用判断

打开既有context时逐项执行：

1. 识别本模式会实际使用的关键claim；
2. 核对claim的支持source ID、内容SHA、事件/有效/核验日期和TTL，并重算`expires_at`；
3. 未到期且无变化信号可reused；
4. 到期但仍可能有效先标stale并定向刷新；
5. 被新证据否定标invalidated，保留历史来源和更正原因；
6. 无法及时复核时从正文结论降为现场问题，`ready_for_use=false`。

`evidence_cutoff_date`只表示本轮证据检查截止日，不代表所有主张都在当天更新。成果文件最近修改时间、source抓取日期和总报告cutoff都不得替代主张TTL。关键claim缺机器TTL记录、已过期或支持来源内容SHA漂移时，立即转`stale`，不得以手工改`freshness_status=current`绕过。

## 3. 各模式处置

- 会前速览：只刷新会进入1页正文的身份、采购、合作、当前任务和最小动作依据。
- 标准拜访包：刷新策略全部关键依赖；不影响议题的稳定历史事实可复用。
- 战略客户包：对人物、采购、内部项目、竞争和产品案例做完整TTL检查，并登记未变化ID。
- 一封信：收件人身份、机构名称、合作事实、承诺和案例授权必须在相应TTL内；任一过期阻断外发。

## 4. 会后复盘

拜访结束后优先记录事实，不先做销售解释：

| 字段 | 要求 |
|---|---|
| visit_date | 实际日期和时区 |
| participants | 已确认姓名/角色；不补写未确认人员 |
| customer_quotes | 仅记录可归因、必要且获授权的原话摘要 |
| confirmed_updates | 被客户或正式材料确认的事实及source/claim |
| invalidated_hypotheses | 被否定或需要降级的既有假设 |
| opportunity_stage | 当前阶段及证据 |
| procurement_timeline | 关键节点、责任部门和不确定性 |
| competitor_change | 只记录可核实的机构格局或销售判断，不推断个人倾向 |
| decisions | 已确认决定与边界 |
| actions | action、owner、due_date、依赖、完成标准 |
| next_contact | 对象、目的、最晚时间 |
| writeback_status | not_requested/candidate/pending_approval/written/rejected/failed |

至少形成一条双方下一步；如果没有，明确写“本次未形成推进动作”并说明原因，不伪造进展。

## 5. 机会与策略更新

把会后信息按三轴模型登记：

- 客户明确陈述：provenance=U、verification_status=asserted；
- 正式纪要、确认邮件、项目文件：按直接性可升级为verified_single；
- 销售解释：A或H，不得写成客户事实；
- 新信息改变BANT、采购时序、竞争位置或win/no-go时，更新相关模块并触发重新审核。

更新后重新计算TTL和`ready_for_use`。任何策略或信件依赖被stale/invalidated时，将其review_status设为changes_requested并清空通用审核绑定或客户信审批绑定。

## 6. CRM/PIMS写回候选

默认只生成候选，不写回。候选按以下分区：

| 分区 | 可写内容 |
|---|---|
| 客户事实 | 当前有效、已核验、范围明确的机构/人物/项目事实 |
| 机会字段 | 阶段、预算状态、决策角色、采购时序、竞争位置、win/no-go和下一步 |
| 行动项 | action、owner、due_date、完成标准 |
| 待确认 | 用户陈述、口头信息、AI分析、未解决冲突 |
| 证据元数据 | source、claim、日期、权限、TTL和适用范围 |

实际写回必须同时满足：

1. 连接器已通过本run的真实读/写能力检查；
2. `tenant_id/customer_id/project_id`三重范围与目标记录完全一致；
3. authorization_owner批准写回范围且授权未过期；
4. data_steward实名可追溯；
5. 用户明确要求本次写回；
6. 写回后读取目标记录核对字段和值，并记录回执或稳定ID。

连接器不存在、只读、无权限、过滤元数据缺失或回读失败时，保持candidate/failed并交付可复制清单；不得声称“已同步”。
