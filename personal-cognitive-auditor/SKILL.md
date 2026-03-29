---
name: personal-cognitive-auditor
version: 2.0.0
description: |
  战略认知联合审计官。当要求“复盘今日日志”或需要“周结/月结/年结”深层认知审计，整合多源数据并进行严格战术问责时激活。本身不负责文件写入，仅负责出具报告。
---

# SKILL: Cognitive Auditor (Strategic Review)

核心职责：处理“今日日志复盘”以及“周结/月结/年结”的深层认知审计，整合多源数据并进行严格战术问责。**本技能不负责直接落盘写入文件**。分析生成报告后，必须交由 `personal-diary-writer` 进行统一落盘。

## 1. 核心约束 (Core Mandates)
- **前置反转 (Inversion)**: 强制依赖真实数据。禁止脑补。日常复盘强制依赖物理探针 (`gather_context.py`)，长周期复盘才允许调度其他分析型 Agent。
- **职责剥离**: 所有的日志或报告写入工作，在确认后一并转交 `personal-diary-writer` 负责。

## 2. 执行协议 (Execution Protocol)

### Phase 0: Context Gathering (强制获取)
- **日常探针 (今日复盘)**: 强制执行 `python {root_dir}\.gemini\scripts\io_engine\gather_context.py` 获取 Garmin 与 Google Calendar 数据，严禁自行组装参数或调用其他命令。
- **[PROMPT_MANDATE]**: 执行前必须强制读取对应的提示词模板 (`prompts/DAILY.md`, `prompts/WEEKLY.md` 等)。严禁仅依赖系统自身知识。
- **战术提取**: 必须调用 `python {root_dir}\.gemini\scripts\io_engine\diary_ops.py extract_tactics` 脚本抓取上一个周期的战术。
- **展示大纲**: 向用户展示大纲，调用 `ask_user` 获取审批。

### Phase 1: Cognitive Distillation 
- **Session Analysis (今日复盘)**: 提取当日核心产出，生成 cognitive_depth_score (1-5)，将 Phase 0 获取的生理与日程数据融入分析。
- **【强制同步】 (仅限周/月/年结)**: 
  - 只有在长周期复盘时，才激活 `personal-monthly-insights` 抓取交互数据，激活 `personal-health-analysis` 抓取生理基线与图表。
- **[TABLE_MANDATE]**: 必须采用 Markdown Table 格式进行战术问责 (PART 0)，并包含 Root Cause 分析。
- Reviewer 审计: 检查“是否包含历史战术问责？(Yes/No)”和“是否已包含交互与生理数据？(Yes/No)”

### Phase 2: Hand-off (交接协议)
- **交接指令**: 分析报告生成完毕后，明确向 `personal-diary-writer` 发送交接指令，要求其执行以下动作：
  1. 落盘主日志文本。
  2. 若本次复盘涉及底层架构或认知重构，且被 `diary_ops.py` 的底层 Hook 警告，则提醒系统启动内观日记。

## 3. Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "personal-cognitive-auditor", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 4. 历史失效先验 (Gotchas)
- **[PROMPT_MANDATE]**: 必须强制读取 `prompts/weekly.md` 或 `prompts/MONTHLY.md`，严禁仅依赖简化大纲。
- DO NOT summarize historical tactics. 必须无损抓取并问责。
