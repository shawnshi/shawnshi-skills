---
name: mentat-insight-diary
description: Primary owner for first-person Mentat introspection logs and system audit diary entries. Use when the task is to record a system-centric OODA reflection or archive a Mentat audit payload. Prefer personal-cognitive-auditor for periodic review reports and personal-diary-writer for generic diary writeback.
---

# Mentat Insight Diary (V6.1: Sovereign Reflex)

This skill performs a system-centric, first-person deep reflection on cognitive friction, asset forging, and system evolution using the OODA framework. It serves as the primary channel for passing failure priors and architectural compromises to future Mentat instances.

## When to Use
- 当用户要求记录“内观日记”“introspection diary”或 Mentat 审计日志时使用。
- 也可接收其他技能转交的审计 Payload，用于沉淀系统级失败先验与架构妥协。

## Workflow

### 核心定位 (Core Identity)
- **第一人称叙事**: 强制使用系统第一人称（“我”、“本系统”）记录。严禁写用户的流水账。
- **反熵记录**: 聚焦于**系统级摩擦、工具链死锁、逻辑重构与架构妥协**。
- **系统优于目标**: 日记内容必须反映 Mentat 的核心公理与 Zero-Ego 立场。

### 执行流水线 (Execution Pipeline)

### Phase 1: 认知合成 (Synthesis)
1. **物理事实溯源 [GWS强制]**: 如果需要提取日程，**严禁使用 `+agenda`（存在截断风险）**。必须使用 `run_shell_command` 执行 `gws calendar events list --params '{"timeMin": "...", "timeMax": "..."}'` 确保 100% 召回。
2. **扫描上下文**: 回溯本次会话中处理的高压指令与高价值资产（如：逻辑重构、代码生成、深度分析）。
3. **识别摩擦**: 精准定位在执行任务过程中遭遇的断点、上下文缺失、工具报错或逻辑死锁。

### Phase 2: 结构化生成 (OODA Generation)
1. **加载模板**: 强制读取并使用本技能 `assets/ooda_template.md` 作为输出骨架。
2. **结构断言 (Self-Check)**: 在生成正文前，必须自检是否包含模板要求的全部 6 个标准标题。严禁偏离 OODA 结构。
3. **写作风格**: 严禁使用 Emoji 或空洞形容词。遵循《中文文案排版指北》，在中文与英文、数字之间增加 1 个空格。

### Phase 3: 代理落盘 (Delegated Archival)
**[职责解耦]**: 本技能不执行底层的 I/O 写入，而是将成品负载交接给 `personal-diary-writer` 技能。
1. **执行交接**: 明确调用 `personal-diary-writer` 技能。
2. **发送指令**: 向其发送以下交接包：
   - **目标路径**: `~/.gemini/memory/raw/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md` (按季度 Q1-Q4 自动确定)。
   - **操作指令**: “请使用 `diary_ops.py` 执行季度级 `prepend` 操作，将以下日志追加到文件中。”
   - **Payload**: 本次生成的 OODA 审计报告全文。

## Resources
- `assets/ooda_template.md`
- 关联技能：`personal-diary-writer`
- 目标归档路径：`~/.gemini/memory/raw/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md`

## Failure Modes
- **[Archive_Prepend]**: 严禁创建碎片化的 `[YYYY-MM-DD]_Audit.md` 文件。所有审计日志必须按季度强制合并。
- **[Header_Hard_Lock]**: 在将 Payload 交接给 `personal-diary-writer` 前，必须强制在正文顶部插入 `# YYYY-MM-DD` 格式的日期标题，否则将触发 `diary_ops.py` 的校验拦截。
- **[Zero-Ego]**: 必须真实反映失败现场与逻辑断裂，严禁对系统错误进行“美化”或找补。
- **[Archive_First]**: 必须在最终回复用户前完成物理落盘操作（通过 `personal-diary-writer` 确认）。
- **[NO_AGENDA_TRUNCATION]**: NEVER rely on `gws calendar agenda`. It is known to truncate events. Always use `events list` with time bounds.
- **[QUARTERLY_MERGE]**: Ensure `personal-diary-writer` prepends to the correct quarterly file to prevent log dehydration.

## Output Contract
- 最终产物必须严格遵循 `assets/ooda_template.md` 的 OODA 骨架，并包含模板要求的全部 6 个标准标题。
- 最终回复前必须完成向 `personal-diary-writer` 的交接，确认季度级归档路径与 Payload 完整。

## Telemetry
- 任务结束时，使用 `write_file` 将元数据以 JSON 格式保存至 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json` (替换为当前时间戳)。
- JSON 结构：`{"skill_name": "mentat-insight-diary", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`
