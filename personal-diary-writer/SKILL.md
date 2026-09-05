---
name: personal-diary-writer
description: 生成并保存个人日记、个人周/月/季度审计或 Mentat 日志。用于用户要求写日记、保存周期审计或承接 canonical Mentat 写入；个人日记在完整正文通过内容门后自动保存到 canonical 季度日志，周期审计和 Mentat 走各自受保护请求门，草稿或非标准路径仍执行确认门。
metadata:
  version: "11.10.1"
  authority_role: standalone
---

# 个人日志权威实现

本文件是 Pi 运行时的 standalone authority。`authority.json` 必须绑定到本文件自身，不得依赖 `.gemini`、`.codex`、`.agents` 或其他运行时副本。

## 启动门

1. 在当前会话 `scratch` 中准备遥测输出路径；不得写入报告目录、长期记忆或知识库。
2. 运行：

   `python scripts/authority_gate.py --config authority.json --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --event-output <SESSION_SCRATCH>/skill-load.jsonl`

3. 仅当返回 `ok=true`，且 `authority_path` 精确等于本文件路径时继续执行。
4. 以下任一情况立即停止草稿生成和写入：

   - 权威路径不存在或不是本文件；
   - 版本或 SHA-256 与 `authority.json` 不一致；
   - 配置重新引入 `.gemini`、`.codex`、`.agents` 或其他外部技能副本；
   - 写入范围、确认状态或目标日期无法确定。

## 不可越过的边界

- 调用本技能生成个人日记，即默认授权只读获取日记日期及次日日历的最小事件字段，以及最近 3 天 Garmin 健康摘要；不再为这两类限定读取重复询问授权。若窗口含当前自然日且必需组件末端陈旧，还授权直接运行一次两阶段同步（`sync_health_data.py sync --dry-run` 后 `--allow-network --allow-sync`），不再启动 `Codex-Garmin-Health-Sync` 计划任务。权限不足或授权失败不得同步，也不授权注册或修复任务。
- Garmin 必须本地优先，并先通过 canonical `personal-health-analysis` 权威门。末端陈旧时直接运行两阶段同步一次并重读本地；同步失败保留同步前证据，不重试、不改走实时接口。仅当本次未尝试新鲜度同步且本地明确返回 `no_data` 时，才可使用已有有效凭证对同一 3 天窗口执行一次云端只读查询；`partial` 继续使用本地数据并披露缺口，依赖、Schema、完整性或其他读取错误不得触发云端回退。
- 云端返回 `authentication_required` 时立即停止健康数据读取并披露缺口；Garmin 登录、令牌修复或刷新必须由用户另行明确授权。
- 默认读取授权不包含 Google Workspace 登录、OAuth 客户端或令牌创建/刷新、凭据导出，亦不包含 Garmin 登录、令牌创建或刷新写入、绕过新鲜度门的本地数据库同步、同步任务注册/更新、原始活动文件下载、账户资料、设备闹钟、日历写操作或任何第二处持久化；仅允许一次 canonical 两阶段直同步。
- 日历只能证明安排，不能单独证明实际参加或任务完成。健康指标只作描述性背景，不生成未经验证的能力分数、医学判断、确定因果或强制日程干预。
- 日记中的能量字段必须把机器侧缺失哨兵投影为可读的“状态、原因、仍可观察事实和判断边界”；`采集审计` 必须披露同步资格、是否启动/等待、任务终态、本地重读结果、实时回退是否使用及稳定原因码；`执行带宽` 固定使用 `not_scored` 并解释边界，来源未提供睡眠负债时写 `sleep_debt_h=null` 与 `sleep_debt_status=not_provided_by_source`。不得只写空值或 `[DATA_UNAVAILABLE]`。
- Mentat 日志不自动读取日历或 Garmin；只有个人日记生成流程继承上述限定默认授权。
- 个人日记在完整八章节生成并通过内容门后自动保存到当日 canonical 季度日志，无需人工确认；允许单一 `[OVERRIDE]` 或 `[WARROOM]` 前缀。调用层必须提交 `personal-diary-request-v1` artifact，绑定用户事件 ID 与文本 SHA-256、日记日期、kind、专用动作 `replace-personal-diary`、canonical 目标、scope hash、payload hash 和 `canonical_autosave` 策略。支持直接更新或携带今日/明日事项及勘误更正的日记指令；草稿、预览、只读、不保存、跨日期复用或修改技能等元请求不得自动写入。未命中自动保存策略或非 canonical 目标的写入保留 hash-bound 用户确认门。
- 通过 `mentat-insight-diary` 明确要求生成、更新、记录或写 Mentat 日志时，原始请求同时授权写入 canonical Mentat 季度档案，不再重复询问确认。该例外不适用于个人日记、草稿/预览、自定义路径、知识库或外部系统。
- 通过 `personal-cognitive-auditor` 生成个人周、月或季度审计时，只有受保护用户事件中的精确 canonical 请求或 `AUDIT_AUTOSAVE` 结构化命令，才能授权把通过审计门的目标周期区块保存到 canonical 季度个人日志。调用层必须提交 `periodic-audit-request-v1` artifact，绑定用户事件 ID 与文本 SHA-256、周期、动作、canonical 目标、scope hash 和 `canonical_autosave` 策略；写入器回查当前受保护 `PI_SESSION_FILE`。草稿、预览、只读、不保存或其他修饰请求不得写入。保存必须保留周期结束日既有日记及其他周期审计，只新增或替换同周期区块。该例外不适用于日度、年度、自定义路径、知识库、Vector Lake、STQM、外部系统或第二处持久化。
- 写入必须使用权威实现的授权范围回执和同日原子替换；纯前置追加已禁用。
- 写后重新读取目标日期，日期标题数量必须等于 1；个人日记自动保存要求八章日记正文与 payload 一致，并保持同日既有合法周/月/季审计区块不变；重复或非法周期区块失败关闭，周期审计保存还要求目标周期标题数量等于 1、原日记与其他周期审计保持不变，且请求、授权与写入范围哈希必须相等。

