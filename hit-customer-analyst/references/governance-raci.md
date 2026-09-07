# RACI、审核与可用状态 v2.6.0

## 1. 核心原则

候选版治理命令仅供有权限的真人在受控终端执行；模型不得代执行批准、mark-ready、生成外发版或开始已批准稿修订。标签、哈希和CLI退出0都不证明真人身份。宿主接入账号权限和当前稿件审核事件后仍须独立验收，未完成前只作人工控制的内部试用。

`closed`只表示一次运行已经安全落盘并结束；它不表示成果已审核、可用于会议或可外发。`ready_for_use`单独记录业务可用性，只允许字符串值`"true"`或`"false"`。

任何审核通过必须同时可追溯到真人和稳定角色/账号。允许显示“张三（华北客户负责人）”或“当班合规审批人：张三/employee_id”；不允许只写“销售”“领导”“审核人”等无法归因的泛化角色。

审批调用入口和既有 approved/ready 成果读取门共用 actor 标识校验：拒绝待确认、待指定、匿名、模板占位符及上述泛化角色。字符串通过只表示标识可记录，不证明真人身份、岗位归属、独立性或外发权限；这些仍由授权的人类及实际身份系统核验，模型不得据此自行批准。

实际宿主需按[真人审批接入契约](approval-host-contract.md)验证账号、稿件和事件，并在权限层隔离模型的治理命令调用；本包未实现该认证能力。

## 2. RACI

| 角色 | 责任 | 最低身份要求 | RACI |
| --- | --- | --- | --- |
| requester | 提出业务目标、用途和截止时间 | 姓名或当前登录账号 | C |
| account_owner | 对客户关系、拜访目标和下一步负责 | 真人＋稳定区域/客户角色 | A |
| runtime_owner | 组织研究、合并、修订和交付 | 真人或可解析当前执行账号 | R |
| evidence_reviewer | 复核主体、人物、采购、合作事实和证据边界 | 与runtime_owner不同的真人；紧急速览可由account_owner兼任并显式记录 | A/R |
| commercial_reviewer | 复核机会资格、竞争位置、产品/案例授权、承诺和投入建议 | 真人＋售前/产品/交付稳定角色 | A |
| external_approver | 批准客户信或明确对外材料 | 有外发权限的真人＋稳定角色/账号 | A |
| authorization_owner | 授权内部数据访问范围和有效期 | 数据所有者或其明确委托人 | A |
| data_steward | 执行CRM/PIMS写回、纠错和失效处理 | 系统实名账号 | R |

同一人可兼任account_owner与commercial_reviewer，但外发审批不得由模型、匿名角色或无法追溯的占位符完成。涉及restricted信息时，authorization_owner不得由runtime_owner自行代填。

## 3. 新增治理字段

综合总报告新运行写：

```yaml
business_mode: "briefing|standard_visit|strategic_account|letter"
ready_for_use: "true|false"
readiness_reviewer: ""
readiness_reviewed_at: ""
readiness_content_version: ""
readiness_body_sha256: ""
tenant_id: ""
project_id: ""
authorization_owner: ""
authorization_expires_at: ""
```

旧v2.5成果允许没有这些字段；实际更新时补写。无内部检索时授权字段可留空。选择internal时，`tenant_id/customer_id/project_id/authorization_owner/authorization_expires_at`必须全部有效。

leader、internal、visit_strategy新增通用审核绑定：

```yaml
reviewer: "姓名（稳定角色/账号）"
reviewed_at: "带时区时间"
reviewed_content_version: "当前成果版本"
reviewed_body_sha256: "64位小写SHA-256"
```

- `review_status=approved`时四字段必须非空、版本必须等于当前版本、哈希必须匹配除YAML frontmatter外的规范化正文。
- `review_status`不是approved时四字段全部清空；不得保留旧审批造成误用。
- 正文或影响结论的结构化上下文改变后，立即设`changes_requested`并清空四字段。
- customer_letter继续使用既有`approver/approved_at/approved_content_version/approved_body_sha256/approved_context_sha256`，不以通用字段替换。

正文哈希规范化沿用客户信规则：CRLF/CR转LF、去除每行尾随空白和首尾空行，UTF-8无BOM、无末尾换行后计算SHA-256。

## 4. 审核对象

