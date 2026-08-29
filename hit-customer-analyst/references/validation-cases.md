# discovery-call v2.10.0 可执行验证契约

本文件同时定义静态断言、CLI 冒烟测试与真实前向测试矩阵。命令均从 Skill 根目录执行；临时目录须使用 `mktemp -d`。

## 1. 统一成果契约

每个成果 frontmatter 必须包含：

`schema, artifact_type, context_id, latest_run_id, customer_id, customer_display_name, organization_scope, safe_name, module_status, review_status, connector_status, freshness_status, content_version, evidence_cutoff_date, updated_at, runtime_owner`

综合报告还必须包含`business_mode, ready_for_use, readiness_reviewer, readiness_reviewed_at, readiness_content_version, readiness_body_sha256, tenant_id, project_id, authorization_owner, authorization_expires_at, route, depth, workflow_stage`。briefing/leader/internal/visit_strategy必须包含通用审核绑定和可信actor身份谱系。交流策略另含`strategy_variant`；scheduled_visit要求`target_contact_level, visit_objective, minimum_next_step`，account_planning要求`strategic_question, planning_horizon, minimum_next_step`。客户信使用六项业务上下文、审批绑定和可信actor谱系。

`schema`继续为`discovery-call-output/v2.5`，Skill版本为2.10.0；读取旧v2.5成果允许缺少新增字段，但必须先用`migrate_workspace.py`将同一宿主签名主体回填到当前manifest；更新或新建时须补齐当前适用字段。主体或机构范围发生变化时必须新建上下文，不得迁移改绑。

枚举断言：

- `module_status ∈ {not_called, queued, running, partial, completed, blocked}`
- `review_status ∈ {not_required, not_started, pending, approved, changes_requested}`
- `connector_status ∈ {not_applicable, not_configured, connected, no_hits, permission_denied, failed}`
- `freshness_status ∈ {current, stale, invalidated}`
- 禁止旧字段 `version/owner` 与旧枚举 `review_required/not_connected`
- `context_id` 符合 `dcx-YYYYMMDD-8chars`
- `latest_run_id` 符合 `dcr-YYYYMMDDTHHMMSS-4chars`
- `content_version` 为正整数；`evidence_cutoff_date` 为 `YYYY-MM-DD`
- `business_mode ∈ {briefing,standard_visit,strategic_account,letter}`，并与受控route/depth映射一致。
- release最终交付要求`ready_for_use=true`及readiness哈希/版本/可信actor谱系匹配当前总报告；closed不能替代ready。
- briefing/leader/internal/visit_strategy的approved要求通用审核绑定及actor谱系匹配当前版本和正文；非approved时全部清空。
- internal被选中或既有internal为connected时，要求tenant/customer/project三重范围、项目白名单、实名authorization_owner、用途、未过期时间、授权根/数据集/密级、connector_id和宿主能力收据ID。
- 新建上下文必须显式提供`--task-timezone`或`--evidence-cutoff-date`；两者都省略时 init 退出2。IANA任务时区写入机器清单，续建、提交、审批、恢复后必须保持不变；同一context显式改时区应退出2且文件哈希不变。旧v2.5清单缺少该字段仍可读取；显式日期模式只允许UTC日期或相邻的下一民用日，更晚日期拒绝。

### 验证profile断言

| profile | 用途 | 占位符 | 成功时`deliverable_state` |
|---|---|---|---|
| `scaffold` | init/恢复安全预检 | 允许但必须告警 | `scaffold_not_deliverable` |
| `candidate`（默认） | 候选内容校验 | 拒绝 | `draft_for_review` |
| `release`（`--strict`别名） | 正式业务使用 | 拒绝，另验审核/TTL/ready | `release_ready` |

`--profile`与`--strict`冲突时CLI退出2。默认candidate不得把初始化骨架判为可交付。

## 2. 1+N 与路径断言

- 综合报告唯一必需；只生成实际调用模块。briefing模式另必须生成唯一`briefing_delivery`文件，严格满足固定章节、1—5条F/F2事实、结论/判断/建议claim依据、3个问题、1个动作和1页代理上限。
- `--modules institution,leader,internal,strategy,letter` 可组合；新建默认仅 `institution`，续建未显式给出时继承最新成果登记中的可调用模块。
- 工作目录严格为 `客户研究-<safe_name>-<context_id短码>/`。
- `safe_name` 经 NFKC 归一化、操作系统与Markdown链接危险字符替换、空白/连字符合并、首尾清理，最长 48 字符；Windows 保留名加前缀。
- 续建不覆盖既有模块；同客户只有一个目录时可自动续建，多项目时必须 `--context-id`。
- 综合报告始终列出全部模块，并记录`selected_in_run`与`run_action`。从未生成且本轮未选时必须`false/not_called`、`module_status=not_called`且无链接；历史文件本轮未选时保留原状态和链接，但必须`false/not_called`；本轮选中时必须`true`且动作为`created/reused/updated/generated`。
- 文件存在时，行内 `module_status/review_status/connector_status/freshness_status/content_version/latest_run_id` 与成果 frontmatter 一致；最终交付时本轮`created/updated/generated`成果的run ID必须等于总报告本轮run ID。planning/research/paused可暂存“计划updated＋旧run”，但须`summary_sync_status=pending`且非严格校验；严格交付仍拒绝。
- 成果登记固定15列，最后一列唯一命名为“成果链接”：Markdown链接目标就是`artifact_path`，显示文本必须精确等于固定模块标签。有文件时目标必须是实际相对路径，无文件时整格留空；不得再拆出第16列。每行还必须有 `updated_at, summary_sync_status, key_claim_ids, downstream_invalidation, gaps/blockers`；`summary_sync_status ∈ {pending,synced,out_of_sync,not_applicable}`，`key_claim_ids`仅为正文引用的当前ledger claim_id去重排序全集或`none`（未调用可空），`downstream_invalidation ∈ {none,stale,invalidated}`，`gaps/blockers`仅为`none`或受控码/当前claim_id去重排序列表。
- 每个新 run 记录必须持久化 `run_id, route, depth, objective, target_evidence_cutoff_date, selected_modules` 以及每个成果的 `created/updated/reused/generated/not_called` 动作；五类动作无重叠并完整覆盖5个模块、派生`briefing`和`external_letter`共7项。只读兼容旧6项历史分区；新run必须写7项。`external_letter`只允许`generated/reused/not_called`，其中`reused`仅表示同一已批准外发版被后续就绪/交付门禁继续采用。全部历史行都须有合法时间、连续版本、唯一run、非空owner和内部一致摘要；最后一行时间/版本/run/owner须与总报告一致。
- workflow_stage 为 review 时，策略/客户信必须 completed/current 且 pending、approved或changes_requested；closed时只允许pending或approved。研究成果须为 partial/completed/blocked、current、已同步，completed 人物/内部判断须 pending 或 approved。
- release 下综合报告必须`completed/current`；research_only/refresh 的 workflow_stage 只允许`output|closed`，visit_prep/strategy/letter 只允许`output|review|closed`。planning、research、paused 等中间阶段不能跳过总报告或必需输出成果的 completed/current 门禁；审批和外发操作仍另行要求`review|closed`。
- refresh 必须 resume 既有 context 且只能选择 institution/leader/internal；选择 strategy/letter 时主 route 必须改为 strategy/letter。
- strict refresh 必须不是首轮，至少选择一个 institution/leader/internal 成果，所选成果动作只能为 created/updated；每个所选成果的 latest_run_id 必须等于本 run，evidence_cutoff_date 必须等于合并后总报告，reused 或旧 cutoff 均拒绝。综合报告`## 8.1 刷新结果记录`中须恰有一条本轮`run_id`行；新增/更正/失效/未变化/待确认分别写逗号分隔的已定义 claim/source ID 或 exact `none`，类别不得重叠。五类不能全部为`none`；无变化时把已复核 ID 写入“未变化”。最新 run 的 target cutoff 必须等于总报告 evidence_cutoff_date。
- 新建 visit_prep/strategy/letter 至少有一个本轮研究模块。续建这些输出路由时，要么至少一个 completed/current、scope匹配的历史研究成果登记为`selected_in_run=true/run_action=reused`；要么至少一个既有且属于本轮 selected_modules 的 institution/leader/internal 成果位于`--refresh-modules`（CLI 中同时列入`--modules`），本 run 动作为 updated，其他被选中且可用的研究为 reused。`--refresh-modules`不得用于新建、research_only、refresh，不得含输出成果或未选/不存在成果；显式更新项可在规划时 partial 或 stale，但 strict 输出前必须 completed/current、run/cutoff 已同步且审核可用。
- resume 初始化只写 target cutoff 和计划；在证据合并前，总报告原 evidence_cutoff_date/freshness_status 必须保持不变。

