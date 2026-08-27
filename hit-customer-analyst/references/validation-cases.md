# discovery-call v2.7.0 可执行验证契约

本文件同时定义静态断言、CLI 冒烟测试与真实前向测试矩阵。命令均从 Skill 根目录执行；临时目录须使用 `mktemp -d`。

## 1. 统一成果契约

每个成果 frontmatter 必须包含：

`schema, artifact_type, context_id, latest_run_id, customer_id, customer_display_name, organization_scope, safe_name, module_status, review_status, connector_status, freshness_status, content_version, evidence_cutoff_date, updated_at, runtime_owner`

综合报告还必须包含`business_mode, ready_for_use, readiness_reviewer, readiness_reviewed_at, readiness_content_version, readiness_body_sha256, tenant_id, project_id, authorization_owner, authorization_expires_at, route, depth, workflow_stage`。briefing/leader/internal/visit_strategy必须包含通用审核绑定和可信actor身份谱系。交流策略另含`strategy_variant`；scheduled_visit要求`target_contact_level, visit_objective, minimum_next_step`，account_planning要求`strategic_question, planning_horizon, minimum_next_step`。客户信使用六项业务上下文、审批绑定和可信actor谱系。

`schema`继续为`discovery-call-output/v2.5`，Skill版本为2.7.0；读取旧v2.5成果允许缺少新增字段，更新或新建时须补齐当前适用字段。

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
- 成果登记固定15列，最后一列唯一命名为“成果链接”：Markdown链接目标就是`artifact_path`，显示文本就是`link`。有文件时目标必须是实际相对路径，无文件时留空；不得再拆出第16列。每行还必须有 `updated_at, summary_sync_status, key_claim_ids, downstream_invalidation, gaps/blockers`；`summary_sync_status ∈ {pending,synced,out_of_sync,not_applicable}`，`downstream_invalidation ∈ {none,stale,invalidated}`。
- 每个新 run 记录必须持久化 `run_id, route, depth, objective, target_evidence_cutoff_date, selected_modules` 以及每个成果的 `created/updated/reused/generated/not_called` 动作；五类动作无重叠并完整覆盖5个模块、派生`briefing`和`external_letter`共7项。只读兼容旧6项历史分区；新run必须写7项。`external_letter`只允许`generated/not_called`。全部历史行都须有合法时间、连续版本、唯一run、非空owner和内部一致摘要；最后一行时间/版本/run/owner须与总报告一致。
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
- Markdown每条来源固定14列并定义非空`source_group, source_locator, source_fingerprint, upstream_id`和`external_use=true|false`；机器证据记录另含`final_url, content_sha256, retrieved_at, capture_method, length`。`source_fingerprint`须精确等于`sha256:<content_sha256>`；URL哈希、提供商ID或`scheme:stable-id`均拒绝。未知上游精确写`unknown:<source_id>`；restricted的external_use只能为false。
- 每条主张在`runtime/evidence-manifest.json`有唯一记录，必须包含`information_type/ttl_class, evidence_anchor_at, date_basis, verified_at, ttl_days, expires_at, supporting_source_ids, verification_status`；TTL按当前模式与信息类别重算，支持来源内容SHA与source cache和Markdown台账一致。
- I/L/N 双台账只能分别定义在机构/人物/内部检索成果中，不能由总报告或策略文件冒充定义。
- `completed` 的机构、人物、内部检索成果必须各有非空且前缀正确的主张台账和来源台账，正文至少引用一个 claim_id。
- `completed` 的综合报告、交流策略、briefing和客户信内部稿也必须在正文引用至少一个已定义 claim_id；仅当research_only/refresh本轮所选研究全部partial/blocked时，总报告可只交付缺口而不伪造claim。
- 禁止遗留证据编号 `I-E### / L-E### / N-E###`。
- F2 要求支持来源中存在至少一对来源：该同一对的`source_group`、`locator/source_locator`、`source_fingerprint`、`upstream_id`四项都有效且逐项不同，且指纹均与机器内容SHA绑定；`upstream_id`为`unknown:<source_id>`的来源不能成为该对成员。只有不存在这样的同一对时才拒绝 F2。
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