| 成果 | 必审内容 | 默认审核人 |
| --- | --- | --- |
| 会前速览 | 具名身份、关键采购/合作事实、一个推进动作 | evidence_reviewer；无具名/采购/内部事实的低风险速览可由account_owner快速确认 |
| 标准拜访包 | 事实、议题、机会资格、分工、承诺边界 | evidence_reviewer＋commercial_reviewer |
| 战略客户包 | 全部关键事实、竞争与投入建议、win/no-go | evidence_reviewer＋commercial_reviewer＋account_owner |
| 一封信内部稿 | 收件人、外发事实、承诺、签署与渠道 | evidence_reviewer＋external_approver |

机构研究默认`not_required`只适用于内部底稿。其关键结论一旦进入标准拜访包、战略客户包或一封信，必须在上层成果审核中被覆盖。

## 5. 审核SLA

SLA从“成果提交为pending且审核材料完整”开始，不从任务创建开始：

| 模式 | 正常SLA | 紧急SLA | 超时处置 |
| --- | --- | --- | --- |
| 会前速览 | 30分钟 | 15分钟 | 标注待复核项；涉及身份/采购/承诺时ready=false |
| 标准拜访包 | 4个工作小时 | 60分钟 | 只交付内部草稿或缩减为已复核速览 |
| 战略客户包 | 1个工作日 | 不低于4个工作小时 | 延后正式使用；可先交已复核摘要 |
| 一封信 | 2个工作小时 | 30分钟仅限无承诺短函 | 不生成外发版，不自动升级审批 |

SLA超时、会议临近或管理层催办都不能替代审核。每次超时记录`review_due_at`、当前阻塞、责任人和解除条件。

## 6. ready_for_use门禁

所有模式共同条件：

1. 主体和organization_scope已锁定；
2. 本模式必需成果存在、非空且结构校验通过；
3. 关键依赖为current，TTL未过期；
4. 必要审核已approved且审核绑定匹配当前版本；
5. account_owner、runtime_owner和下一步owner可归因；综合报告须在既有RACI表中登记唯一account_owner（表头前两列为`角色`、`姓名（稳定角色/账号）`），并有恰一行主动作表（前三列`action | owner | due_date`）。具备策略成果的非信件模式，策略也须保留同样的唯一主动作表；owner不能为占位符，due_date须为有效日历日期。no_go可登记停止投入或到期复核，不强迫制造客户会议。历史草稿仍可普通读取，但重新mark-ready须补齐这些既有业务必填项；
6. 受限信息未进入更低权限成果；
7. 关键冲突已解除或明确降级为现场问题。

模式附加条件：

- briefing：1页上所有具名身份、采购、合作事实已经复核；若只包含公开机构事实，可由account_owner确认后ready=true。
- standard_visit：visit_strategy approved；议程、分工、材料、主动作owner和due_date完整。
- strategic_account：综合机会判断经account_owner和commercial_reviewer确认；win/no-go与投入建议一致。
- letter：内部使用时内部稿可保持pending且ready=false；只有内部稿approved、审批五字段匹配且外发事实安全时，外发版ready=true。

任何条件失效时立即把`ready_for_use`改为`"false"`并清空四个readiness字段。只有执行独立就绪审批后才可设为true；readiness_reviewer须可追溯到真人/稳定角色，版本与正文哈希须匹配当前总报告。总报告和交付消息必须同时展示ready状态及原因。

## 7. 试运行与推广门禁

状态保持“试运行”，直到以下条件均有真实项目记录支撑：

1. 四种业务模式各完成至少一次端到端演练，覆盖新建、复用/TTL、人工审核、mark-ready和会后回填候选；
2. account_owner、主/备reviewer、authorization_owner和故障响应人均已实名排班，审核SLA在实际工作时段可兑现；
3. `closed`冒充ready、匿名审批、越权内部检索、未经确认写回或自动发送事件为零；
4. 会前速览稳定满足1页，其他模式的用户正文与审计附件可分发且关键主张可回溯；
5. 内部连接器通过独立权限边界测试、三重过滤测试和授权到期测试；未通过的租户继续禁用internal；
6. 事务恢复、审批失效、外发版重生成和回滚演练通过，并明确停用/降级到公开资料的操作人；
7. 试运行复盘确认检索预算、SLA、ready率和返工原因可观测，再由业务负责人和合规/数据责任人共同批准扩大范围。

任一高风险事件出现时暂停对应模式或连接器，而不是只补文档。问题修复、受影响成果失效标记和复测完成后再恢复。
