# CustomerResearchContext统一上下文契约 v2.7.0

## 目录

1. 用途与持久化
2. 标识和逻辑字段
3. 分离状态
4. 模块与成果登记
5. 单写者合并
6. 复用、刷新和恢复
7. 信息与证据

## 用途与持久化

CustomerResearchContext 是 discovery-call 的唯一逻辑状态模型。它服务于同一客户或项目的连续研究、拜访准备、策略、客户信和增量刷新。

不单独创建另一份业务上下文 JSON。可恢复的业务状态持久化到综合总报告；事务、缓存和机器验证状态持久化到`runtime/`：

- 文件头：保留v2.5全部字段，并新增`business_mode、ready_for_use、readiness_reviewer、readiness_reviewed_at、readiness_content_version、readiness_body_sha256、tenant_id、project_id、authorization_owner、authorization_expires_at`。route/depth继续存在但只作内部兼容。
- 成果登记表：模块、选择/动作、四类状态、content_version、latest_run_id、updated_at、摘要同步、关键主张、下游失效、缺口和阻塞，以及唯一的“成果链接”列；该列的 Markdown 链接目标就是`artifact_path`，显示文本就是`link`，不存在第16个物理列。
- 运行记录：每个 run_id 的 route、depth、objective、target_evidence_cutoff_date、selected_modules，以及各成果 created/updated/reused/generated/not_called 动作。
- 刷新记录：新增、更正、失效、未变化和待确认事项。

每个独立成果继续记录v2.5字段。`briefing_delivery`是会前速览必需的可独立交付成果，必须使用1页模板、独立文件头和通用审核绑定。leader、internal、visit_strategy和briefing的approved必须绑定`reviewer、reviewed_at、reviewed_content_version、reviewed_body_sha256`及可信actor身份谱系；非approved时全部清空。交流策略固定记录`strategy_variant`：scheduled_visit记录`target_contact_level/visit_objective/minimum_next_step`，account_planning记录`strategic_question/planning_horizon/minimum_next_step`；客户信内部稿继续使用既有六项信件上下文、审批绑定和可信身份谱系。

总报告的`artifact_type`固定为`comprehensive_report`；其module_status描述主流程综合，review_status默认`not_required`。v2.7最终交付必须通过独立就绪审批：`ready_for_use=true`及全部readiness显示、哈希和actor身份谱系与当前总报告一致。`closed`只表示运行结束，不等于ready或approved。

## 标识和逻辑字段

context_id 在同一客户与 organization_scope 内稳定复用；run_id 每次执行唯一，在持久化字段中始终写作 latest_run_id。context_id 格式为 dcx-YYYYMMDD-8chars；context_id_short 取最后一段8位，只用于目录名且不另行持久化。显示名称与路径名称分开保存。