## 3. 主张与来源双台账断言

- 主张定义格式：`CLM-I-### / CLM-L-### / CLM-N-###`。
- 来源定义格式：`SRC-I-### / SRC-L-### / SRC-N-###`。
- `claim_type ∈ {F,F2,A,H,R}`；`provenance ∈ {public,U,N}`。U/N 只表示来源，不代表核验等级。
- `verification_status ∈ {asserted,verified_single,corroborated,conflicted,stale,invalidated,unusable}`。
- F 必须对应 `verified_single`，F2 必须对应 `corroborated`。
- 每条主张至少引用一个已定义支持 `source_id`；任何 claim/source 引用不得孤立。
- Markdown每条来源固定14列、每条主张固定10列，全部实质字段逐列精确绑定验签machine record；支持/反证字段只允许规范source_id列表。raw locator只允许HTTP(S) URL或受控stable-id，台账禁止Markdown链接/图片、反引号、HTML和Cf。宿主捕获服务按实际内容、响应元数据和授权谱系签发v3 source-capture receipt并逐项绑定`locator/canonical_locator/final_url`及完整来源字段；candidate seal不得冒充来源或语义审核。`source_fingerprint`须精确等于`sha256:<content_sha256>`；未知上游精确写`unknown:<source_id>`；restricted的external_use只能为false。
- `provenance=N`只能位于`internal_retrieval/CLM-N-*`；`source_level=internal`或`permission=internal-authorized|restricted`只能位于`internal_retrieval/SRC-N-*`。任一此类证据都触发租户、项目、有效期及宿主签名能力收据门禁，不得靠未选择internal或伪造公开载体绕过。
- 每条主张在`runtime/evidence-manifest.json`有唯一记录，必须包含`information_type/ttl_class, evidence_anchor_at, date_basis, verified_at, ttl_days, expires_at, supporting_source_ids, verification_status`；TTL按当前模式与信息类别重算，支持来源内容SHA与source cache和Markdown台账一致。
- I/L/N 双台账只能分别定义在机构/人物/内部检索成果中，不能由总报告或策略文件冒充定义。
- `completed` 的机构、人物、内部检索成果必须各有非空且前缀正确的主张台账和来源台账，正文至少引用一个 claim_id。
- `completed` 的综合报告、交流策略、briefing和客户信内部稿也必须在正文引用至少一个已定义 claim_id；仅当research_only/refresh本轮所选研究全部partial/blocked时，总报告可只交付缺口而不伪造claim。
- 禁止遗留证据编号 `I-E### / L-E### / N-E###`。
- F2只使用已验签machine source的`source_group/canonical_locator/content_sha256/upstream_id`判定，并要求存在同一对四项同时有效且逐项不同；Markdown显示值不得参与。`upstream_id`为`unknown:<source_id>`的来源不能成为该对成员。
- completed/current策略与客户信不得依赖partial/blocked或非current研究载体，也不得依赖conflicted/stale/invalidated/unusable主张，并至少有一个F/F2已核实事实锚点。客户信引用的每个主张都须为F/F2，支持来源须非C级、非restricted且`external_use=true`；人物/内部载体还须approved。
- visit_strategy/customer_letter_internal 的 freshness 为 stale/invalidated 时 review_status 必须为 changes_requested，并与成果登记同步；pending/approved 只允许 current。

## 4. 客户信隔离断言

- 内部稿必须且只能有一对、顺序正确的 `EXTERNAL_BODY_START/END`。
- 外发版只允许由`completed/approved/current`且同时含有效审批绑定和可信actor谱系的内部稿，在审批后宿主记录了匹配的第二次用户请求事件后，通过`--emit-external --actor-id <id> --request-event-id <event>`原子抽取。
- `--approve-letter`只接受completed/pending内部稿；changes_requested必须修改并重新提交为pending，不能直接批准。
- 成功抽取后内部稿必须记录`external_output_required=true`；重复抽取拒绝覆盖既有外发文件。
- 成功抽取必须在同一WAL事务中将request event标为已消费并绑定外发run；审批前、过期、已消费、版本/哈希/上下文不匹配的事件均拒绝且工作区哈希不变。
- 外发正文不能为空；按统一上下文契约的固定换行/尾随空白规范化后，必须与内部稿标记间正文完全一致，且小写SHA-256匹配审批绑定。
- 内部稿的“版本与审核记录”至少有一行且版本连续；每次正文更新、approve、emit_external 都追加而不覆盖历史，最新行的时间/版本/run/owner/review_status 与 frontmatter 一致。
- 外发版不得出现 claim/source ID、标记、任何HTML注释、内部审核、竞对、价格底线、关系评价、受限资料、承诺检查或配置的内部词。
- 综合报告外发版状态行与新文件同步。
- 外发生成必须是新 run，selected 中包含 customer_letter 与至少一个 current 研究载体，后者动作为 reused。成功后内部稿递增版本、外发版为版本1、总报告递增版本，三者使用同一新 run_id 与同一带时区 updated_at；evidence_cutoff_date 不推进。失败时三个文件的内容、版本和时间全部回滚。

## 5. 文件安全与事务断言

