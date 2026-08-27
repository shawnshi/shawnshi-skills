# Skill 4：一封信 v2.7.0

## 任务边界

仅在用户选择“一封信”且属于高风险正式信件时，生成首次拜访邀约、来访邀请、会后感谢、材料报送、方案交流或项目跟进信。高风险判定见[四种业务模式](business-modes.md)；普通感谢、通知、材料转发和无关键事实的通用写作不调用本模块。客户信分为内部审核稿和纯净外发版；本模块不自动发送。

## 执行门禁与文件契约

仅在本信件场景所需的研究成果可用、未调用模块原因透明、所需确认轮次完成、用户选择客户信，并确认场景、收件对象（姓名或明确称谓）及角色/身份确认状态、目的、期望动作、签署人和发送渠道后执行；不得把客户信路由扩张为三路全量研究。新建 context 时本轮至少一个 institution/leader/internal 模块承载 claim/source 台账；续建时至少一个 organization_scope 匹配且 completed/current 的历史研究成果已登记为本轮 selected/reused。

内部稿 frontmatter 必须结构化持久化`letter_scenario`、`recipient_role`、`letter_purpose`、`expected_action`、`signer`和`delivery_channel`；`recipient_role`必须同时包含收件对象（姓名或明确称谓）、角色/身份及确认状态，不新增独立`recipient`字段。六项须非空、非占位并与内部审核摘要一致。审批绑定同时绑定这组信件上下文；任一项变化都使既有批准失效。

开始执行时在本run隔离候选工作区使用[客户信内部审核模板](../assets/customer-letter-output-template.md)创建内部稿候选：

```text
{{客户安全名称}}客户信（内部待审核稿）.md
```

内部审核稿状态：

- 开始执行：`module_status: running`、`review_status: not_started`；
- 正文候选完成：`module_status: completed`、`review_status: pending`；
- 身份、合作事实或承诺冲突：`module_status: blocked`、`review_status: not_started`；
- 审核通过：`module_status: completed`、`review_status: approved`，并同时绑定非空`approver`、带时区`approved_at`、当前`approved_content_version`、批准正文`approved_body_sha256`和六项业务上下文`approved_context_sha256`。

只有修改稿处于`pending`，且事实复核人与外发审批人分别通过宿主认证后，才先运行`python3 scripts/validate_outputs.py <workspace> --review-letter-facts --reviewer <事实复核人> --actor-id <fact_reviewer_actor_id> --action-event-id <fact_event_id>`，再由不同真人运行`--approve-letter --approver <外发审批人> --actor-id <approver_actor_id> --action-event-id <approval_event_id>`。宿主必须验证两人的当前角色、客户/模式/操作范围及两个短期签名事件；修改已批准稿前先运行`--begin-letter-revision --reviewer <显示名> --actor-id <actor_id> --action-event-id <revision_event_id>`。“领导”“销售”“AI”等泛化角色、文本显示名或Skill自造身份均不得批准。

内部审核稿达到`completed/approved/current`仅完成第一道门禁。审批后用户必须再次明确要求“生成外发版”，且认证宿主将该新回合记录为与审批run/版本/正文哈希/上下文哈希绑定的未消费event，才运行`python3 scripts/validate_outputs.py <workspace> --emit-external --actor-id <actor_id> --request-event-id <event_id>`。成功事务一次性消费event；审批前请求、过期或重放event一律拒绝。全部治理操作完成后再取得独立就绪事件，运行`--mark-ready --reviewer <显示名> --actor-id <actor_id> --action-event-id <ready_event_id>`和`--profile release`：

```text
{{客户安全名称}}客户信（外发版）.md
```

外发版必须使用同一`context_id/customer_id/safe_name`，YAML frontmatter设置：

```yaml
schema: "discovery-call-output/v2.5"
artifact_type: "customer_letter_external"
module_status: "completed"
review_status: "approved"
connector_status: "not_applicable"
freshness_status: "current"
```

外发版继承同一`context_id/customer_id/customer_display_name/organization_scope/safe_name/evidence_cutoff_date/runtime_owner`，使用外发 run_id、`content_version: 1`和该 run 的带时区更新时间。它只包含完整YAML frontmatter、标题和经过批准的信件正文，不得包含内部审核说明、主张ID、来源ID、任何HTML注释、待核实项、销售判断、竞对、价格底线、关系评价、受限资料或配置的内部词。总报告分别登记内部审核稿和外发版；不存在的外发版不得显示链接。