runtime_owner 依次取用户明确负责人、项目元数据负责人、当前执行用户；三者都不可用时统一写“待确认”，不得留空或回退到 Skill 维护负责人。

    meta
      schema: discovery-call-output/v2.5
      context_id, latest_run_id, customer_id, tenant_id
      customer_display_name, safe_name, aliases
      business_mode, ready_for_use
      readiness_reviewer, readiness_reviewed_at
      readiness_content_version, readiness_body_sha256
      tenant_id, project_id, authorization_owner, authorization_expires_at
      customer_type, region, organization_scope
      created_at, updated_at, evidence_cutoff_date
      artifact_type, module_status, review_status, connector_status
      content_version, freshness_status, runtime_owner, participants, report_path

    routing
      business_mode: briefing | standard_visit | strategic_account | letter
      route: research_only | visit_prep | strategy | letter | refresh
      depth: quick | standard | deep
      selected_modules, requested_outputs, source_scope
      reuse_policy, refresh_scope, expected_outcome
      authorization_scope:
        tenant_id, customer_id, project_id
        allowed_project_ids, authorized_roots
        allowed_dataset_aliases, allowed_confidentiality
        requester, authorization_owner, authorization_purpose, authorization_expires_at
        connector_id, capability_receipt_id, authorization_actor_id
        capability_operation, capability_receipt_verified
        capability_receipt_issuer, capability_receipt_key_id
        capability_receipt_sha256, capability_receipt_verified_at
        capability_receipt_expires_at

    workflow
      workflow_stage, started_at, paused_at, closed_at
      review_submitted_at, review_due_at, review_sla_status
      open_questions, critical_conflicts, change_summary

    run_history[]
      run_id, route, depth, objective, target_evidence_cutoff_date
      selected_modules
      artifact_actions: created | updated | reused | generated | not_called
      started_at, completed_at

    refresh_history[]
      run_id
      added_ids, corrected_ids, invalidated_ids
      unchanged_ids, pending_confirmation_ids

    module_outputs
      institution, leader, internal, visit_strategy, customer_letter
        selected_in_run, run_action, artifact_type
        module_status, review_status, connector_status, freshness_status
        artifact_path, external_artifact_path, link
        content_version, latest_run_id
        started_at, updated_at, completed_at
        summary_sync_status, sync_classification
        reviewer, reviewed_at, reviewed_content_version, reviewed_body_sha256
        key_claim_ids, downstream_invalidation, gaps, blockers

    derived_artifacts
      briefing
        selected_in_run, run_action=created|updated|reused|not_called
        artifact_type=briefing_delivery, artifact_path
        content_version, latest_run_id, updated_at, approval_lineage, link
      external_letter
        selected_in_run, run_action=generated|not_called, artifact_type
        artifact_path, content_version, latest_run_id, updated_at
        approval_lineage, link

    visit_context
      strategy_variant: scheduled_visit | account_planning
      target_people, target_contact_level, visit_time
      visit_objective, strategic_question, planning_horizon
      expected_outcome, minimum_next_step
      priority_topics, avoid_topics

    letter_context
      letter_scenario, recipient_role, letter_purpose
      expected_action, signer, delivery_channel, external_claims
      internal_artifact_path, external_artifact_path
      approver, approved_at, approved_content_version
      approved_body_sha256, approved_context_sha256

`recipient_role`同时持久化收件对象（姓名或明确称谓）、角色/身份和确认状态；不新增独立`recipient`字段。

    user_inputs
      raw_inputs, uploaded_files, confirmed_unknowns
      confirmations, corrections, source_authorizations

    runtime_sidecars
      manifest.json
        intake_preflight, authorization, runtime_files, revision, task_timezone
      search-plan.json, source-cache.json
      evidence-manifest.json, run-metrics.json
      governance-context.json

`governance-context.json`是认证宿主注入的可信登记，Skill只能在经授权的WAL事务内消费外发请求事件，不得新建actor/grant/event。另四个研究机器文件必须与Markdown使用同一`context_id/run_id/business_mode`，由manifest记录schema和SHA-256。

    institution_profile
      identity, positioning, history, development_timeline
      strategic_tasks, operations, disciplines, policy_environment
      it_maturity, procurement_landscape, supplier_landscape
      decision_structure, decision_profile, current_window, gaps

    leader_profiles[]
      person_id, identity_status, same_name_exclusion
      name, current_role, tenure, responsibilities
      career_timeline, public_views, thought_map
      procurement_relevance, professional_collaboration
      decision_profile, duty_environment
      communication_hypotheses, gaps, confidence

    internal_context
      cooperation_history, project_stage, installed_systems
      known_needs, customer_feedback, sales_judgements
      commitments, competitors, risks, source_scope, confidentiality

    source_registry[]
      source_id, source_title, publisher_or_provider, source_locator
      publish_or_update_date, accessed_at, source_level
      source_group, source_fingerprint, upstream_id
      confidentiality, external_use, customer_id, project_id, notes

    claim_registry[]
      claim_id, claim_type, provenance, verification_status
      information_subtype, claim_text, time_scope
      supporting_source_ids, counter_source_ids
      confidence, downstream_impact, notes

    research_synthesis
      verified_facts, cross_validated_facts, analyses
      hypotheses, recommendations, conflicts, gaps
      decision_chain, institution_decision_profile
      leader_decision_profile, gcp, verification_questions
      overall_confidence

    feedback
      visit_date, participants, customer_quotes
      confirmed_updates, invalidated_hypotheses
      opportunity_stage, procurement_timeline, competitor_change
      decisions, actions(owner, due_date, completion_criteria)
      next_contact, writeback_status

## 分离状态

### 模块状态 module_status

只描述模块执行情况：

- not_called：本轮未选；不创建新文件。
- queued：已选，等待执行。
- running：正在执行；对应文件必须已创建且非空。
- partial：已输出可用部分，仍有明确缺口。
- completed：本轮范围已完成，文件和门禁通过。
- blocked：关键身份、权限、输入或工具使本轮范围无法完成。

