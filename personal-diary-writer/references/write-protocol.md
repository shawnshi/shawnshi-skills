# 保存协议与授权合同

仅进入保存分支时完整读取本文件；任何保存前必须通过根入口 authority 启动门。以下 scope/approval 与事务要求不适用于不保存的草稿或只读输出，不得据此索取草稿保存确认。

## 保存边界

- 个人日记在完整八章节生成并通过内容门后自动保存到当日 canonical 季度日志，无需人工确认；允许单一 `[OVERRIDE]` 或 `[WARROOM]` 前缀。调用层必须提交 `personal-diary-request-v1` artifact，绑定用户事件 ID 与文本 SHA-256、日记日期、kind、专用动作 `replace-personal-diary`、canonical 目标、scope hash、payload hash 和 `canonical_autosave` 策略。支持直接更新或携带今日/明日事项及勘误更正的日记指令；草稿、预览、只读、不保存、跨日期复用或修改技能等元请求不得自动写入。未命中自动保存策略但用户另行明确要求保存的 canonical 写入保留 hash-bound 用户确认门；非 canonical 目标不在本写入器能力范围，不创建 scope。
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
- 用户另行明确要求保存且需人工确认的 canonical 调试/整日写入使用 `action=replace-date`；生成后自动保存的个人日记使用专用 `action=replace-personal-diary`。`replace-date` 维持显式整日替换；`replace-personal-diary` 仅替换日记正文，保留同日已有合法周/月/季审计及其他日期，重复或非法周期区块失败关闭。两者同日不存在时插入到首个日期块之前。周期审计使用对应 `replace-*-audit` 动作，只替换匹配周期的 H2 区块，并验证同日其他内容 hash 不变。payload 的第一个非空行且唯一 H2 必须为目标周期标题，其余标题只能为 H3 或更深；0–3 个空格缩进的 ATX H1/H2 与 Setext H1/H2 同样禁止。日期块不存在时只创建日期标题与目标审计区块。
- 非空 canonical 文件没有可识别日期标题、存在重复目标标题、锁已存在或目标在 scope 后变化时，必须失败关闭。禁止纯追加、重复日期标题和绕过 scope/approval 的直接写入。

## Personal diary checkpoint

- drafts/previews 不写入；草稿、预览、只读、不保存请求不生成 scope/approval，不展示待确认 hash，也不要求保存确认。后续另行明确要求保存时重新判定授权，不复用草稿阶段的同意。
- 除 canonical 个人日记生成后自动保存外，非 canonical 的 personal diaries、custom paths、knowledge bases、Vector Lake、STQM、外部系统和任何第二处持久化必须分别取得明确授权。
- 只有用户后续另行明确要求保存、且未命中自动保存例外的 canonical 个人日记写入，才先展示固定正文、canonical 目标、日期、动作和完整 `authorization_scope_sha256`，并要求用户回复“确认写入 <该 SHA-256>”或“确认保存 <该 SHA-256>”。调用层只保存该用户消息的 Pi session event ID；写入器从受保护会话记录核验角色、完整文本和 scope hash。正文、目标、日期、动作或 nonce 变化时，旧 scope 与 approval 同时失效。
- 本次用户只提供“今日”和“明日”事项时，不得扩写为已交付、已验收或已形成结论；日历只能证明安排。

非 canonical 目标即使另获明确授权，当前 `diary_ops.py` 仍拒绝；不得绕过写入器或把确认当作任意路径通行证。custom paths、knowledge bases、Vector Lake、STQM、外部系统和第二处持久化不在本写入器能力范围。

## Canonical Mentat auto-save exception

通过 `mentat-insight-diary` 且证据门允许保存时，originating request is the approval，只授权 canonical Mentat 当日日期块；不再要求第二次确认。approval 必须绑定 evidence input SHA-256，写入器会重新运行固定证据门并要求 `save_allowed=true`。

## Canonical periodic personal-audit auto-save exception

通过 `personal-cognitive-auditor` 生成周、月、季度 personal-log audit 且内容门通过时，只有以下两类受保护用户事件可继续：一是精确文本 `本周个人日志审计`/`个人日志周审计`、`本月个人日志审计`/`个人日志月度审计`、`本季度个人日志审计`/`个人日志季度审计`，允许单一 `[OVERRIDE]` 或 `[WARROOM]` 前缀，并要求事件时间对应同一周期；二是精确 `AUDIT_AUTOSAVE {canonical-json}` 命令，其中 period type、period ID 和 `canonical_autosave` 策略必须匹配。任何额外修饰都拒绝，因此草稿、预览、只读或不保存请求保持只读。调用层生成的 approval 必须包含 `periodic-audit-request-v1` artifact 字段；写入器绑定事件、周期、动作、目标、scope 和 payload 后，只接受对应 `replace-*-audit` 动作。

## 不可变输入与 TOCTOU

个人日记、Mentat evidence 与周期审计 payload 各只读取一次，核验 hash 后写入私有不可变临时快照，固定门禁只读取该快照；个人日记与周期审计还要绑定受保护用户事件。随后写入阶段仍复核原始输入 hash，阻断 TOCTOU。