## Canonical 目标与写入协议

- canonical 个人日志：`C:/Users/shich/MEMORY/raw/privacy/Diary/YYYY-QN.md`。
- canonical Mentat 日志：`C:/Users/shich/MEMORY/raw/privacy/Diary/mentat_audit/YYYY-QN_Audit.md`。
- 日期按 `Asia/Shanghai` 计算；季度由目标日期确定。不得把个人日志写入 Mentat 文件，反之亦然。
- 写入只允许先调用 `python scripts/diary_ops.py scope` 生成状态为 `awaiting_confirmation` 的 `diary-write-scope-v1` 回执。该命令不生成确认，也不能写 canonical 文件。
- 每次 scope 生成随机 128-bit `scope_nonce`，并把它、目标、日期、动作、周期标识、payload 与写前状态共同纳入 `authorization_scope_sha256`。确认必须来自调用层独立生成的 `diary-write-approval-v1` artifact；`diary_ops.py` 不提供生成 approval artifact 的命令，也不信任 artifact 的自声明：`user_confirmation` 必须回查受保护的当前 `PI_SESSION_FILE`，命中内容精确为“确认写入 <authorization_scope_sha256>”或“确认保存 <authorization_scope_sha256>”的用户消息；旧确认、通用“确认”或 receipt 时间字段均不能授权新 scope。`mentat_evidence_gate` 绑定输入 SHA-256。个人日记自动保存 approval 必须携带 `personal-diary-request-v1` 字段，绑定生成正文 SHA-256 并回查受保护用户事件，再对不可变 payload 快照运行严格内容门。周期审计 approval 除绑定 payload SHA-256 并重跑固定内容门外，还必须携带 `periodic-audit-request-v1` 字段并回查受保护用户事件；任何字段或文本 hash 漂移都拒绝。
- 写入调用 `python scripts/diary_ops.py replace`，并同时提交完全相同的内容文件、scope 回执和 confirmed approval artifact。任何目录或锁创建前先验证日期、canonical 目标和授权矩阵；随后工具在同目录排他锁内重新读取目标、核对写前 SHA-256、payload、受保护内容和范围摘要，再执行同卷临时文件 `fsync` 与 `os.replace`；无论替换成功或失败，都在 `finally` 中清理尚未提交的临时文件，禁止遗留第二份私人日记。
- 授权矩阵固定为：`personal + replace-date → user_confirmation`；`personal + replace-personal-diary → personal_diary_request_gate`；`mentat + replace-date → mentat_evidence_gate`；`personal + replace-weekly-audit → weekly_audit_gate`；`personal + replace-monthly-audit → monthly_audit_gate`；`personal + replace-quarterly-audit → quarterly_audit_gate`。其他组合一律拒绝。周期标识必须分别为合法 `YYYY-Www`、`YYYY-MM`、`YYYY-QN`，目标日期必须等于对应 ISO 周星期日、自然月末或自然季末。
- 需人工确认的草稿/调试写入使用 `action=replace-date`；生成后自动保存的个人日记使用专用 `action=replace-personal-diary`。`replace-date` 维持显式整日替换；`replace-personal-diary` 仅替换日记正文，保留同日已有合法周/月/季审计及其他日期，重复或非法周期区块失败关闭。两者同日不存在时插入到首个日期块之前。周期审计使用对应 `replace-*-audit` 动作，只替换匹配周期的 H2 区块，并验证同日其他内容 hash 不变。payload 的第一个非空行且唯一 H2 必须为目标周期标题，其余标题只能为 H3 或更深；0–3 个空格缩进的 ATX H1/H2 与 Setext H1/H2 同样禁止。日期块不存在时只创建日期标题与目标审计区块。
- 非空 canonical 文件没有可识别日期标题、存在重复目标标题、锁已存在或目标在 scope 后变化时，必须失败关闭。禁止纯追加、重复日期标题和绕过 scope/approval 的直接写入。

