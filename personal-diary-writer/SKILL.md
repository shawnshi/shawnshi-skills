---
name: personal-diary-writer
description: 生成并保存个人日记、个人周/月/季度审计或 Mentat 日志。用于用户要求写日记、保存周期审计或承接 canonical Mentat 写入；个人日记在完整正文通过内容门后自动保存到 canonical 季度日志，周期审计和 Mentat 走各自受保护请求门，纯当次文本草稿不读取私人数据、不保存；私人读取和保存分别进入授权门。
metadata:
  version: "11.10.2"
  authority_role: standalone
---

# 个人日志权威实现

本文件是 Pi 运行时的 standalone authority。`authority.json` 必须绑定到本文件自身，不得依赖 `.gemini`、`.codex`、`.agents` 或其他运行时副本。

## 先选分支（任何私人读取或保存之前）

- **纯文本草稿**：用户要求草稿、预览、只读或不保存，且仅使用当次用户提供文本时，直接在回复中起草。不读取个人历史、日历、健康库、私人会话或凭证；不运行 authority 启动遥测，不调用 `diary_ops.py scope`/`replace`，不生成 scope/approval，不要求 scope/hash 确认。日期或事实缺失可注明缺口，不为起草要求写入范围。
- **私人数据读取**：需要个人历史、日历或 Garmin 时，先通过下方启动门，再完整读取 `references/private-data-read.md`，按现有最小范围授权读取；草稿身份不豁免读取门。用户明确排除的来源不得读取。只读/不保存仍不进入 scope、approval 或保存确认。
- **保存**：仅在命中下述 canonical 自动保存例外或用户另行明确要求保存时，先通过启动门，再完整读取 `references/write-protocol.md`。生成待保存个人日记的能量字段时，另读 `references/private-data-read.md` 的能量模板（含未采集时的缺口表达）；读模板本身不授权数据采集。读取授权不等于保存授权；从草稿转为保存必须重新判定请求与目标，不能复用草稿阶段同意。

用户要求草稿、预览、只读或不保存时，不写入、不索取保存确认；若需要私人数据，仅进入读取分支。仅当次文本也能生成正式日记，但其自动保存仍须完整执行保存分支，不能借纯文本跳过门禁。

## 启动门（仅私人读取或保存分支）

1. 在当前会话 `scratch` 中准备遥测输出路径；不得写入报告目录、长期记忆或知识库。
2. 运行：

   `python scripts/authority_gate.py --config authority.json --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --event-output <SESSION_SCRATCH>/skill-load.jsonl`

3. 仅当返回 `ok=true`，且 `authority_path` 精确等于本文件路径时继续执行。
4. 以下任一情况立即停止受门控的私人读取和写入；不得用草稿名义绕过失败的门：

   - 权威路径不存在或不是本文件；
   - 版本或 SHA-256 与 `authority.json` 不一致；
   - 配置重新引入 `.gemini`、`.codex`、`.agents` 或其他外部技能副本；
   - 私人读取范围或目标日期无法确定；保存分支另要求写入范围与适用授权/确认状态明确。

## 不可越过的边界

- 私人读取保留既有限定授权：个人日记日期及次日日历最小字段、最近 3 天 Garmin 摘要；日历先验证 Google Calendar OAuth 资格，禁止静默换源。Garmin 先过 canonical 健康权威门、本地优先；仅在未命中草稿、预览、只读、不保存、不同步、不联网或仅用本地数据等退出条件时，当前日末端陈旧才允许一次两阶段同步并重读，不重试。仅未尝试同步且本地 `no_data`、已授权联网并通过 preflight 时才允许一次同窗口实时回退。认证、Schema、完整性等错误失败关闭，不自行登录、刷新凭据、修复任务或扩展采集。完整限制见读取合同。
- 日历只能证明安排，不能单独证明实际参加或任务完成。仅有“今日”和“明日”事项不得扩写为已交付、已验收或已有结论。健康指标仅作描述性背景，不生成能力分数、诊断、确定因果或强制日程干预；不为填模板强行读取健康数据，缺口必须可读。
- Mentat 不自动读取日历或 Garmin；个人日记读取默认授权不外溢到其他日志。任何第二处持久化、自定义路径、知识库或外部系统均不受 canonical 例外授权；当前写入器拒绝非 canonical 目标，明确授权也不能绕过实现。
- 保存一律 `authority_gate` → scope → 独立 approval → `replace` → 复读。个人日记绑定受保护用户事件与正文 hash；Mentat 绑定证据输入并重跑门；周/月/季审计绑定事件、周期和 payload 并重跑门。不得自行伪造确认或仅信任 artifact 自声明。
- 同日原子替换、防重复、保留合法同日周期审计与非目标历史、排他锁、写前 hash 复核、不可变快照、同卷 `fsync`/`os.replace` 及失败清理全部保留；禁止纯追加与绕过 scope/approval 的直接写入。