允许转换：

    not_called → queued → running → partial | completed | blocked
    partial | completed | blocked → queued → running    仅刷新或纠错
    running → queued                                     中断后安全重排

partial、completed、blocked 都是本轮可交付终态。blocked 必须写明已尝试动作、影响和解除条件。

成果登记中partial/blocked的`gaps/blockers`不得写“无”；blocked统一采用“已尝试：…；影响：…；解除条件：…”以便机械校验和恢复。

### 审核状态 review_status

只描述人工审核，不改变模块执行状态：

- not_required：本成果不需要人工审核。
- not_started：需要审核但尚未提交。
- pending：已提交审核。
- approved：审核通过。
- changes_requested：要求修改。

允许转换：

    not_required
    not_started → pending → approved | changes_requested
    changes_requested → pending

institution 默认`not_required`；leader、internal、visit_strategy、customer_letter 默认需要审核，执行中为`not_started`，内容完成后为`pending`。leader/internal/visit_strategy只有在通用审核四字段与当前版本、正文哈希一致时才能approved；customer_letter继续按专用审批五字段。任何状态都不授权自动发送。

### 连接状态 connector_status

只描述当前模块依赖的连接或资料库：

- not_applicable
- not_configured
- connected
- no_hits
- permission_denied
- failed

connector_status 不得代替 module_status。例：资料库未配置但本地材料可用时，可写 module_status: partial、connector_status: not_configured；权限导致完全无法执行时，可写 module_status: blocked、connector_status: permission_denied。

当本轮只使用用户明确提供的文件或其他已授权材料、未计划也不依赖任何内部连接器时，写`connector_status: not_applicable`；它不同于已计划使用连接器但尚未配置的`not_configured`。初始化 CLI 的`--internal-connector-status`必须能表达这两个值。

### 时效状态 freshness_status

只描述当前成果能否继续被下游使用：

- current：关键依赖主张当前有效。
- stale：关键依赖主张过期或发生未解变化，需要刷新。
- invalidated：关键依赖主张已失效，成果不得继续使用。

关键身份、合作事实、采购阶段或承诺发生 conflicted、stale 或 invalidated 时，模块返回 downstream_invalidation。依赖它的策略和客户信改为 freshness_status: stale 或 invalidated，并将 review_status 设为 changes_requested；module_status 保留既有执行结果。

对`visit_strategy`和`customer_letter_internal`，`review_status: pending|approved`只允许与`freshness_status: current`组合；一旦 freshness 为 stale/invalidated，必须改为 changes_requested，并同步综合报告成果登记行。

### 流程阶段 workflow_stage

- intake：接收任务。
- disambiguation：主体或上下文消歧。
- planning：确定路由、档位、模块和来源范围。
- research：模块执行。
- synthesis：主流程综合。
- confirmation：仅处理高影响冲突、策略或外发门禁。
- output：主流程更新总报告和交付。
- review：等待人工审核。
- closed：本轮结束。
- paused：中断，等待恢复。

典型路径：

    intake → disambiguation → planning → research → synthesis → output → review → closed
    closed → planning                                      新 run 增量刷新
    任意执行阶段 → paused → 原阶段或 planning

旧route仍按原路径兼容；四种业务模式的最终使用还须独立执行ready_for_use门禁。closed后仍可等待审核，ready_for_use=false时必须明确“仅草稿/底稿”。

### v2.4 成果迁移（仅在读取历史成果时）

- v2.4 成果状态 `review_required`：转换为 module_status: completed、review_status: pending。
- v2.4 组合值 `partial/not_connected`：拆为 module_status: partial、connector_status: not_configured。
- v2.4 `connector_status: not_connected`：转换为 connector_status: not_configured。
- v2.4 将 `permission_denied` 写入成果状态时：迁移到 connector_status，module_status 按实际影响设为 partial 或 blocked。
- v2.4 `outputs_generated` 不迁移为状态；重算关闭门禁并设定 workflow_stage。
- 迁移只读取和规范化历史值；v2.6新写入不得产生上述旧值，输出schema仍保持v2.5兼容。

## 模块与成果登记

