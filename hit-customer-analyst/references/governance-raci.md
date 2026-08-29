# RACI、审核与可用状态 v2.10.0

## 1. 核心原则

`closed`只表示一次运行已经安全落盘并结束；它不表示成果已审核、可用于会议或可外发。`ready_for_use`单独记录业务可用性，只允许字符串值`"true"`或`"false"`。

任何审核通过必须同时可追溯到真人和稳定角色/账号。允许显示“张三（华北客户负责人）”；不允许只写“销售”“领导”“审核人”等无法归因的泛化角色。显示名本身不是授权证据：所有审批、修订和就绪操作必须同时提供`--actor-id`与宿主签名、短期、单次的`--action-event-id`；外发操作使用审批后另行签发的`--request-event-id`。宿主注入的`runtime/governance-context.json`须验证`human + active + role + operation + customer + business_mode + valid_from/expires_at`以及事件绑定的版本、正文、上下文、session和nonce。Skill不得创建、补写或扩大身份、授权或人工动作；可信登记不可用时，高风险治理操作必须失败关闭。

本地`DISCOVERY_CALL_GOVERNANCE_NONCE_DIR`只作为试运行故障防重放账本：它可阻断正常重复调用、崩溃恢复和工作区克隆，但同一宿主UID仍可能删除标记。生产审批、mark-ready和外发必须改由Skill进程无删除权限的宿主原子nonce服务（或等价不可删除存储）完成消费；在此之前不得把本地0700目录表述为生产级恶意重放防护。

## 2. RACI

| 角色 | 责任 | 最低身份要求 | RACI |
|---|---|---|---|
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

旧v2.5成果允许没有这些字段；实际更新时补写。无内部检索时授权字段可留空。选择internal时，除上述frontmatter字段外，机器授权还必须同时有效地绑定三重范围、项目白名单、用途、授权根/数据集/密级、connector_id和宿主签发的capability receipt ID。该收据不得由Skill自造或从用户文本推断。

institution、leader、internal、visit_strategy新增通用审核绑定：

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

所有新审批还必须写入结构化身份谱系：

```yaml
# briefing/institution/leader/internal/visit_strategy
reviewer_actor_id: "employee_id"
reviewer_role: "按下表artifact/mode矩阵"
reviewer_authority_id: "grant_id"
reviewer_identity_provider: "corp-sso"
review_action_event_id: "signed_event_id"

# customer_letter
approver_actor_id: "employee_id"
approver_role: "external_approver"
approval_authority_id: "grant_id"
approver_identity_provider: "corp-sso"
fact_reviewer_actor_id: "employee_id"
fact_review_action_event_id: "signed_event_id"
approval_action_event_id: "signed_event_id"

# comprehensive_report readiness
readiness_reviewer_actor_id: "employee_id"
readiness_reviewer_role: "按business_mode要求"
readiness_reviewer_authority_id: "grant_id"
readiness_reviewer_identity_provider: "corp-sso"
readiness_action_event_id: "signed_event_id"
readiness_target_body_sha256: "审批前总报告正文SHA-256"
```

`reviewer_role`与`readiness_reviewer_role`不得按自由文本解释，必须按成果与模式同时判定：

| 操作 | artifact | business_mode | 允许角色 |
|---|---|---|---|
| 通用成果审核 | institution_research / leader_research / internal_retrieval | 任一适用模式 | `evidence_reviewer` |
| 通用成果审核 | visit_strategy | standard_visit / strategic_account | `commercial_reviewer` |
| 通用成果审核 | briefing_delivery | briefing（含具名身份、采购、合作或内部事实） | `evidence_reviewer` |
| 通用成果审核 | briefing_delivery | briefing（仅公开机构事实的低风险速览） | `evidence_reviewer`或`account_owner` |
| 客户信事实复核 | customer_letter_internal | letter | `evidence_reviewer`；写入`fact_reviewer_role` |
| 客户信外发审批 | customer_letter_internal | letter | `external_approver`；写入`approver_role` |
| 包级mark-ready | comprehensive_report | briefing | `evidence_reviewer`或`account_owner` |
| 包级mark-ready | comprehensive_report | standard_visit | `commercial_reviewer` |
| 包级mark-ready | comprehensive_report | strategic_account | `account_owner` |
| 包级mark-ready | comprehensive_report | letter | `external_approver` |

表中“低风险速览”沿用第4节和第6节边界；不满足该边界时，`account_owner`不能替代`evidence_reviewer`完成事实审核。通用成果的`reviewer_role`记录成果审核角色，综合报告的`readiness_reviewer_role`只记录包级mark-ready角色，二者不得互相替代。

非approved或`ready_for_use=false`时，对应显示字段、哈希字段和身份谱系字段必须全部清空。旧成果只有自由文本审批人时可读但不再视为有效批准；更新前先降级为pending/changes_requested或ready=false，再走可信身份审批。