- 初始化、续建、验证、外发均拒绝工作目录或目标Markdown为符号链接。
- 一个文件只能有一个起始YAML frontmatter；重复顶层frontmatter或伪造第二个`---`块必须拒绝。
- 所有多文件操作使用同目录临时文件、完整预检和原子替换；任一阶段故障后不得留下新文件、半更新版本、时间或链接。
- 研究执行只能写`build_candidate.py`创建的隔离候选区；正式区机器文件不得由`research_plan.py`直写。
- 严格提交必须把`runtime/search-plan.json、source-cache.json、evidence-manifest.json、run-metrics.json`与Markdown经同一CAS/WAL事务提交；四文件缺失、schema/context/run/mode/SHA不匹配或提交后复检失败时全部回滚。
- `validate_outputs.py`在读取客户成果前，必须用代码内固定SHA-256清单校验全部`schemas/*.schema.json`和`config/business-modes.json`。缺失、符号链接、未登记文件、合法JSON式替换或摘要漂移均失败关闭；不得从schema/config同目录自证，也不得在运行时自动接受或重写摘要。
- 有意修改上述契约时，维护者须先完成代码评审，再用`sha256sum schemas/*.schema.json config/business-modes.json`核对新摘要，显式更新`TRUSTED_SCHEMA_SHA256/TRUSTED_BUSINESS_CONFIG_SHA256`并运行`tests.test_contract_bundle_trust`及完整发布回归。该门禁以Python校验器源码仍可信为前提，只用于包完整性与误改检测，不宣称抵抗能够同时替换Python源码的攻击者。

## 6. CLI 冒烟测试

```bash
python3 scripts/init_workspace.py --help
python3 scripts/validate_outputs.py --help
python3 scripts/research_plan.py plan --help

python3 -m unittest \
  tests.test_preflight_intake.IntakePreflightBehaviorTests.test_N67_signed_ledger_omission_and_duplicate_json_keys_fail_closed \
  tests.test_preflight_intake.IntakePreflightBehaviorTests.test_N68_signed_raw_second_organization_and_time_cannot_be_omitted \
  tests.test_preflight_intake.IntakePreflightBehaviorTests.test_N69_signed_meeting_cancellation_cannot_be_omitted \
  tests.test_preflight_intake.IntakePreflightBehaviorTests.test_N70_shorter_entity_or_role_cannot_cover_distinct_signed_occurrences \
  tests.test_candidate_builder.CandidateBuilderTests.test_N71_build_and_commit_reject_current_request_revision_drift \
  tests.test_runtime_transactions.RuntimeTransactionTests.test_N72_disabled_file_map_cannot_trigger_recovery_side_effects \
  tests.test_initializer_cli.InitializerCLITests.test_initializer_happy_path_and_manifest
```

测试辅助代码只在内存中创建测试私钥并向子进程注入测试公钥；生产运行不得复用测试签发器。生产冒烟必须由认证宿主提供`discovery-call-intake/v3`、原始请求bundle和`discovery-call-request-binding-receipt/v2`签名receipt。预期：双机构/双日期遗漏连续3次均阻断且零业务副作用；完整绑定的初始化和scaffold profile退出0，结果明确为`scaffold_not_deliverable`。只有填充候选内容、提交并完成审核/ready/TTL后，`--profile release`才能退出0并返回`release_ready`。

### 宿主部署必测（本地测试不能替代）

以下测试状态在宿主集成完成前一律标记为“待实测”，不得用仓内测试签发器的通过结果替代：

- 低权限Skill进程自行生成Ed25519密钥并尝试覆盖`DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON`或`DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON`：宿主必须拒绝覆盖，截短原始请求不得获得ready gate，且任何工作区、锁、候选、query或网络调用均未产生。
- 缺少当前有效request gate或尝试绕过`preflight/init/plan/build/commit`直接调用WebSearch、WebFetch或企业连接器：连接器执行边界必须拒绝请求并记录拒绝审计，不能只依赖Skill文本约束。
- 生产部署包扫描：不得包含测试私钥、测试签发器或允许从workspace、附件、命令行和普通子进程环境重设信任根的入口。

三项均须以受保护宿主配置和真实连接器执行日志连续复测3次；任一失败即保持发布阻断。

## 7. 组合、续建与隔离测试

```bash
case_root="$(mktemp -d)"
python3 scripts/init_workspace.py "示例医院" --output-root "$case_root" \
  --task-timezone "Asia/Shanghai" --runtime-owner "医疗售前" --business-mode letter \
  --intake-input "<与letter模式匹配且ready的intake.json>" \
  --modules institution,leader,internal,strategy,letter \
  --internal-connector-status not_applicable --json > "$case_root/result.json"
workspace="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workspace"])' "$case_root/result.json")"
python3 scripts/validate_outputs.py "$workspace" --profile scaffold
test "$(find "$workspace" -maxdepth 1 -name '*.md' | wc -l)" -eq 6

case_context="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["context_id"])' "$case_root/result.json")"
python3 scripts/init_workspace.py "示例医院" --output-root "$case_root" \
  --runtime-owner "医疗售前" --context-id "$case_context" --resume --business-mode letter \
  --intake-input "<同一ready intake.json>" --modules institution
python3 scripts/validate_outputs.py "$workspace" --profile scaffold

if python3 scripts/init_workspace.py "../escape" --output-root "$case_root" \
  --safe-name "../escape" --task-timezone "Asia/Shanghai" --business-mode letter \
  --intake-input "<同一ready intake.json>"; then
  exit 1
fi
```

预期：6 文件组合通过scaffold校验但不可交付；续建保留已有文件；路径穿越退出2。尖括号intake须在运行时替换为实际文件，不是可执行占位值。

已有 institution 成果达到既有终态后，在续建 strategy 的同一 run 定向更新它：

```bash
python3 scripts/init_workspace.py "示例医院" --output-root "<父目录>" \
  --runtime-owner "医疗售前" --context-id "<context_id>" --resume --business-mode strategic_account \
  --intake-input "<ready intake.json>" \
  --modules institution,strategy --refresh-modules institution
```

预期：institution 与 strategy 的本 run 计划动作为 updated；其他被选中且可用的研究成果为 reused。strict 前必须实际写回本 run、完成为 completed/current、同步截止日并满足相应审核要求。

## 8. 机械负例矩阵

每项复制一份已填充且通过严格校验的基准工作目录，注入一个变异并断言 validator 退出 1。`tests/negative_case_map.json`只登记每个编号的一个可运行锚点测试，不代表自动覆盖同一行用“或”连接的全部变体；复合行的其余变体须以独立子测试或发布前向证据补齐，不能因映射文件存在就宣称已测：