| 模块 | 独立成果 | 默认审核 | 连接状态适用 |
|---|---|---|---|
| institution | {{safe_name}}机构研究报告.md | not_required | 否 |
| leader | {{safe_name}}人物研究报告.md | pending | 否 |
| internal | {{safe_name}}内部信息检索报告.md | pending | 是 |
| visit_strategy | {{safe_name}}交流策略与议题设计.md | pending | 否 |
| customer_letter | {{safe_name}}客户信（内部待审核稿）.md；审核通过且用户明确要求时可增加 {{safe_name}}客户信（外发版）.md | pending | 否 |

逻辑模块固定为上述5个。为让外发生成拥有独立版本、谱系、run_id和回滚审计，综合报告另持久化第6行“客户信外发版”；它是`customer_letter`的派生成果，不是可由`--modules`选择的模块，仅外发事务可把其登记为`selected_in_run=true/run_action=generated`。运行记录中的`selected_modules`沿用历史字段名，但在该系统事务中可包含审计名称`external_letter`。

`external_letter`在成果登记和全部历史运行摘要中的动作只允许`generated`或`not_called`；`created`、`reused`、`updated`均非法。生成外发版的 run 写`generated`，其他 run 写`not_called`。

成果登记表至少包含：

| 字段 | 要求 |
|---|---|
| artifact_type | 使用固定英文成果类型；总报告固定中文行标签按模板映射 |
| selected_in_run | 本 run 是否调用 |
| run_action | not_called、created、reused、updated 或 generated |
| module_status | 使用合法枚举 |
| review_status | 使用合法枚举 |
| connector_status | 使用合法枚举 |
| freshness_status | 使用合法枚举 |
| 成果链接（artifact_path/link） | 这是成果登记的唯一物理列：Markdown 链接目标是成果的独立相对`artifact_path`，显示文本是`link`；文件不存在时不能伪造链接或拆出第16列 |
| content_version | 每次实际更新递增 |
| latest_run_id | 最后修改该文件的 run_id |
| updated_at | 带时区时间；只有该成果实际修改时更新 |
| summary_sync_status | pending、synced、out_of_sync 或 not_applicable |
| key_claim_ids | 总报告摘要所依赖的主张ID；无则写“无” |
| downstream_invalidation | 只用 none、stale、invalidated |
| gaps/blockers | 无则写“无” |
| reviewer/reviewed_* | leader/internal/visit_strategy approved时绑定当前版本与正文；其他状态清空 |

已有文件在本轮未调用时保留，但 selected_in_run 为 false、module_status 不冒充本轮状态，latest_run_id 保持原值。

## 单写者合并

- 主流程是综合总报告唯一写者。
- 子模块只写候选工作区内映射到自己artifact_path的候选文件，不得编辑正式Markdown、综合总报告、成果登记表或其他模块候选。
- 模块完成后通过自己的候选文件向主流程提供摘要、关键判断、缺口、key_claim_ids、downstream_invalidation、版本和状态。
- 并行模块全部达到本轮终态后，主流程串行读取并合并。
- 主流程将 summary_sync_status 设为 synced；模块文件更新而总报告尚未合并时为 pending 或 out_of_sync。
- 不参与总报告摘要同步的外发版或未生成成果用 summary_sync_status: not_applicable。
- 总报告只同步摘要和决策价值，不复制完整模块底稿。
- 总报告与模块版本不一致时，以 content_version 和 updated_at 更新的模块底稿重新同步；事实冲突必须保留为 verification_status: conflicted，不能用“最新模块”决定真伪。
- 模块不得自行宣告 workflow_stage: closed。

## 内部路由关闭门禁

下表仅保留v2.5 route兼容。用户业务模式和ready门禁以[四种业务模式](business-modes.md)及[审核治理](governance-raci.md)为准。

