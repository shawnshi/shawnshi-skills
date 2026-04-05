---
name: personal-cognitive-auditor
description: 战略认知联合审计官。当用户提出“复盘今日日志”、“周结/月结/年结”或需要深层认知审计、多源数据整合与战术问责时激活。本技能仅负责生成审计报告，报告必须交由 personal-diary-writer 统一落盘。
---

# Personal Cognitive Auditor (Strategic Review)

This skill performs deep cognitive auditing for daily, weekly, monthly, and annual reviews, integrating multi-source data and enforcing tactical accountability.

## 0. 核心约束 (Core Mandates)
- **前置反转 (Inversion)**: 审计必须强制依赖真实生理与日程数据，严禁脑补。
- **职责剥离**: 所有的日志或报告物理落盘必须通过 `personal-diary-writer` 负责。

## 1. 执行协议 (Execution Protocol)

### Phase 0: Context Gathering (强制获取)
1. **获取生理与日程数据**: 使用 `run_shell_command` 执行 `python ~/.gemini/skills/scripts/io_engine/gather_context.py` 获取 Garmin 与 Google Calendar 数据。
2. **加载审计模板**: 根据复盘周期类型，读取本技能 `prompts/` 目录下的对应 Markdown 模板（如 `DAILY.md`, `WEEKLY.md` 等）。严禁仅依赖系统知识生成报告结构。
3. **提取上周期战术**: 使用 `run_shell_command` 执行 `python ~/.gemini/skills/scripts/io_engine/diary_ops.py extract_tactics` 抓取待审计战术。
4. **展示大纲**: 向用户展示审计大纲，并调用 `ask_user` 获取确认。

### Phase 1: Cognitive Distillation 
1. **生成评分**: 提取核心产出，计算 `cognitive_depth_score` (1-5)。将 Phase 0 获取的数据融入深度分析。
2. **长周期同步 (仅限周/月/年结)**: 
   - 只有在长周期复盘时，才激活 `personal-monthly-insights` 抓取交互数据，激活 `personal-health-analysis` 抓取生理基线与图表。
3. **战术问责**: 必须采用 Markdown Table 格式执行战术问责 (PART 0)，并包含 Root Cause 分析。
4. **自检审计**: 检查是否已包含历史战术问责以及交互与生理数据。

### Phase 2: Hand-off (交接协议)
1. **发送交接指令**: 分析报告生成完毕后，向 `personal-diary-writer` 技能发送交接指令，并传递审计报告内容，要求其执行：
   - 落盘主日志文本。
   - 若涉及底层架构重构，则提醒系统启动 `mentat-insight-diary`。

## 2. Telemetry & Metadata (Mandatory)
- 任务结束时，使用 `write_file` 将执行元数据以 JSON 格式保存至 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json` (替换为当前时间戳)。
- JSON 结构：`{"skill_name": "personal-cognitive-auditor", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. 历史失效先验 (NLAH Gotchas)
- `IF [Phase == 0] THEN [Require read_file("prompts/Template.md")] AND [Halt if relying solely on memory]`
- `IF [Action == "Extract Tactics"] THEN [Halt if Summarizing] AND [Require Lossless Extraction]`
- `IF [Section == "Tactical Accountability"] THEN [Halt if Format == "Unordered List"] AND [Require Format == "Markdown Table"]`