case_root="$(mktemp -d)"
python3 - "$case_root/intake.json" <<'PY'
import json, sys
payload = {
  "schema": "discovery-call-intake/v1",
  "request_id": "smoke-briefing-001",
  "business_mode": "briefing",
  "candidate_sets": [{
    "field": "customer_name",
    "candidates": [{"candidate_id": "customer-001", "value": "示例医院", "status": "asserted", "source_ref": "测试输入"}]
  }],
  "confirmations": []
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(payload, stream, ensure_ascii=False)
PY
python3 scripts/preflight_intake.py "$case_root/intake.json" > "$case_root/intake-gate.json"
python3 scripts/init_workspace.py "示例医院" \
  --output-root "$case_root" \
  --task-timezone "Asia/Shanghai" \
  --runtime-owner "医疗售前" \
  --business-mode briefing \
  --intake-input "$case_root/intake.json" \
  --json > "$case_root/result.json"

workspace="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["workspace"])' "$case_root/result.json")"
python3 scripts/validate_outputs.py "$workspace" --profile scaffold
if python3 scripts/validate_outputs.py "$workspace"; then
  exit 1
fi
```

预期：intake为ready；初始化和scaffold profile退出0，结果明确为`scaffold_not_deliverable`；默认candidate因占位符和未完成状态退出1。只有填充候选内容、提交并完成审核/ready/TTL后，`--profile release`才能退出0并返回`release_ready`。

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

每项复制一份已填充且通过严格校验的基准工作目录，注入一个变异并断言 validator 退出 1：

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
| N23 | 外发内部稿freshness_status=stale | `external_source_stale` / `emit_external_failed` |
| N24 | route=letter进入review但缺少内部稿 | `route_required_artifact_missing` |
| N25 | strict时总报告非completed/current，或research_only/refresh不在output/closed，或输出路由不在output/review/closed；包括以planning/research/paused规避输出终态 | `strict_total_not_ready` / `strict_workflow_stage_not_ready`，输出成果另命中对应终态错误 |
| N26 | init中refresh未使用resume或选择strategy/letter | init退出2并说明refresh只可续建/只可研究模块；伪造成果由`refresh_output_selected`拒绝 |
| N27 | 新建strategy/letter/visit_prep仅选择输出模块 | init退出2；伪造成果由`route_research_carrier_missing`拒绝 |
| N28 | resume未提供新证据截止日 | 总报告既有evidence_cutoff/freshness保持原值；这是一项前后值断言 |
| N29 | 15列成果登记缺summary_sync/key_claim/downstream/gaps/成果链接任一列，或把链接拆成第16列 | `status_row_missing` / 对应`*_invalid`或`*_missing` |
| N30 | review/closed的选中研究仍queued/running、非current，或completed人物仍not_started | `selected_module_nonterminal` / `review_stage_research_stale` / `review_stage_status_invalid` |
| N31 | review_status=approved但缺审批五字段，或版本、正文哈希、上下文哈希漂移 | `approval_metadata_required` / `approval_version_drift` / `approval_body_drift` / `approval_context_drift` |
| N32 | 批准正文含`<!-- comment -->`或配置内部词 | `external_candidate_leak` / `external_html_comment` / `external_internal_leak` |
| N33 | 外发版或内部稿run/版本/updated_at/审批谱系被篡改 | `status_sync_mismatch` / `external_metadata_drift` / `external_lineage_version_drift` |
| N34 | 工作目录或任一目标Markdown为符号链接 | CLI退出2或`artifact_symlink` |
| N35 | 任一文件含重复字段或第二个frontmatter块 | `frontmatter_duplicate` / `frontmatter_duplicate_block` |
| N36 | 外发提交后完整校验故障 | `emit_external_postflight_failed`，且三文件哈希/版本/时间与运行前一致 |
| N37 | changes_requested内部稿直接执行approve | `approve_letter_failed`且文件哈希不变 |
| N38 | 来源缺locator/group/content SHA/捕获元数据、用稳定ID或URL哈希冒充内容哈希、unknown上游或external_use无效 | `source_locator_missing` / `source_group_missing` / `source_fingerprint_invalid` / `source_cache_binding_invalid` / `source_capture_metadata_missing` / `source_upstream_unknown_invalid` / `source_external_use_invalid` |
| N39 | 客户信依赖partial载体、未审核人物/内部载体、asserted/conflicted主张、C级/restricted或external_use=false来源 | `output_uses_incomplete_research` / `letter_carrier_review_missing` / `letter_claim_not_externally_verified` / `output_uses_unsafe_claim` / `fact_source_level_unsafe` / `letter_source_restricted` / `letter_source_not_external_authorized` |
| N40 | 任一历史run摘要、时间、版本或owner损坏 | 对应`run_history_*`错误，最新行另命中`run_history_latest_*_mismatch` |
| N41 | partial行gaps写“无”，或blocked未写尝试/影响/解除条件 | `terminal_gap_missing` / `blocked_resolution_incomplete` |
| N42 | 初始化或续建提交后全量校验故障 | init退出2，且新文件删除、原总报告哈希恢复 |
| N43 | 新建时同时省略`--task-timezone`和`--evidence-cutoff-date` | init退出2并说明新建必须显式提供其中之一 |
| N44 | 客户信内部稿缺任一六项结构化上下文字段，`recipient_role`未同时表达收件对象、角色/身份和确认状态，或字段仍为占位值 | `approval_metadata_required` / `letter_context_unresolved` / `placeholder_remaining` |
| N45 | scheduled_visit缺`target_contact_level/visit_objective/minimum_next_step`，或account_planning缺`strategic_question/planning_horizon/minimum_next_step`，或任一字段为占位值 | `strategy_context_required` / `strategy_context_unresolved` / `placeholder_remaining` |
| N46 | refresh 为首轮、未选研究、所选成果为reused/旧run/旧cutoff、缺本轮刷新行、表值非法/全为none/类别重叠/引用孤立ID，或最新cutoff未合并 | `refresh_not_resume` / `refresh_first_run_invalid` / `refresh_research_missing` / `refresh_action_invalid` / `refresh_artifact_run_mismatch` / `refresh_artifact_cutoff_mismatch` / `refresh_ledger_latest_missing` / `refresh_ledger_value_invalid` / `refresh_ledger_empty` / `refresh_ledger_overlap` / `refresh_ledger_orphan` / `refresh_cutoff_not_merged`；历史摘要另命中`run_history_refresh_research_missing` / `run_history_refresh_reused_invalid` |
| N47 | 内部信版本审核记录缺失、断版、重复run，或 approve/emit 后未追加与 frontmatter 一致的最新行 | 对应`letter_review_history_*`错误，最新行另命中`letter_review_history_latest_mismatch` |
| N48 | visit_strategy/customer_letter_internal 为 stale/invalidated，但 review_status 仍为 pending/approved | `output_review_freshness_conflict` |
| N49 | 成果登记或任一历史 run 把 external_letter 记为 created/reused/updated | `external_run_action_invalid` / `run_history_external_action_invalid` |
| N50 | 批准后修改任一六项结构化信件上下文 | `approval_context_drift`；外发操作失败且文件哈希不变 |
| N51 | 新建、research_only或refresh使用`--refresh-modules`，包含输出模块、未同时选中或不存在的研究成果；或输出路由把显式刷新项保留为reused、strict前仍非completed/current/审核不可用 | init退出2；伪造成果命中相应动作、run、cutoff、研究终态或审核依赖错误 |
| N52 | intake中对象角色/会议时间冲突且无用户确认，仍尝试init/plan | 预检退出3；init/plan失败关闭，输出目录、候选目录、query和四机器文件哈希不变 |
| N53 | 预检后修改当前intake中的客户主体、组织范围或其他已绑定关键输入，再以修改前参数执行init/plan | init/plan必须重算当前intake；`input_sha256`发生变化，主体/范围/已建manifest绑定不一致时失败关闭；输出目录、候选目录、query和四机器文件前后值断言不变 |
| N54 | 以“领导”/AI/不存在actor、停用actor、过期或越范围grant执行审批/就绪 | `governance_actor_*`或`governance_grant_*`；全部正式文件与manifest哈希不变 |
| N55 | 客户信在审批后没有第二次宿主请求，或event在审批前/过期/已消费/哈希不匹配 | `external_request_*`；不生成外发版，事件不被部分消费 |
| N56 | research plan直写正式区，或提交缺任一固定runtime文件/哈希漂移 | `candidate_workspace_required` / `runtime_file_required` / `runtime_file_hash_mismatch`；CAS/WAL不产生半提交 |
| N57 | 默认candidate校验初始化骨架，或同时给`--strict --profile candidate` | 前者`placeholder_remaining`且`deliverable_state=invalid`；后者CLI退出2 |
| N58 | briefing缺独立成果/状态行/run分区、超过一页代理上限；事实行缺唯一F/F2或合法CLM；结论、机会判断/建议、主动作缺claim；问题/动作计数错误，或未审批就mark-ready | `briefing_delivery_required` / `briefing_delivery_unselected` / `run_history_*` / `briefing_page_limit_exceeded` / `briefing_fact_type_invalid` / `briefing_fact_claim_missing` / `briefing_fact_claim_type_mismatch` / `briefing_*_claim_missing` / `briefing_question_count_invalid` / `briefing_action_count_invalid` / `briefing_delivery_not_ready` |
| N59 | strategic_account无会议且已提供战略问题、经营周期和最小动作，仍要求对象/议程/材料 | 计划应得到`strategy_variant=account_planning`并可达到`planning_ready=true`，不得补造会议事实 |
| N60 | internal缺用途、授权根/数据集/密级、connector_id或宿主capability receipt | planning gate中相应`*_bound=false`，且不生成internal query/batch；伪造connected成果命中`connector_audit_field_missing` / `connector_audit_scope_drift` |
| N61 | 关键claim缺TTL字段、`expires_at`与机器重算不同、已过期或supporting source无绑定 | `machine_claim_fields_missing` / `claim_ttl_policy_drift` / `claim_expiry_recompute_mismatch` / `referenced_claim_expired` / `claim_support_machine_drift` |
| N62 | source cache使用URL哈希/提供商ID代替内容SHA，Markdown台账/evidence manifest/cache三者不一致，或缺失/篡改宿主签名source-capture receipt | `machine_source_content_unbound` / `source_fingerprint_machine_drift` / `source_cache_binding_missing` / `source_capture_receipt_missing` / `source_capture_receipt_invalid` |
| N63 | account_planning写入会议专属metadata、会议型二级标题，或在合法章节中嵌入“会议对象/时间/参会人/展示材料”等结构化标签 | `strategy_variant_field_forbidden` / `strategy_variant_heading_forbidden` / `strategy_variant_body_label_forbidden`；candidate、治理写操作和release均失败且文件前后哈希不变 |
| N64 | meeting_status为none/unknown却同时提供唯一确切会议时间，或用explicit_unknown伪装meeting_status | `meeting_status_time_conflict`或预检退出2；阻断并要求认证宿主重建intake，不自行选择有利分支 |
| N65 | 将任一已登记机器Schema替换为`{}`、删除、符号链接或未登记版本后运行candidate/release | 在读取客户成果前命中`runtime_machine_contract_unavailable`，不得自动更新可信摘要或继续内容校验 |
| N66 | 篡改`config/business-modes.json`以放宽必填、禁止字段或分支规则 | 在读取客户成果前命中`runtime_business_contract_unavailable`，不得自动更新可信摘要或继续内容校验 |

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

发布评估时，每个标准、缺失/冲突、最高风险场景同输入独立运行3次。第二名审核者确认：关键事实/结论/风险提示一致，用户正文页数、claim→source→content SHA追溯、逐claim TTL、机会与行动可执行性、closed未冒充ready、候选四机器文件事务提交、连接器收据真实和外发未发送。任一P0/P1或三次关键结论漂移时保持“试运行”并重跑完整发布测试。

## 10. 发布前统一命令

```bash
python3 /root/.codex/skills/oai/skill-creator/scripts/quick_validate.py .
python3 -m unittest discover -s tests -v
python3 scripts/init_workspace.py --help
python3 scripts/validate_outputs.py --help
rg -n '^(?:owner|version):|review_required|not_connected|(?:I|L|N)-E[0-9]{3}' assets
```

最后一条 `rg` 预期无匹配；校验器源码和本文件会有意包含旧值负例，因此不纳入这条发布扫描。