外发预检必须确认`approved_content_version`等于预检前内部稿当前版本，且按[统一上下文契约](customer-research-context.md#外发审批与生成事务)固定规则重新计算的正文 SHA-256 与六项结构化上下文 SHA-256 分别等于`approved_body_sha256`和`approved_context_sha256`。`approve`和`emit_external`每次都必须向内部稿“版本与审核记录”追加记录，不得覆盖历史；最新记录须与 frontmatter 一致。成功时在一个事务内：内部稿登记`external_output_required=true`并递增版本，在正文和上下文不变时把批准版本绑定到新内部版本；外发版新建为版本1；总报告递增版本并记录新 run、generated 动作和链接。三者使用同一外发 run_id 与 updated_at，evidence_cutoff_date 不因抽取推进。任何写入或校验失败全部回滚。该流程只生成文件，不调用邮件、消息或其他发送工具。

## 场景与篇幅

| 场景 | 结构重点 | 默认篇幅/边界 |
|---|---|---|
| 首次拜访邀约 | 客户任务→交流方向→相关能力/经验→建议时间 | 邮件600—1000字；即时消息不超过350字 |
| 邀请来访/考察 | 邀请缘起→来访价值→议程→可选时间 | 不承诺未确认出席、费用和规格 |
| 会后感谢 | 感谢→已确认共识→双方行动→下一节点 | 不扩大口头意见和承诺 |
| 材料报送 | 对应约定→附件→用途→反馈事项 | 不夹带新商务条件 |
| 方案交流 | 客户背景→问题假设→主题→参会角色→下一步 | 不把假设写成既定痛点 |
| 项目跟进 | 已确认事项→待决问题→我方准备→请求下一步 | 不施压、不擅设时间表 |

多个目的并存时确定一个主目的；根据发送渠道控制长度。

## 执行步骤

1. 核对所有输入成果的上下文标识一致。
2. 从机构、人物和内部成果中选最多3个个性化依据。
3. 核验客户规范名称、院区/部门、收信人现职、合作事实、签署人和期望动作。
4. 按[时效规则](freshness-feedback.md)从`runtime/evidence-manifest.json`逐claim复核收件人、采购/项目阶段、合作事实、承诺和案例授权；重算TTL与source content SHA绑定，任一关键依赖缺记录、过期或内容漂移即阻断外发。
5. 只使用 completed/current 研究中由非C级来源支撑的 F/F2 已核实事实；每条支持来源必须非restricted并显式标记`external_use=true`，`internal-authorized`本身不等于可外发；人物或内部研究载体还须`review_status=approved`且通用审核绑定有效。
6. 在内部审核稿的`EXTERNAL_BODY_START/END`之间写正文候选，在标记外写内部审核说明。
7. 检查价格、免费范围、交付、效果、上线时间、评级、高层出席、案例授权和联合合作承诺。
8. 正文候选完成后设为`completed/pending/current`，总报告候选保持`ready_for_use=false`，向主流程返回摘要、关键主张ID和内部稿候选路径；不得直接改正式Markdown。
9. 人工审核通过后设置`completed/approved`及审批五字段；正文或六项业务上下文变化都使批准失效并退回`changes_requested`。
10. 如用户再次明确要求外发版，另起run原子抽取；生成成功后总报告才具备执行独立ready审批的条件，但仍不发送。
11. 运行输出校验；失败时回滚内部稿、外发版和总报告，不得交付或发送。

若关键依赖后续变为`stale`或`invalidated`，内部稿保留既有`module_status`，同时把`freshness_status`设为对应值、`review_status`设为`changes_requested`并同步成果登记；`pending`或`approved`内部稿只允许`freshness_status: current`。

## 对外边界

不得写入销售判断、竞争态势、价格底线、关系评价、受限资料、未确认承诺或AI推断偏好。不得使用私人关系、家庭、健康、宗教、财产和非公开联系方式。禁止绝对效果承诺和绕过正常程序的表达。

## 完成检查

- 内部稿与外发版的`artifact_type`、状态和文件名正确；
- 内部稿六项结构化信件上下文非空、非占位，且与正文摘要一致；
- 新建上下文至少一个本轮研究模块、续建至少一个 current 历史研究成果提供实际 claim/source 台账；
- 外发版仅在内部稿`review_status: approved`且审批五字段绑定有效后存在；
- 外发版不含内部审核标题、主张ID、来源ID、注释和敏感词；
- 所有内部稿主张ID可追溯到主张台账及其来源台账；
- 总报告链接只指向实际文件；
- `python3 scripts/validate_outputs.py <客户工作目录> --profile candidate`通过；正式外发前`--profile release`通过；
- 外发生成运行在内部稿、外发版、总报告三个文件中的 run_id、版本和带时区更新时间一致且符合各自递增规则；
- 内部稿每次正文更新、批准和外发均追加版本审核记录，最新记录与 frontmatter 一致；
- 发送状态保持“仅生成、未发送”。
- 审批在[审核SLA](governance-raci.md)内完成或明确记录超时；超时不改变门禁。