## Personal diary checkpoint

- drafts/previews 不写入。
- 除 canonical 个人日记生成后自动保存外，非 canonical 的 personal diaries、custom paths、knowledge bases、Vector Lake、STQM、外部系统和任何第二处持久化必须分别取得明确授权。
- 仅明确声明草稿、预览、只读或非 canonical 目标的个人日记才需要先展示固定正文、canonical 目标、日期、动作和完整 `authorization_scope_sha256`，并要求用户回复“确认写入 <该 SHA-256>”或“确认保存 <该 SHA-256>”。调用层只保存该用户消息的 Pi session event ID；写入器从受保护会话记录核验角色、完整文本和 scope hash。正文、目标、日期、动作或 nonce 变化时，旧 scope 与 approval 同时失效。
- 本次用户只提供“今日”和“明日”事项时，不得扩写为已交付、已验收或已形成结论；日历只能证明安排。

## Canonical personal-diary auto-save exception

个人日记请求（包括“更新个人日志”、携带今日/明日具体事项内容的明确日记指令或明确指向个人日记的后续勘误，允许单一 `[OVERRIDE]` 或 `[WARROOM]` 前缀）在生成完整个人日志并通过内容门后，自动保存到事件发生日的 canonical 季度文件，无需人工确认。写入器严格核验日记授权意图、事件日期与日记日期相等、排除草稿/预览/只读/不保存等免写词，并执行 `personal-diary-request-v1` 全字段绑定。否定写入先拒绝。裸健康更新、泛勘误或仅给事项不构成新授权；未绑定日记上下文不得将泛更正自动保存，也不创建第二套持久状态。当前这类“修改技能，使某命令自动保存”等元请求不会被识别为日记写入授权。

自动保存 payload 必须以唯一的当日 H1 开始，且按顺序包含下列八个非空 H2；不得出现其他 H1/H2 或 Setext H1/H2：

