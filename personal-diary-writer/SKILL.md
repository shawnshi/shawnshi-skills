---
name: personal-diary-writer
description: 个人日志原子写入器。当用户需要日常记录、写日记、状态录入，或被高级系统（如 cognitive-auditor）调用落盘审计报告时激活。该技能通过专用的 diary_ops.py 执行安全写入，确保护理日志的物理完整性。
---

# Personal Diary Writer (Atomic I/O)

This skill handles high-frequency, lightweight daily status recording and atomic file operations for diary/log entries.

## 0. 核心约束 (Core Mandates)
- **物理操作债防守**: 必须强制使用 `run_shell_command` 调用 `python ~/.gemini/skills/scripts/io_engine/diary_ops.py` 进行 `prepend` 操作。严禁使用 Shell 重定向或常规 `write_file` 直接覆盖主日志文件。
- **Win32 物理适配**: 永远使用 `--content_file` 传递复杂内容，防止 Windows 命令行转义导致解析错误。
- **语义本体**: 强制检查 `#tag` 格式，确保所有标签符合本体标准。

## 1. 执行协议 (Execution Protocol)

### Phase 0: Reconnaissance (证据先行)
- **自动化事实重建**: 在组装日志前，必须先自动执行 `gws calendar events list` 获取日程数据。
- **前置数据硬锁**: 能量数据**绝对禁止**主 Agent 自己编造。你必须调用 `personal-health-analysis` 的专用查询脚本（如：`python ~/.gemini/skills/personal-health-analysis/scripts/garmin_intelligence.py insight_cn --days 3`）提取真实的系统态势与睡眠负债。若脚本执行失败，该字段强制填入 `[DATA_UNAVAILABLE]`，严禁进行语义推理。

### Phase 1: Structure Alignment (结构对齐)
- **Schema 绝对防御**: 严格按照以下模板结构组装内容，绝对禁止合并标题：
```markdown
# YYYY-MM-DD 星期X

## 今日工作 (Tactical Context)
- ...

## 核心产出 (Strategic Professional Assets)
- ...

## 明日战术锁定 (Next Day Tactics)
1. ...

## 认知结晶 (Cognitive Distillation)
...

## 熵增对抗 (Chaos Mitigation)
...

## 能量管理 (Biological-Cognitive Correlation)
- **系统态势**: [必须提取自 Garmin 简报，如 🟡 黄灯 (Fatigue)]
- **执行带宽**: [提取分数，如 68.9/100]
- **睡眠负债**: [提取债务小时数，如 1.9h]
- **摩擦解构**: [基于上述真实数据进行的简短定性分析]

## 标签
#tag
```

### Phase 2: Action
1. **规范化标签**: 处理用户或审计官提供的文本，确保标签格式正确。
2. **中间暂存**: 将组装好的内容写入临时文件 `~/.gemini/tmp/log_entry.md`。
3. **安全写入**: 使用 `run_shell_command` 执行 `python ~/.gemini/skills/scripts/io_engine/diary_ops.py prepend --content_file ~/.gemini/tmp/log_entry.md`。

## 2. 附属落盘协议 (Secondary Write-Backs)

### 2.1 Mentat Insight Archival (内观日记同步)
- **触发条件**: 当前记录属于 Mentat Insight 深度日志。
- **动作**: 物理归档至 `~/.gemini/memory/raw/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md`。必须使用 `diary_ops.py` 执行季度级 `prepend`。

### 2.2 Strategic Sync (全局记忆同步)
- **触发条件**: 接收到来自 `personal-cognitive-auditor` 且 `cognitive_depth_score >= 4` 的产出。
- **动作**: 将认知结晶格式化为 JSON并调用 `run_shell_command` 执行 `python ~/.gemini/skills/scripts/io_engine/memory_sync.py` 同步至全局 `memory.md`。

## 3. Telemetry & Metadata (Mandatory)
- 任务结束时，使用 `write_file` 将元数据以 JSON 格式保存至 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json` (替换为当前时间戳)。
- JSON 结构：`{"skill_name": "personal-diary-writer", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 4. 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Archive"] THEN [Require run(diary_ops.py)] AND [Halt if creating fragment files]`
- `IF [Condition == "Modified memory.md" OR "Tool_Error_Count >= 2"] THEN [Execute activate_skill("mentat-insight-diary")]`
- `IF [Action == "Append Multiple Lines"] THEN [Require Parameter == "--content_file"]`
- `IF [Field == "Energy Management"] THEN [Halt if source != "garmin_intelligence.py"] AND [Require Output == "[DATA_UNAVAILABLE]" if data missing]`