| route | 可关闭条件 |
|---|---|
| research_only | 所选研究达到 partial/completed/blocked 终态且 current；缺口/阻塞透明；completed 人物/内部判断已 pending 或 approved；总报告已同步 |
| visit_prep | 新建时本轮至少一个研究模块；续建时至少一个 completed/current 历史研究成果可复用，或至少一个既有研究成果同时选中并由`--refresh-modules`在本 run 更新；关闭前研究依赖 completed/current 且审核可用；策略 completed/current 且 pending 或 approved；目标和最小动作明确 |
| strategy | 新建时本轮至少一个研究模块；续建时至少一个 completed/current 历史研究成果可复用，或至少一个既有研究成果同时选中并由`--refresh-modules`在本 run 更新；关闭前研究依赖 completed/current 且审核可用；策略 completed/current 且 pending 或 approved |
| letter | 新建时本轮至少一个研究模块；续建时至少一个 completed/current 历史研究成果可复用，或至少一个既有研究成果同时选中并由`--refresh-modules`在本 run 更新；关闭前研究依赖 completed/current 且审核可用；外发事实不能依赖 partial/blocked 结论；内部稿 completed/current 且 pending 或 approved；外发版如已请求还须审批绑定完整 |
| refresh | 必须续建且只选择 institution/leader/internal；strict 下至少选择一个研究成果，动作只允许 created/updated，成果由本 run 实际写入且截止日等于合并后总报告；所选研究达到 partial/completed/blocked 终态且 current、总报告已同步；变更摘要及本 run 六列刷新结果记录已写入 |

旧上下文的`research_only`按兼容门禁直接关闭；v2.6新请求即使只要客户研究，也按会前速览、标准拜访包或战略客户包的最终成果范围建模，不向用户呈现`research_only`。未选择客户信不构成缺口。

策略或客户信内部稿达到`completed/pending/current`后，可以在明确标注“待人工审核、未发送、ready_for_use=false”的前提下关闭本次内部生产运行；`approved`只用于确认模块审核已通过，仍不代表总成果ready或已发送。completed人物与内部判断同样至少进入pending。partial/blocked研究可作为缺口透明的阶段性底稿进入closed，但不能支撑关键策略或外发事实。

任何route只有在必需成果已实际持久化、文件审计通过后才能进入closed。最终业务使用还必须取得宿主签名的短期人工动作事件，独立执行`--mark-ready --reviewer <显示名> --actor-id <actor_id> --action-event-id <event_id>`并完成readiness哈希/版本/可信actor谱系绑定。无文件写入能力时必须设paused，不得声称本轮完成。

### 外发审批与生成事务

内部稿的`review_status: approved`不是单独布尔值，必须绑定：`approver`、`approved_at`、`approved_content_version`、`approved_body_sha256`、`approved_context_sha256`。正文哈希规范化固定为：抽取唯一标记对之间的文本，将CRLF/CR转为LF，去除每行尾随空白和首尾空行，以UTF-8（无BOM、无末尾换行）计算小写SHA-256。上下文哈希固定对按字段名排序的六项结构化信件上下文序列化为紧凑 UTF-8 JSON 后计算小写 SHA-256。外发预检时批准版本必须等于当前内部稿版本，两个哈希必须分别匹配当前正文和当前上下文。任一字段缺失、上下文变化或正文漂移都视为未批准。

所有审批、修订、就绪和外发命令还必须带`--actor-id`，宿主可信登记必须确认该真人的当前角色、操作、客户、模式和有效期授权。客户信审批之后，还必须由认证宿主记录新的、未消费的`authenticated_user_turn`外发请求事件；`--emit-external --actor-id <actor_id> --request-event-id <event_id>`必须同时匹配审批run、版本、两个哈希和时序，并在同一WAL事务中一次性消费该事件。

内部稿正文中的“版本与审核记录”是审批审计链的一部分。每次正文更新、`approve`和`emit_external`都必须追加一行，不得覆盖或改写历史；后两类行的变更摘要须明确动作。最新一行的`updated_at/content_version/latest_run_id/runtime_owner/review_status`必须与 frontmatter 一致，严格校验、批准和外发均须核对。

外发生成是独立 run，只做文件生成、不发送；运行记录写`route: letter`、`objective: generate_external`、沿用既有证据截止日作为 target，并把 customer_letter 及至少一个原信件依赖的 current 研究载体列为 selected；动作分别记录研究载体 reused、内部稿 updated、外发版 generated。在写入前拒绝符号链接、重复 frontmatter、HTML 注释、内部审核词和敏感内部词。成功事务同时完成：内部稿登记本次外发、追加审核记录并递增 content_version，在正文与六项信件上下文未变的前提下把 approved_content_version 绑定到递增后的内部稿版本；外发版以 content_version: 1 创建；总报告递增 content_version 并同步登记、运行记录和链接。三者写同一外发 run_id 与同一带时区 updated_at；只做正文抽取时不推进 evidence_cutoff_date。任何校验或写入失败，三者恢复到运行前状态。

### 文件完整性