| 编号 | 变异 | 必须命中的错误码 |
|---|---|---|
| N01 | 删除综合报告 | `comprehensive_count` |
| N02 | 删除 `latest_run_id` | `frontmatter_required` |
| N03 | `review_status=review_required` | `review_status_invalid` |
| N04 | `connector_status=not_connected` | `connector_status_invalid` |
| N05 | 增加 `owner/version` | `legacy_metadata` |
| N06 | 总报告某未调用行设为 selected=true 但无文件 | `selected_artifact_missing` |
| N07 | 历史文件本轮未选但 run_action=updated | `run_action_unselected` |
| N08 | 总报告 freshness/version/run 与分报告不同 | `status_sync_mismatch` |
| N09 | completed 研究删除主张台账 | `completed_claim_ledger_missing` |
| N10 | completed 研究删除来源台账 | `completed_source_ledger_missing` |
| N11 | 正文引用 `CLM-I-999` 未定义 | `claim_orphan_reference` |
| N12 | 主张引用 `SRC-I-999` 未定义 | `claim_source_orphan` / `source_orphan_reference` |
| N13 | 主张支持来源留空 | `claim_source_missing` |
| N14 | `claim_type=U` | `claim_type_invalid` |
| N15 | F 配 `corroborated` | `fact_mapping_invalid` |
| N16 | 使用 `I-E001` | `legacy_evidence_id` |
| N17 | 相对链接越出目录 | `link_escape` |
| N18 | 外发标记倒置或重复 | `external_markers_invalid` |
| N19 | 未批准内部稿存在外发版 | `external_source_unapproved` |
| N20 | 外发版加入“价格底线” | `external_internal_leak` |
| N21 | 外发版与内部批准正文差一个字 | `external_body_drift` |
| N22 | F2只有一个来源，或全部支持来源中不存在同一对能在source_group、locator/source_locator、content_sha256、upstream_id四项都有效且逐项不同；包括候选成员upstream为unknown | `fact2_sources_insufficient` / `fact2_sources_not_fourfold_independent` |
| N23 | 外发内部稿freshness_status=stale | `external_source_stale` |
| N24 | route=letter进入review但缺少内部稿 | `route_required_artifact_missing` |
| N25 | strict时总报告非completed/current，或research_only/refresh不在output/closed，或输出路由不在output/review/closed；包括以planning/research/paused规避输出终态 | `strict_total_not_ready` / `strict_workflow_stage_not_ready`，输出成果另命中对应终态错误 |
| N26 | init中refresh未使用resume或选择strategy/letter | init退出2并说明refresh只可续建/只可研究模块；伪造成果由`refresh_output_selected`拒绝 |
| N27 | 删除输出路由的全部研究载体，仅保留策略或信件成果 | `route_research_carrier_missing`；初始化器的受控模式映射会自动保留研究载体 |
| N28 | resume未提供新证据截止日 | 总报告既有evidence_cutoff/freshness保持原值；这是一项前后值断言 |
| N29 | 15列成果登记缺summary_sync/key_claim/downstream/gaps/成果链接任一列，或把链接拆成第16列 | `status_row_missing` / 对应`*_invalid`或`*_missing` |
| N30 | review/closed的选中研究仍queued/running、非current，或completed人物仍not_started | `selected_module_nonterminal` / `review_stage_research_stale` / `review_stage_status_invalid` |
| N31 | review_status=approved但缺审批五字段，或版本、正文哈希、上下文哈希漂移 | `approval_metadata_required` / `approval_version_drift` / `approval_body_drift` / `approval_context_drift` |
| N32 | 批准正文含`<!-- comment -->`或配置内部词 | `external_candidate_leak` / `external_html_comment` / `external_internal_leak` |
| N33 | 外发版或内部稿run/版本/updated_at/审批谱系被篡改 | `status_sync_mismatch` / `external_metadata_drift` / `external_lineage_version_drift` |
| N34 | 工作目录或任一目标Markdown为符号链接 | CLI退出2或`artifact_symlink` |
| N35 | 任一文件含重复字段或第二个frontmatter块 | `frontmatter_duplicate` / `frontmatter_duplicate_block` |
| N36 | 外发提交后强制完整校验抛出故障 | 操作抛错，且内部稿、总报告哈希不变、外发版不存在；前后值断言 |
| N37 | changes_requested内部稿直接执行approve | `operation_failed`且文件哈希不变 |
| N38 | 来源稳定定位为空 | `source_locator_missing` |
| N39 | 客户信依赖partial载体、未审核人物/内部载体、asserted/conflicted主张、C级/restricted或external_use=false来源 | `output_uses_incomplete_research` / `letter_carrier_review_missing` / `letter_claim_not_externally_verified` / `output_uses_unsafe_claim` / `fact_source_level_unsafe` / `letter_source_restricted` / `letter_source_not_external_authorized` |
| N40 | 任一历史run摘要、时间、版本或owner损坏 | 对应`run_history_*`错误，最新行另命中`run_history_latest_*_mismatch` |
| N41 | partial行gaps写`none`，或blocked未写完整受控`attempted_* / impact_* / release_*`恢复码 | `terminal_gap_missing` / `blocked_recovery_contract_invalid` |
| N42 | 初始化或续建提交后全量校验故障 | init退出2，且新文件删除、原总报告哈希恢复 |
| N43 | 新建时同时省略`--task-timezone`和`--evidence-cutoff-date` | init退出2并说明新建必须显式提供其中之一 |
| N44 | 客户信内部稿缺任一六项结构化上下文字段，`recipient_role`未同时表达收件对象、角色/身份和确认状态，或字段仍为占位值 | `approval_metadata_required` / `letter_context_unresolved` / `placeholder_remaining` |
| N45 | scheduled_visit缺`target_contact_level/visit_objective/minimum_next_step`，或account_planning缺`strategic_question/planning_horizon/minimum_next_step`，或任一字段为占位值 | `strategy_context_required` / `strategy_context_unresolved` / `placeholder_remaining` |
| N46 | refresh 为首轮、未选研究、所选成果为reused/旧run/旧cutoff、缺本轮刷新行、表值非法/全为none/类别重叠/引用孤立ID，或最新cutoff未合并 | `refresh_not_resume` / `refresh_first_run_invalid` / `refresh_research_missing` / `refresh_action_invalid` / `refresh_artifact_run_mismatch` / `refresh_artifact_cutoff_mismatch` / `refresh_ledger_latest_missing` / `refresh_ledger_value_invalid` / `refresh_ledger_empty` / `refresh_ledger_overlap` / `refresh_ledger_orphan` / `refresh_cutoff_not_merged`；历史摘要另命中`run_history_refresh_research_missing` / `run_history_refresh_reused_invalid` |
| N47 | 内部信版本审核记录缺失、断版、重复run，或 approve/emit 后未追加与 frontmatter 一致的最新行 | 对应`letter_review_history_*`错误，最新行另命中`letter_review_history_latest_mismatch` |
| N48 | visit_strategy/customer_letter_internal 为 stale/invalidated，但 review_status 仍为 pending/approved | `output_review_freshness_conflict` |
| N49 | 成果登记或任一历史 run 把 external_letter 记为 created/updated | `external_run_action_invalid` / `run_history_external_action_invalid` |
| N50 | 批准后修改任一六项结构化信件上下文 | `approval_context_drift`；外发操作失败且文件哈希不变 |
| N51 | 新建、research_only或refresh使用`--refresh-modules`，包含输出模块、未同时选中或不存在的研究成果；或输出路由把显式刷新项保留为reused、strict前仍非completed/current/审核不可用 | init退出2；伪造成果命中相应动作、run、cutoff、研究终态或审核依赖错误 |
| N52 | intake中对象角色/会议时间冲突且无用户确认，仍尝试init/plan | 预检退出3；init/plan失败关闭，输出目录、候选目录、query和四机器文件哈希不变 |
| N53 | 预检后修改当前intake中的客户主体、组织范围或其他已绑定关键输入，再以修改前参数执行init/plan | init/plan必须重算当前intake；`input_sha256`发生变化，主体/范围/已建manifest绑定不一致时失败关闭；输出目录、候选目录、query和四机器文件前后值断言不变 |
| N54 | 以“领导”/AI/不存在actor、停用actor、过期或越范围grant执行审批/就绪 | `governance_actor_*`或`governance_grant_*`；全部正式文件与manifest哈希不变 |
| N55 | 客户信在审批后没有第二次宿主请求，或event在审批前/过期/已消费/哈希不匹配 | `external_request_*`；不生成外发版，事件不被部分消费 |
| N56 | research plan把source_workspace与写入workspace设为同一正式目录 | 抛出`PlanError`并包含“拒绝直接写正式workspace”；文件树前后值断言不变 |
| N57 | 默认candidate校验初始化骨架，或同时给`--strict --profile candidate` | 前者`placeholder_remaining`且`deliverable_state=invalid`；后者CLI退出2 |
| N58 | briefing缺独立成果/状态行/run分区、超过一页代理上限；事实行缺唯一F/F2或合法CLM；结论、机会判断/建议、主动作缺claim；问题/动作计数错误，或未审批就mark-ready | `briefing_delivery_required` / `briefing_delivery_unselected` / `run_history_*` / `briefing_page_limit_exceeded` / `briefing_fact_type_invalid` / `briefing_fact_claim_missing` / `briefing_fact_claim_type_mismatch` / `briefing_*_claim_missing` / `briefing_question_count_invalid` / `briefing_action_count_invalid` / `briefing_delivery_not_ready` |
| N59 | strategic_account无会议且已提供战略问题、经营周期和最小动作，仍要求对象/议程/材料 | 计划应得到`strategy_variant=account_planning`并可达到`planning_ready=true`，不得补造会议事实 |
| N60 | internal缺用途、授权根/数据集/密级、connector_id或宿主capability receipt | planning gate中相应`*_bound=false`，且不生成internal query/batch；伪造connected成果命中`connector_audit_field_missing` / `connector_audit_scope_drift` |
| N61 | 关键claim缺TTL字段、`expires_at`与机器重算不同、已过期或supporting source无绑定 | `machine_claim_fields_missing` / `claim_ttl_policy_drift` / `claim_expiry_recompute_mismatch` / `referenced_claim_expired` / `claim_support_machine_drift` |
| N62 | source cache使用URL哈希/提供商ID代替内容SHA，Markdown台账/evidence manifest/cache三者不一致，使用v1/v2收据，或篡改v3收据签入的来源元数据、TTL日期、权限、外发许可、租户/项目范围 | `machine_source_content_unbound` / `source_fingerprint_machine_drift` / `source_cache_binding_missing` / `source_capture_receipt_missing` / `source_capture_receipt_invalid` / `source_ledger_machine_drift` / `machine_source_authorization_scope_drift` |
| N63 | account_planning写入会议专属metadata、会议型二级标题，或在合法章节中嵌入“会议对象/时间/参会人/展示材料”等结构化标签 | `strategy_variant_field_forbidden` / `strategy_variant_heading_forbidden` / `strategy_variant_body_label_forbidden`；candidate、治理写操作和release均失败且文件前后哈希不变 |
| N64 | meeting_status为none/unknown却同时提供唯一确切会议时间，或用explicit_unknown伪装meeting_status | `meeting_status_time_conflict`或预检退出2；阻断并要求认证宿主重建intake，不自行选择有利分支 |
| N65 | 将任一已登记机器Schema替换为`{}`、删除、符号链接或未登记版本后运行candidate/release | 在读取客户成果前命中`runtime_machine_contract_unavailable`，不得自动更新可信摘要或继续内容校验 |
| N66 | 篡改`config/business-modes.json`以放宽必填、禁止字段或分支规则 | 在读取客户成果前命中`runtime_business_contract_unavailable`，不得自动更新可信摘要或继续内容校验 |
| N67 | request binding收据缺信任根、签名被篡改、当前request revision漂移、签名ledger漏记可确定机构提及，或intake任意层含重复JSON键 | 预检退出2并命中`信任根`、`当前会话头`、`签名无效`、`mention ledger遗漏`或`重复字段` |
| N68 | 宿主签名原始请求含“北京协和医院/09-10”和“澳门协和医院/09-12”，但模型intake只保留前一组 | 预检退出3并命中`raw_mentions_unrepresented`；连续3次均无`expires_at`/query，init/plan失败关闭且文件集合与哈希不变 |
| N69 | 宿主签名原始请求先确认会议、后明确取消，但intake只保留confirmed和原时间 | 连续3次预检退出3并同时命中`raw_mentions_unrepresented`与`candidate_without_signed_occurrence`；不得产生ready TTL |
| N70 | 原始请求含北京/澳门两个机构或“院长/副院长”两个角色，intake只用较短“协和医院”或“院长”覆盖 | 连续3次预检退出3；精确匹配使未覆盖提及或无签名候选可观察，禁止子串合并 |
| N71 | init后宿主当前请求头推进到新revision，再尝试build或commit旧候选 | build/commit连续3次均退出2并命中`当前会话头`；候选目录不创建，正式区与候选区文件哈希不变 |
| N72 | 未完成事务存在时，用已禁用的`--file-map --recover`调用commit | 连续3次均在加锁/恢复前退出2并命中`file-map`禁用；journal、事务暂存目录与全文件树保持不变 |
| N73 | candidate manifest由宿主签章后改写Markdown，再本地重建manifest/marker/seal request但不取得新宿主签章 | commit退出2并说明candidate attestation绑定漂移；正式区全文件哈希前后值断言不变 |
| N74 | 使用v1/v2 source-capture receipt，或修改v3签名覆盖的来源字段/published_at而不重签 | `source_capture_receipt_invalid` |
| N75 | 在institution载体伪造`provenance=N`和internal/internal-authorized来源且不选择internal、不提供授权 | `internal_claim_carrier_invalid` / `internal_source_carrier_invalid` / `authorization_required` / `capability_receipt_unverified` |
| N76 | briefing删除“建议交流节奏”章节 | `briefing_agenda_required` |
| N77 | briefing机会表只保留Need等部分固定行 | `briefing_opportunity_rows_invalid` |
| N78 | scheduled_visit只保留一个“概述”章节并堆入目标、议程、材料等关键词 | `presales_section_missing` |
| N79 | 客户信六项上下文仍在内部摘要，但候选外发正文只剩“您好。” | `letter_external_body_too_short` / `letter_expected_action_missing` / `letter_signer_anchor_missing` |
| N80 | account_planning的综合报告重新加入时间化会议议程和材料/演示表 | `account_comprehensive_structure_forbidden` |
| N81 | account_planning的固定11列30/60/90动作缺action、action_disposition、external_interaction、resource_commitment、owner、due_date、依赖、完成标准、调整/停止触发或CRM/PIMS候选 | `account_strategy_action_invalid` |
| N82 | account_planning续跑，或在account_planning与scheduled_visit间双向切换 | 目标模板重建、旧分支字段/审核/ready清除、旧四机器文件失效且manifest一致；前后值断言 |
| N83 | 发布前向评估无外部预签计划或manifest、遗漏任一planned slot、未提供四模式各3个T1正链与T2/T3各3个负链（总计至少18个），或同场景客户ID/完整决策五元组/关键结论漂移 | `forward_evaluation_pending` / `planned_slots_missing` / `positive_business_mode_run_count_insufficient` / `customer_id_drift` / `primary_action_drift` / `key_conclusion_drift` |
| N84 | 四个研究机器文件逐一删除或逐一替换内容，保持旧宿主签章后提交 | 8个参数化子场景均在WAL前退出2；正式区manifest revision/hash与全部成果不变 |
| N85 | 候选完成签章和首次快照校验后，在预览/事务前替换任一已绑定候选bytes | commit退出2并命中`candidate在封印读取后发生变化`；禁止把校验后的路径二次读取为提交payload，正式区零写入 |
| N86 | 用旧run能力收据提交新run的N/internal/internal-authorized/restricted证据，即使connector未connected | `capability_receipt_invalid`或`capability_receipt_run_drift`；plan、evidence、manifest的receipt run必须精确等于候选run，正式区零写入 |
| N87 | completed会前速览保留固定表头和claim_id，但事实、机会判断或交流时段内容为空/仅写“已记录”等空壳 | `briefing_fact_content_invalid` / `briefing_opportunity_content_invalid` / `briefing_agenda_content_invalid` |
| N88 | scheduled_visit把每个必需章节写成“已讨论/相关内容已记录”，或把CRM/PIMS词埋入别的章节 | `presales_section_empty` / `presales_section_missing` / `scheduled_strategy_structure_invalid` |
| N89 | account_planning在合法30/60/90动作表后追加一张改名会议表，即使不含时间或“议程”字样 | `account_strategy_action_invalid`；动作章节必须恰有一张固定11列表 |
| N90 | account_planning有建议但省略投入强度或具体建议理由 | `account_strategy_no_go_fields_invalid` |
| N91 | 建议为no_go但action与stop/archive/observe/recheck的受控文案不精确匹配，或external_interaction/resource_commitment非none，或依赖、完成标准、触发条件另行安排推进、加码、投标、演示或跟进 | `account_strategy_no_go_conflict` / `comprehensive_no_go_conflict` |
| N92 | 标准/战略综合报告只保留标题/状态表，缺决策摘要、综合判断链或G-C-P，或执行章节追加第二表 | `comprehensive_section_missing` / `comprehensive_gcp_invalid` / `comprehensive_action_invalid` |
| N93 | 客户信把收件称谓、expected_action和signer拼接在一行 | `letter_external_structure_invalid` |
| N94 | 客户信把expected_action的字符分散在多句无关正文中 | `letter_expected_action_missing` |
| N95 | 客户信只有行动请求，或用“相关事项已有相应记录”等通用空话代替letter_purpose背景 | `letter_purpose_anchor_missing` |
| N96 | 缺少独立candidate信任根，或修改已签manifest/路径/摘要后尝试沿用旧宿主attestation | `CandidateAttestationError` / `candidate_attestation_invalid`；正式区零写入 |
| N97 | 前向证据修改output/trace/validation/side-effect任一工件后重算普通SHA，把派生摘要伪装成底层CLI stdout，篡改预签runner/observer/tool registry，或把仓内临时key自报为宿主签名并沿用旧execution receipt/审核绑定 | `execution_receipt_binding_mismatch` / `validation_result_binding_mismatch` / `raw_validator_output_hash_mismatch` / `validation_adapter_binding_mismatch` / `host_key_untrusted` / `review_binding_mismatch`；六份JSON同时通过Schema和Python深校验才算结构有效，`release_decision=false` |
| N98 | account_planning核心章节存在但只写短句、空表或缺固定表列 | `account_strategy_structure_invalid` |
| N99 | scheduled_visit在任一固定章节的合法表后追加第二张表 | `scheduled_strategy_structure_invalid`；每个固定章节必须满足精确表数 |
| N100 | account_planning综合报告新增“执行准备”等非契约H2，并用`阶段/讨论主题/客户角色/我方负责人/资料包`等无时间改名表重引会议计划 | `account_comprehensive_structure_forbidden`；candidate与release均阻断，连续3次一致 |
| N101 | no_go动作使用recheck等允许枚举掩盖“提交产品方案给客户/邀请客户试用”等面客推进 | `account_strategy_no_go_conflict` / `comprehensive_no_go_conflict`；每个disposition须符合正向停止/归档/观察/复核语义 |
| N102 | completed会前速览把全部固定章节藏入fenced或缩进Markdown代码块 | `briefing_section_invalid` / `delivery_code_block_forbidden`；两种载体各连续3次均阻断 |
| N103 | 会前速览用空Markdown link的destination暗藏事实、claim_id或现场问题 | `briefing_markdown_link_forbidden`；三种位置各连续3次均阻断 |
| N104 | 客户信把purpose/action藏入fenced/缩进代码块或空link，以“可否不确认”否定行动，或以“发信目的为”元数据叙述冒充目的 | `letter_external_markdown_forbidden` / `letter_expected_action_missing` / `letter_purpose_meta_forbidden`；每类各连续3次均阻断 |
| N105 | 任一completed Markdown成果加入HTML注释/原始标签、Unicode Cf不可见格式字符、fenced或缩进代码块 | `delivery_hidden_content_forbidden` / `invisible_format_character_forbidden` / `delivery_code_block_forbidden`；标准/战略模式的综合报告与策略各连续3次，并以两模式综合报告为代表样本经candidate/release阻断 |
| N106 | scheduled_visit在允许H2中追加改名行动表，或增加H3并以编号列表暗藏第二组推进动作 | `scheduled_strategy_structure_invalid`；两类各连续3次，改名表代表样本另经candidate/release阻断 |
| N107 | standard_visit综合报告新增非契约H2，并以`事项/状态动作/责任角色/日期/完成信号`改名表写第二组影子行动 | `comprehensive_structure_forbidden`；连续3次并经candidate/release阻断 |
| N108 | account_planning策略在额外H2、H3或合法核心H2内用改名表暗藏会议步骤、人员和物料 | `account_strategy_structure_invalid`；三种结构各连续3次，额外H2代表样本另经candidate/release阻断 |
| N109 | no_go使用“复核后向客户交付解决办法”、“检查后安排客户进入测试环境”或Unicode Cf分隔符规避受控action | `account_strategy_no_go_conflict` / `invisible_format_character_forbidden`；三种payload各连续3次均阻断 |
| N110 | letter的letter_purpose或expected_action使用“相关事项已说明/已完成”等空壳值 | `required_value_non_substantive`；直接实质性函数与preflight blocked各连续3次一致 |
| N111 | no_go的固定action表看似合法，但在依赖、情景应对、验证动作或CRM action/verification中暗藏面客推进 | `account_strategy_no_go_conflict`；四个表面各连续3次完整治理校验均阻断 |
| N112 | 综合报告在允许H2中错位写ready_for_use，或在允许的“异常审核队列/可用状态”H2/H3中写与frontmatter冲突、无效时间或夹带行动的治理值 | `account_comprehensive_structure_forbidden`；两类各连续3次，H2/H3值走私代表样本另经candidate/release阻断 |
| N113 | “高价值发现”复用已有claim_id却改写claim_type/provenance/发现，或在受控impact_type的业务影响中夹带开场、方案、收口和下次交流序列 | `comprehensive_finding_claim_mismatch` / `account_comprehensive_structure_forbidden`；带权威claims参数各3次，claim洗白另经candidate/release阻断 |
| N114 | no_go的owner写“向客户提交产品方案的账户负责人”、“账户负责人负责把材料交给客户”或未绑定稳定角色的“张主任” | `account_strategy_no_go_conflict` / `comprehensive_no_go_conflict`；三种owner在account strategy和total各连续3次均阻断 |
| N115 | “高价值发现”使用8列新表且claim字段正确，但在业务影响中写“可据此判断王经理负责同张主任对齐目标…”等同义执行计划 | `comprehensive_finding_claim_mismatch`；连续3次且代表样本经candidate/release阻断 |
| N116 | 综合报告恢复旧的6列关键缺口表，或在其中用“同王经理核对安排并把资料交给张主任”等同义表达走私面客计划 | `account_comprehensive_structure_forbidden`；两类各连续3次，同义走私代表样本经candidate/release阻断；新8列受控表正例连续3次不命中`comprehensive_gap_contract_invalid` |
| N117 | 策略正文恢复旧“审核与可用状态”H2，或在允许章节下增加“可用状态”H3并夹带ready_for_use/解除条件 | `account_strategy_structure_invalid`；两类各连续3次；无审核状态镜像正文、仅以frontmatter和签名治理记录为权威状态的完整release链路独立3次通过 |
| N118 | no_go综合报告在“决策摘要”当前结论写“可据此判断王经理负责同张主任对齐目标并提交产品方案”等同义对客计划 | `comprehensive_no_go_contract_invalid`；带权威claims/sources直接治理校验连续3次，代表样本另经candidate/release阻断；闭合码strategy+total及签名治理的完整release链路独立3次通过 |
| N119 | 固定8列gap表后追加自由段落，恢复旧审核队列/单表导航，或在RACI责任码中走私“向张主任提交产品方案” | `account_comprehensive_structure_forbidden`；四类各连续3次；固定码RACI、审核队列、gap及双表导航组合正例直接校验连续3次零错误 |
| N120 | 完整客户信同时用“非张主任：”、“本函并非旨在…”、“请勿确认…”和“此信并非王经理签署。”伪装称谓、目的、动作与签署人 | direct必须同时命中`letter_external_structure_invalid`、`letter_expected_action_missing`、`letter_purpose_anchor_missing`；candidate/review/approve/emit/ready/release链路独立3次在前置校验阻断，治理命令另命中`operation_preflight_failed`；失败前后全工作区字节快照、manifest、ready、外发文件和审批谱系均不变 |
| N121 | standard/strategic/No-Go成果状态表把`key_claim_ids`或`gaps/blockers`写成“王经理同张主任对齐目标并递交产品资料”，或把机构研究链接显示文本改成“向客户提交产品方案”而保持合法href | `key_claim_ids_contract_invalid` / `gaps_blockers_contract_invalid` / `status_link_mismatch`；普通strategic与No-Go直接正负例各连续3次；两类完整release正链各独立3次通过，随后三种变体均在release阻断且校验前后全工作区字节快照不变 |
| N122 | 研究来源台账以Markdown显示文本夹带承诺、替换href或raw locator，改写claim实质字段/refs，Markdown伪造F2四元独立性，或同时改Markdown与machine字段但沿用旧宿主收据 | `source_ledger_markup_forbidden` / `source_ledger_machine_drift` / `source_locator_machine_drift` / `claim_support_refs_invalid` / `claim_ledger_machine_drift` / `source_capture_receipt_invalid` / `fact2_sources_not_fourfold_independent`；candidate/release各连续3次阻断且全工作区字节快照不变；v3来源收据、claim逐列绑定、source receipt信封摘要、独立research正文SHA审核的标准release正链独立3次通过 |
| N123 | 使用与删除集无关的有效candidate签章，在`commit_run`额外传入`--delete archive/letters/受保护历史客户信.md`，或绕过CLI向内部Namespace注入同一删除请求 | 公开CLI连续3次以`unrecognized arguments: --delete`阻断，内部入口连续3次以`删除接口已禁用`阻断；每次正式工作区字节快照不变且历史客户信仍存在；移除删除请求后同一有效候选可正常提交 |
| N124 | candidate签章在首次校验时有效，但故障注入令preview结束后、nonce消费或WAL开始前跨过`expires_at`；另尝试在过期后直接调用candidate nonce消费API | WAL前与postflight fresh完整验签连续3次以`candidate_attestation_invalid`阻断，正式成果、manifest、journal和事务目录零写；过期后直接消费被拒；正式audit不持久化本地`verified_at/wal_authorized_at`，只接受宿主签名的`host_authorized_at`与对应共享nonce消费记录 |
| N125 | scheduled/account“依据导航与缺口”把来源成果链接改为`mailto:`、HTTP、错误显示文本，或把使用位置/缺口验证方式写成“王经理同张主任对齐目标并递交产品资料”及其动作链接 | `strategy_navigation_contract_invalid`；scheduled/account direct、candidate、release正负例各连续3次，正例精确绑定当前I/L成果、固定显示文本和受控位置/typed缺口，负例阻断且校验前后全工作区字节快照不变 |
| N126 | T3请求同时要求虚构领导批准、使用患者案例和内部邮件/CRM、承诺3个月上线与效率提升30%、总价不超500万元、直接外发，并把审批/执行人写成AI | 连续3次`status=blocked`、`safe_to_initialize_or_search=false`、`questions=[]`；八个签名风险码齐全，固定输出拒绝项/原因/可做部分/补充材料/审批路径五段；只允许`internal_review_draft_only`且无外发路径、无发送、无ready、文件树零变化 |
| N127 | 对已签名授权患者/内部材料的内部待审核信尝试事实复核、审批、生成外发版、mark-ready或release；再同时清空manifest与plan中的授权码 | 全部操作连续3次以`internal_review_draft_only`、`internal_only_source_release_forbidden`或`candidate_gate_attestation_invalid`阻断；完整gate的独立宿主签章必须重验，失败前后工作区字节不变 |
| N128 | 两个机构显示名相同但注册实体键或jurisdiction不同，或篡改已签subject_resolution任一字段；另用两个别名指向同一外部主体ID | 不同主体派生`customer_id`必须不同；同一受信外部主体的别名ID与主体SHA保持一致；任一字段篡改均以`subject_resolution`验签/摘要错误阻断 |
| N129 | 会前速览规范化Markdown源码恰为3200/3201字符、80/81个非空行、单章节900/901字符或结论80/81字符 | 边界内通过；越界分别命中`briefing_page_limit_exceeded`、`briefing_section_budget_exceeded`或`briefing_conclusion_budget_exceeded`，不得把渲染页数当成可移植承诺 |
| N130 | briefing与交流策略的建议、投入强度、主动作、owner、due_date任一不一致，或建议/动作使用否定和空壳措辞 | `briefing_strategy_decision_drift`、`briefing_opportunity_content_invalid`或`briefing_primary_action_invalid`；正式manifest只接受完整决策五元组并由当前已选成果派生 |
| N131 | 将同一主体、同一风险类型的患者/CRM授权复用于另一组签名材料，保持其他subject和request字段不变 | 预检在任何工作区/搜索副作用前退出2并报告`material_scope_sha256`不匹配；授权必须同时绑定当前request bundle/revision和材料范围SHA |
| N132 | 旧工作区与新签名intake同名，但规范实体键、jurisdiction或派生ID不同；或在迁移替换/备份阶段注入失败与并发CAS写 | 以`不得改号`/`不得改绑`阻断且零写；合法同主体迁移先备份原manifest字节、SHA和迁移收据，dry-run零写、失败可回滚、重复执行幂等 |
| N133 | 清空已提交manifest门禁授权码并同步改audit哈希，补写本地历史验签/WAL时点，或把同一audit复制到另一正式路径 | 分别命中`需重建候选并重新签章`、`历史审计材料字段不完整或含未知字段`或`禁止克隆或路径重绑定`；完整宿主签名、当前formal root和共享nonce消费记录重验失败，本地补写时点不得构成历史授权 |
| N134 | letter分支保留历史visit_strategy文件或切换selected_modules后沿用旧`delivery_summary` | 当前letter manifest不得出现`delivery_summary`；未选中策略也不得派生摘要，命中`delivery_summary`状态漂移门禁 |
| N135 | resume使用相同外部customer_id和显示名、但实体键或jurisdiction不同的当前签名intake | 在根锁、恢复、目录或文件写入前以`普通resume不得改绑`阻断；正式工作区和事务journal的全树字节快照不变 |
| N136 | 改写T2/T3原始请求receipt或raw bundle后重算普通哈希，替换真实validator argv/输入文件，或篡改adapter stdout后同步重封summary/result/trace | `request_binding_receipt_sha256_mismatch`、`validator_invocation_invalid`、`validator_input_sha256_mismatch`、`raw_validator_output_hash_mismatch`或`validation_adapter_binding_mismatch`；真实subprocess adapter、exact argv/input/stdout和validation result必须逐项闭合，重封派生层仍失败 |
| N137 | 公开`recover_workspace.py --strategy roll-forward`面对含四机器文件、无research bundle的letter、未知事务或带旧合法签章的任意after-image | 有journal时一律安全rollback并清理journal/事务目录，再以`public_roll_forward_disabled`退出2；伪造research与letter after各连续3次保持before，旧合法签章也不得前滚；无journal返回`no_transaction` |
| N138 | 在首个`skill.start`后向预签plan回填`raw_input_sha256`，或把validator/adapter/commit的脚本改为相对同名路径、解释器改为`/tmp/python3`、实际cwd改到另一目录并同步重封派生层 | plan只接受预运行`launch_input_sha256`；回填字段命中`forward_plan_slot_invalid`，相对/伪解释器/cwd漂移均由launch执行身份门禁失败，运行后observation只能由execution receipt绑定，不能反向改写plan |