1. `## 今日事项`
2. `## 今日进展与证据`
3. `## 判断与反思`
4. `## 时间背景`
5. `## 能量管理（描述性生理背景）`
6. `## 明日事项`
7. `## 风险与未知`
8. `## 行动闭环`

信息不足时在对应章节写明“用户未提供”“日历仅证明安排”“健康证据门不可用”或其他具体缺口，不得留空、使用模板占位符或补写未经证实的完成状态。完整 payload 必须对不可变快照运行 `audit_gate.py --enforce-template-fields`；门禁通过只授权当前 canonical 日期块，不授权第二处存储。

## Canonical Mentat auto-save exception

通过 `mentat-insight-diary` 且证据门允许保存时，originating request is the approval，只授权 canonical Mentat 当日日期块；不再要求第二次确认。approval 必须绑定 evidence input SHA-256，写入器会重新运行固定证据门并要求 `save_allowed=true`。

## Canonical periodic personal-audit auto-save exception

通过 `personal-cognitive-auditor` 生成周、月、季度 personal-log audit 且内容门通过时，只有以下两类受保护用户事件可继续：一是精确文本 `本周个人日志审计`/`个人日志周审计`、`本月个人日志审计`/`个人日志月度审计`、`本季度个人日志审计`/`个人日志季度审计`，允许单一 `[OVERRIDE]` 或 `[WARROOM]` 前缀，并要求事件时间对应同一周期；二是精确 `AUDIT_AUTOSAVE {canonical-json}` 命令，其中 period type、period ID 和 `canonical_autosave` 策略必须匹配。任何额外修饰都拒绝，因此草稿、预览、只读或不保存请求保持只读。调用层生成的 approval 必须包含 `periodic-audit-request-v1` artifact 字段；写入器绑定事件、周期、动作、目标、scope 和 payload 后，只接受对应 `replace-*-audit` 动作。

## 日历与 Garmin 限定读取

1. 个人日记可只读获取日记日期及次日日历的最小字段，以及最近 3 天 Garmin 健康摘要。日历读取顺序固定如下，不得跳步或静默切换数据源：
   1. 先运行 `gws auth status`。只有命令成功、`auth_method=oauth2`、`token_valid=true`，且授权范围包含 Google Calendar 时，才进入查询；只记录资格状态和稳定原因码，不复制用户标识、客户端标识、令牌或凭据路径。
   2. 再分别运行 `gws calendar +agenda --today --timezone Asia/Shanghai --format json` 与 `gws calendar +agenda --tomorrow --timezone Asia/Shanghai --format json`。查询结果只投影日期/起止时间、摘要和日历名称；位置、参与人、描述及其他字段仅在用户当前请求明确需要时读取。
   3. `gws` 不存在、权限检查失败、Calendar scope 缺失、认证失效或查询失败时，立即报告日历证据缺口与稳定原因码；不得自动登录、刷新或修改凭据。
   4. 禁止自动改用 Outlook COM、Microsoft Graph、Windows 日历或其他日历源。只有用户在当前请求中明确指定并授权其他来源时，才可改用该来源。
2. Garmin 先通过 canonical `personal-health-analysis` 的 `runtime-authority.json` 门，再执行本地读取命令中的 `--source local --allow-health-data`。返回 `partial` 时保留已有证据并披露缺口；返回 `no_data` 时不得伪造观测。
3. Current-date freshness gate：只有窗口含当前日且必需组件末端陈旧时，允许一次 `sync_health_data.py sync --dry-run`，通过后再执行一次带 `--allow-network --allow-sync --allow-health-data` 的同步并本地重读；without retry。同步失败后不得改走实时接口。
4. 仅当本次没有尝试同步、本地明确为 `no_data`、用户已授权联网且 `runtime_preflight.py --mode live` 通过时，才允许一次同窗口 `--source live --allow-network --allow-health-data`。`authentication_required`、`RUNTIME_CONTRACT_MISMATCH`、Schema 或完整性错误立即失败关闭。
5. 不注册、更新或修复计划任务，不调用 `Codex-Garmin-Health-Sync`，不执行 Garmin 登录、令牌写入或原始活动下载。