治理写命令的`--reviewer/--approver`仅用于友好显示，`--actor-id`才是授权查询键。宿主显示名与actor登记不一致、actor停用、grant过期或不覆盖当前操作/客户/模式时，命令必须在文件哈希不变的前提下退出。

正文哈希规范化沿用客户信规则：CRLF/CR转LF、去除每行尾随空白和首尾空行，UTF-8无BOM、无末尾换行后计算SHA-256。

## 4. 审核对象

| 成果 | 必审内容 | 默认审核人 |
|---|---|---|
| 会前速览 | 具名身份、关键采购/合作事实、一个推进动作 | evidence_reviewer；无具名/采购/内部事实的低风险速览可由account_owner快速确认 |
| 标准拜访包 | 事实、议题、机会资格、分工、承诺边界 | evidence_reviewer＋commercial_reviewer |
| 战略客户包 | 全部关键事实、竞争与投入建议、win/no-go | evidence_reviewer＋commercial_reviewer＋account_owner |
| 一封信内部稿 | 收件人、外发事实、承诺、签署与渠道 | evidence_reviewer＋external_approver |

institution、leader、internal完成执行后均进入`pending`。所有被本轮选中或被任一下游成果引用的研究载体，必须由与生成者独立的`evidence_reviewer`按当前正文SHA完成宿主签名审核，才能mark-ready或release；把载体标为unselected不能绕过仍存在的下游claim引用。该审核是语义事实门禁，candidate封印和来源收据只证明完整性与捕获谱系，不能替代人工事实判断。

## 5. 审核SLA

SLA从“成果提交为pending且审核材料完整”开始，不从任务创建开始：

| 模式 | 正常SLA | 紧急SLA | 超时处置 |
|---|---|---|---|
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
5. account_owner、runtime_owner和下一步owner可归因；
6. 受限信息未进入更低权限成果；
7. 关键冲突已解除或明确降级为现场问题。

模式附加条件：

- briefing：1页上所有具名身份、采购、合作事实已经复核；若只包含公开机构事实，可由account_owner确认后ready=true。
- standard_visit：visit_strategy approved；议程、分工、材料、主动作owner和due_date完整。
- strategic_account：综合机会判断经account_owner和commercial_reviewer确认；win/no-go与投入建议一致。
- letter：内部使用时内部稿可保持pending且ready=false；只有内部稿approved、审批及身份谱系匹配、宿主在审批后记录了第二次明确外发请求、该请求被外发事务一次性消费、外发版completed/approved/current且谱系一致时，才允许ready=true。只有内部稿时不得mark-ready。

### 外发第二次请求事件

`runtime/governance-context.json.external_requests[event_id]`由认证宿主记录，不由Skill生成。事件至少绑定`actor_id、source=authenticated_user_turn、verified=true、context_id、customer_id、approval_run_id、internal_content_version、approved_body_sha256、approved_context_sha256、requested_at、expires_at`。`requested_at`必须晚于当前`approved_at`，且事件未过期、未消费。

外发命令必须同时提供`--actor-id`和`--request-event-id`。成功外发在同一WAL事务内写外发文件、更新内部稿/总报告，并把事件标记`consumed_at/consumed_by_run_id`；任一步失败必须一并回滚。事件不可重放，审批前请求、聊天文本转述或模型自行生成的事件均无效。

任何条件失效时立即把`ready_for_use`改为`"false"`并清空四个readiness字段。只有执行独立就绪审批后才可设为true；readiness_reviewer须可追溯到真人/稳定角色，版本与正文哈希须匹配当前总报告。总报告和交付消息必须同时展示ready状态及原因。

## 7. 试运行与推广门禁

状态保持“试运行”，直到以下条件均有真实项目记录支撑：

1. 发布计数只以[发布前向评估证据门禁](forward-evaluation.md)为准：四种业务模式各不少于3个成功T1正链，共至少12个正链slot；另有不少于3个T2冲突阻断和不少于3个T3高风险安全拒绝，共至少6个负链slot、总slot不少于18，且T2/T3不得占用T1额度；
2. account_owner、主/备reviewer、authorization_owner和故障响应人均已实名排班，审核SLA在实际工作时段可兑现；
3. `closed`冒充ready、匿名审批、越权内部检索、未经确认写回或自动发送事件为零；
4. 会前速览稳定满足1页，其他模式的用户正文与审计附件可分发且关键主张可回溯；
5. 内部连接器通过独立权限边界测试、三重过滤测试和授权到期测试；未通过的租户继续禁用internal；
6. 事务恢复、审批失效、外发版重生成和回滚演练通过；宿主隔离nonce服务已部署，并验证消费后删除、回滚和克隆重放均失败；同时明确停用/降级到公开资料的操作人；
7. 试运行复盘确认检索预算、SLA、ready率和返工原因可观测，再由业务负责人和合规/数据责任人共同批准扩大范围。

任一高风险事件出现时暂停对应模式或连接器，而不是只补文档。问题修复、受影响成果失效标记和复测完成后再恢复。