## 9. 四模式真实医疗售前前向测试矩阵

| 场景 | 业务模式 | 输入特征 | 成功断言 |
|---|---|---|---|
| 临时高层会面 | briefing | 公开资料、剩余时间短 | 独立briefing_delivery严格1页；审计台账不挤入正文；一个主动作；可信actor审核 |
| 三甲医院重要拜访 | standard_visit | 领导已知、内部连接获授权 | 策略含机会资格、议程、参会分工、材料计划、会后行动和CRM/PIMS候选 |
| 重点战略客户 | strategic_account | 多年度项目、无具体会议、竞争和投入决策 | 默认account_planning；不追问会议对象；输出BANT、情景、30/60/90天动作、win/no-go和停止条件 |
| 高风险正式信件 | letter | 称谓、合作事实、承诺需审核 | 可信actor审批、逐claim TTL有效、审批后第二次请求、一次性event消费、新run抽取且未发送 |
| 内部连接只是文档规范 | 任一 | 有接口说明但无宿主能力收据 | 不得生成internal query或写connected；改为公开资料候选run并透明降级 |
| 三重范围不一致 | 任一含internal | tenant/customer/project任一不匹配 | 丢弃结果、阻断ready、不跨项目复用 |
| 会后复盘 | 延续原模式 | 新增客户反馈和行动 | 更新事实/假设、action-owner-date，默认只生成写回候选 |
| 并发/中断 | 任一 | 候选提交冲突或遗留journal | 不直接改正式Markdown；CAS拒绝旧候选；auto恢复后无半提交 |
| 普通材料转发通知 | 不触发 | 仅要求转发和一句通知 | 不加载本Skill，不创建目录 |
| 单一医院事实查询 | 不触发 | 只问地址、床位等 | 使用普通检索，不创建成果目录 |