总报告、模块、briefing和外发版都必须是工作目录内的普通文件。初始化、续建、校验和外发生成均拒绝符号链接、路径逃逸及重复frontmatter。

任何研究run先由`build_candidate.py`基于当前manifest创建新的隔离候选工作区；模块、汇总器和`research_plan.py`只能写该候选区。候选提交必须同时包含本run的`runtime/search-plan.json`、`source-cache.json`、`evidence-manifest.json`和`run-metrics.json`；缺文件、schema/context/run/mode不匹配、清单SHA不匹配或正式区发生任何变化都拒绝提交。

`runtime/manifest.json.evidence_run_id`记录四件套所属研究run。四件套必须run一致，且该run必须存在于综合报告版本历史；后续审批、就绪等治理run可以推进`latest_run_id`而不伪造研究重跑。Markdown主张/来源仍须与当前evidence/source-cache逐项一致。每条source另嵌入宿主签名source-capture receipt，绑定定位、内容摘要、长度、捕获方法与时间及run/customer/project；候选校验使用受保护宿主信任根验签，不持久化敏感原文。

init/resume的`scaffold`允许保留上一研究run四件套作为历史快照；只有candidate/release才要求新plan与当前selected_modules、同一份intake收据完全绑定。两处持久化的`intake_preflight.expires_at`必须相等且在校验时仍有效，否则报`intake_preflight_expired`并重新预检、重建候选。

主流程在候选中完成综合报告和`--profile candidate`预检后，以当前manifest revision/hash为CAS前提调用`commit_run.py --strict`统一提交Markdown与四个机器文件。各目标经WAL和原子替换，提交后立即全量复检；任一写入或复检失败时回滚本run全部目标和manifest。发现journal或异常中断时先运行`recover_workspace.py <workspace> --strategy auto`，不得手工复制候选文件到正式区。

### 验证profile

- `--profile scaffold`：仅用于初始化后和恢复预检；允许模板占位符，输出只能标`scaffold_not_deliverable`。
- `--profile candidate`：默认；占位符、孤立主张/来源、缺机器证据绑定或候选不一致均为错误，通过后只表示`draft_for_review`。
- `--profile release`：另要求必需成果、审核谱系、逐claim TTL、就绪绑定和外发治理完整，通过才能标`release_ready`。`--strict`是该profile的兼容别名，不得与其他profile并用。

## 复用、刷新和恢复

### 定位上下文

1. 优先使用用户给出的 context_id 或总报告路径。
2. 否则按客户规范名、organization_scope 和 safe_name 查找。
3. 唯一匹配时复用；多个匹配时向用户列最多3个候选。
4. 用户明确要求重新开始时才创建新 context_id。

`refresh`没有唯一既有上下文时不得初始化；须改判并确认 research_only 或 visit_prep。新建 visit_prep、strategy、letter 必须在本轮创建至少一个研究模块作为 claim/source 台账载体。续建这些输出路由时，要么将至少一个 organization_scope 匹配、module_status: completed、freshness_status: current 的历史研究成果登记为`selected_in_run=true/run_action=reused`；要么用`--refresh-modules`指定既有且同时属于本轮 selected_modules 的 institution/leader/internal 成果（CLI 中须同时列入`--modules`），并将其本 run 动作记为`updated`，其他被选中且可用的研究成果仍记`reused`。`--refresh-modules`不得用于新建、research_only 或 refresh 路由，也不得包含输出成果；显式更新的既有终态研究可在规划时为 partial 或 stale，但 strict 输出前必须 completed/current 并满足相应审核要求。

新建上下文必须显式提供`--task-timezone <IANA时区>`或`--evidence-cutoff-date <YYYY-MM-DD>`，两者均省略时初始化失败。任务时区只写入`runtime/manifest.json`的可选`task_timezone`字段，不改变`discovery-call-output/v2.5`成果frontmatter；续建自动继承，已建立后不得在同一context中变更。旧v2.5清单或只给显式日期的上下文允许缺少该字段，并采用最多比UTC日期晚一天的兼容民用日窗口，超过该窗口仍拒绝。

### 增量刷新