## Canonical 目标与写入协议

- canonical 个人日志：`C:/Users/shich/MEMORY/raw/privacy/Diary/YYYY-QN.md`。
- canonical Mentat 日志：`C:/Users/shich/MEMORY/raw/privacy/Diary/mentat_audit/YYYY-QN_Audit.md`。
- 日期按 `Asia/Shanghai` 计算，季度由目标日期确定；两类文件不可混写。周/月/季审计日期分别为 ISO 周星期日、自然月末、自然季末。
- `scripts/diary_ops.py` 只提供受控 scope 与 replace；字段、授权矩阵、确认事件校验、周期标题拓扑和事务失败条件全部在保存前必读的 `references/write-protocol.md`，不得只凭本节摘要写入。

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

通过 `mentat-insight-diary` 明确要求生成、更新、记录或写 Mentat 日志，且证据门允许保存时，原始请求授权 canonical Mentat 当日日期块，不再重复询问确认。草稿/预览不写入；不适用于个人日记、自定义路径或第二处存储。approval 绑定 evidence input SHA-256，写入器重跑固定证据门并要求 `save_allowed=true`；完整合同见保存协议。

## Canonical periodic personal-audit auto-save exception

通过 `personal-cognitive-auditor` 生成周、月、季度审计时，仅受保护用户事件中的精确当前周期 canonical 请求或匹配的 `AUDIT_AUTOSAVE {canonical-json}` 授权自动保存；绑定 `periodic-audit-request-v1` 并通过内容门，只新增或替换同周期区块。精确别名、单一前缀、日期/周期与字段绑定见保存协议。草稿、预览、只读、不保存及其他修饰请求不得写入；日度、年度、自定义路径或第二处持久化不在例外内。

## 执行顺序与完成标准

1. 先选分支。纯当次文本草稿仅在回复中输出，标明未读取私人来源、未保存；到此结束，不执行后续写入步骤。个人日记草稿沿用八章结构，缺失日期或证据明确标注，不冒充已验证或可自动保存的正文。
2. 私人读取分支先运行启动门并阅读读取合同；确定授权来源与日期，只读所需目标日期块及最小日历/健康摘要。来源失败按合同关闭并披露稳定原因码，不扩大来源。只读输出完成即结束，无 scope/approval/保存确认。
3. 保存分支先运行启动门并阅读保存协议，确定日期、kind、canonical 目标和动作。生成固定正文，检查事实、敏感信息、日期标题及适用模板；个人日记完整八章通过严格内容门，未读取健康时在能量章节说明缺口，不伪造观测。
4. 调用 `python scripts/diary_ops.py scope`，回执只能为 `awaiting_confirmation`。个人日记自动保存使用 `replace-personal-diary`，由调用层提交独立 `diary-write-approval-v1` 和绑定请求 artifact；Mentat 与周期审计走各自受保护门。未命中例外且用户明确要求保存的 canonical 整日写入，才展示固定正文、目标、日期、动作、完整 scope hash 并等待精确用户确认。
5. 用完全相同的内容文件、scope 和 confirmed approval 调用 `python scripts/diary_ops.py replace`；不得把只读退出改成等待确认，不得把已获确认当作可以更换正文/日期/目标/动作/nonce 的许可。
6. 复读验证：日期标题恰好 1 个；个人日记正文（排除受保护审计）或目标周期区块等于 payload；目标周期标题恰好 1 个（如适用）；请求/授权/写入范围 hash 一致；合法同日其他审计及非目标历史不变。重复、非法周期块、锁冲突或 scope 后目标变化均失败关闭，失败不宣称保存成功。

## 验证

在本技能目录运行 `python -B -m unittest discover -s scripts -p "test_*.py" -v`，覆盖入口分支、按需引用、授权门与合成临时文件事务；不得读取真实日记、健康数据或私人会话。维护时可仅对本技能运行资源清单检查与 Gate，并用 authority gate 验证本文件最终 SHA-256（遥测只放当前任务 scratch）。这些检查不代替真实日历/Garmin或业务保存的另行授权 live 验证。