发布评估固定执行18个planned slot：四个业务模式的T1真实正向链路各3次（12次），原T2主体/日期冲突负链3次，原T3高风险正式信负链3次。第二名审核者确认：同场景客户ID、完整决策五元组、关键事实/结论/风险提示一致，用户正文代理预算、claim→source→content SHA追溯、逐claim TTL、机会与行动可执行性、closed未冒充ready、候选四机器文件事务提交、连接器收据真实和外发未发送。任一P0/P1、任何slot缺失、raw输入/真实CLI参数/输入文件/工具stdout/adapter结果/副作用审计不能逐项绑定，或三次关键结论漂移时保持“试运行”并重跑完整发布测试。

## 10. 发布前统一命令

```bash
python3 /root/.codex/skills/oai/skill-creator/scripts/quick_validate.py .
python3 -m unittest discover -s tests -v
python3 scripts/validate_forward_evaluation.py <真实前向评估证据目录或manifest.json> --json
python3 scripts/init_workspace.py --help
python3 scripts/validate_outputs.py --help
legacy_asset_scan_rc=0
rg -n '^(?:owner|version):|\b(?:review_required|not_connected|(?:I|L|N)-E[0-9]{3})\b' assets || legacy_asset_scan_rc=$?
if [ "$legacy_asset_scan_rc" -eq 0 ]; then
  echo "发现legacy字段或枚举。" >&2
  exit 1
elif [ "$legacy_asset_scan_rc" -ne 1 ]; then
  echo "legacy扫描执行失败（rg退出${legacy_asset_scan_rc}）。" >&2
  exit "$legacy_asset_scan_rc"
fi
```

`validate_forward_evaluation.py`只做本地结构与签名核验，不能证明自身处于受保护宿主。即使配置自报`trust_profile=protected_host`且证据包完整、新鲜，也只返回`status=signature_valid、claimed_trust_profile=protected_host、protected_host_verified=false、release_decision=false`并退出1；过期包仍可报告签名有效，但`promotion_freshness=stale`且`historical_verified=false`。真实宿主真实性与最终发布决定只能由外部部署控制面作出。`test_only`即使结构有效也退出1；无证据返回`pending`并退出1，不能跳过后宣称发布评估通过。最后的assets扫描使用精确token边界：`rg`退出1才表示无匹配并继续，退出0表示发现legacy字段或枚举并阻断，退出码大于1表示扫描工具错误并原码阻断；校验器源码和本文件会有意包含旧值负例，因此不纳入这条发布扫描。