1. 生成新 run_id，保留 context_id；refresh 只选择 institution、leader、internal。
2. 初始化时只登记 target_evidence_cutoff_date、route、depth、objective、selected_modules 和计划动作，不改变总报告及历史成果的 evidence_cutoff_date、freshness_status。
3. 根据 refresh_scope 选择受影响研究模块，不全量重跑；如需策略或客户信，route 分别改为 strategy 或 letter。
4. 稳定历史事实和仍有效证据复用；现职、分工、项目阶段、金额、供应商状态和近期政策重新核验。
5. 新来源和主张追加；旧主张标 stale、conflicted 或 invalidated，旧来源继续保留。
6. 只增加实际更新模块 content_version；其他模块保持版本。
7. 证据合并完成后，主流程才更新总报告变更摘要、evidence_cutoff_date、freshness_status、latest_run_id、updated_at 和 content_version。
8. 在综合报告`## 8.1 刷新结果记录`追加本 run 的六列表格行：`run_id｜新增｜更正｜失效｜未变化｜待确认`。五类结果单元格只允许逗号分隔的 claim/source ID，或精确值`none`；不得留空、写自由文本或占位符。
9. strict refresh 至少选择一个研究成果；每个所选成果的动作只能是 created/updated，latest_run_id 必须等于本 run，evidence_cutoff_date 必须等于合并后总报告；reused 成果或旧 cutoff 不能满足本轮刷新。
10. closed 前确认最新刷新记录的 run_id 等于总报告 latest_run_id，且最新运行记录 target_evidence_cutoff_date 等于总报告 evidence_cutoff_date；首次运行或缺少本轮刷新记录不得以 refresh 关闭。

复用和刷新还须执行[信息TTL与会后反馈](freshness-feedback.md)。文件更新时间或evidence_cutoff_date不能替代人物、采购、机构、内部信息各自TTL；过期依赖必须先标stale。

### 会后反馈与回填

拜访后记录确认/否定、机会阶段、采购时序、竞争变化和`action/owner/due_date`，先形成CRM/PIMS写回候选。只有连接器真实可执行、三重授权有效、data_steward实名且用户明确要求时才实际写回，并须回读核对。

### 中断恢复

1. 读取总报告中的 context_id、latest_run_id、workflow_stage 和成果登记。
2. 检查 running、queued、summary_sync_status 非 synced 的模块。
3. 读取这些模块文件并核对 content_version、latest_run_id 和 updated_at。
4. 从安全阶段恢复；不重复已完成且未过期的检索。
5. 找不到总报告但存在模块文件时，先暂停并重建最小成果登记，不擅自合并不同 context_id。

## 信息与证据

- claim_type：F事实、F2交叉验证事实、A分析、H假设、R建议。
- provenance：public、U用户提供、N内部记录。U/N 只表示来源，不表示已核实。
- verification_status：asserted、verified_single、corroborated、conflicted、stale、invalidated、unusable。
- F 只能对应 verified_single；F2 只能对应 corroborated。F2 要求支持来源中存在至少一对来源：该同一对的 source_group、locator/source_locator、content_sha256、upstream_id 四项都有效且逐项不同；upstream_id 为`unknown:<source_id>`的来源不能成为该对成员；其他补充支持来源不影响这对成立。不存在这样的同一对时不能形成 F2。
- source_id 与 claim_id 分开；正文引用 claim_id，主张台账再连接支持和反证 source_id。每条来源必须给出稳定locator、非空source_group、实际捕获内容的content_sha256、capture metadata、upstream_id、权限、适用范围和`external_use: true|false`；restricted不得标true，internal-authorized也不自动代表可外发。
- 每条claim在evidence manifest中必须记录信息类别、证据锚点、日期基础、核验时间、TTL、到期时间和支持来源；验证器重算TTL并校验source cache/Markdown/evidence manifest三方内容SHA绑定。
- 销售判断使用 information_subtype: sales_judgement；历史口头信息使用 information_subtype: oral_history，不能重定义 A 或 H。
- 权限：public、internal-authorized、restricted；来源等级：S、A、B、C、internal。
- A、H、R 回指主张ID，并写推理、反证或边界、置信度和验证方式。
- 新来源和主张追加，不静默改写；每个来源必须有稳定定位、实际捕获内容的64位小写SHA-256、捕获元数据和共同上游标识；稳定ID和URL哈希不能替代内容哈希。转载、镜像和同一上游按 source_group/upstream_id 合并；上游不明时写`unknown:<source_id>`，该来源不能成为满足 F2 门槛的来源对成员，但不妨碍其他合格来源对成立。
- 关键主张冲突返回 downstream_invalidation；客户信只读取允许外发、已核实且 current 的主张。