## 能量管理（描述性生理背景）

只有实际读取健康摘要时才生成本节；没有健康读取需求时不得为填模板强行采集。生成后运行适用的 `audit_gate.py --enforce-template-fields`。

- **数据范围与来源**：记录请求窗口、实际观测窗口、来源和读写边界。
- **组件覆盖与新鲜度**：分别说明 sleep、hrv、body_battery、heart_rate、stress 的末端日期。
- **采集审计**：`sync_eligible=<true|false>; sync_attempted=<started|waited_existing|direct|not_attempted>; task_status=<success|failed|timeout|invalid|start_failed|interrupted_or_terminated|not_checked>; local_reread=<accepted|rejected|not_run>; local_status=<complete|partial|no_data|read_error|not_run>; live_fallback=<used|not_used>; reason=<稳定原因码>`
- **睡眠观察**：只记录来源实际提供的数值、状态和日期。
- **HRV 与静息心率观察**：保持描述性，不生成诊断。
- **Body Battery 与压力观察**：不把共享上游信号重复合成为总分。
- **执行带宽**：固定为 `not_scored`，不得出现 score、value、level 或 color。
- **睡眠负债**：来源未提供时使用 `sleep_debt_h=null; sleep_debt_status=not_provided_by_source; method=none; baseline_h=null; window_days=null`。
- **摩擦解构**：分开记录任务负荷、主观感受、生理观察和外部约束。
- **交叉归因**：说明日期是否同期，并保留替代解释。
- **干预指令**：仅给出触发条件、最小动作和完成标准，不自动调整会议、训练或重要事项。
- **数据缺口与不可判断事项**：明确缺失组件、日期和判断边界。

## 执行顺序

1. 运行权威门并确认返回本文件。
2. 确定日期、目标类型和 canonical 季度文件，只读取目标日期块。
3. 按请求最小化读取日历与健康摘要；日历必须先执行 `gws auth status`，再查询 Google Calendar。任一步失败均按上述合同关闭并报告缺口，不得扩大来源或擅自改用 Outlook。
4. 生成固定正文并执行事实、敏感信息、模板和日期标题检查；个人日记必须生成上述完整八章节并通过严格内容门。
5. 调用 `diary_ops.py scope` 并保存 scope 回执；此时状态只能是 `awaiting_confirmation`。自动保存个人日记使用专用 `replace-personal-diary`。
6. 个人日记在完整正文通过内容门后自动保存，无需人工确认；调用层直接生成绑定 scope hash 的独立 `diary-write-approval-v1` approval artifact（包含 `personal-diary-request-v1` 字段）。只有明确声明草稿、预览、只读或非 canonical 路径的日记才展示 hash 并等待用户确认。个人日记、Mentat evidence 与周期审计 payload 各只读取一次，核验 hash 后写入私有不可变临时快照，固定门禁只读取该快照；个人日记与周期审计还要绑定受保护用户事件。随后写入阶段仍复核原始输入 hash，阻断 TOCTOU。
7. 用完全相同的内容文件、scope 和 approval 调用 `diary_ops.py replace`。自动保存个人日记使用 `replace-personal-diary`；需确认的草稿日记使用 `replace-date`；周、月、季度审计分别使用 `replace-weekly-audit`、`replace-monthly-audit`、`replace-quarterly-audit`。
8. 复读目标日期，验证日期标题恰好 1 个、个人日记正文（排除受保护审计）或目标周期区块等于 payload、目标周期标题恰好 1 个（如适用）、请求/授权/写入范围摘要一致，且非目标历史未变化。

## 验证

运行 `python -m unittest discover -s scripts -p "test_*.py" -v`。测试只使用临时文件，不读取真实日记或健康数据；同时运行权威门 live probe，确认返回本文件的最终 SHA-256。
