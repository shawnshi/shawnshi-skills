---
name: personal-cognitive-auditor
version: 1.0.0
description: |
  战略认知联合审计官。当要求“复盘今日日志”或需要“周结/月结/年结”深层认知审计，整合多源数据（Garmin, 系统交互）并进行严格战术问责时激活。本身不负责文件写入，仅负责出具报告。
---

# SKILL: Cognitive Auditor (Strategic Review)

核心职责：处理“今日日志复盘”以及“周结/月结/年结”的深层认知审计，整合多源数据并进行严格战术问责。**本技能不负责直接落盘写入日记文件**。分析生成报告后，必须引导或调用 `personal-diary-writer` 进行落盘。

## 1. 核心约束 (Core Mandates)
- **前置反转 (Inversion)**: 强制依赖真实数据。必须调度 `garmin-health-analysis` 和 `personal-monthly-insights`。禁止脑补。
- **职责剥离**: 所有的日志或报告写入工作，在确认后转交 `personal-diary-writer` 负责。
- **原生依赖 (Native Dependency)**: 严禁手写 `gws` bash 命令。任何日历数据的获取，必须且只能通过 `activate_skill` 工具激活 `gws-calendar-agenda`。

## 2. 执行协议 (Execution Protocol)

### Phase 0: Context Gathering (强制获取)
- **日程校准**: 强制执行 `activate_skill` 挂载 `gws-calendar-agenda` 抓取当日与次日日程，严禁通过 `run_shell_command` 拼凑 JSON 参数。
- **[PROMPT_MANDATE]**: 执行“每周审计”或“月度审计”前，必须强制读取 `prompts/weekly.md` 或 `prompts/MONTHLY.md`；**执行“今日复盘”前，必须强制读取 `prompts/DAILY.md`**。严禁仅依赖系统自身知识。
- **战术提取**: 必须调用 `scripts/diary_ops.py extract_tactics` 脚本抓取上一个周期的战术。
- **展示大纲**: 向用户展示大纲，调用 `ask_user` 获取审批。

### Phase 1: Cognitive Distillation 
- **Session Analysis (今日复盘)**: 若为“复盘今日日志”，提取当日核心产出，生成 cognitive_depth_score (1-5)，并调用 `garmin-health-analysis` 获取今日身体电量等物理锚点。
- **【强制同步】 (仅限周/月/年结)**:
  - Usage Insight: 激活 `personal-monthly-insights` 抓取交互数据。
  - Health Audit: 激活 `personal-health-analysis` 抓取生理基线。
- **[TABLE_MANDATE]**: 必须采用 Markdown Table 格式进行战术问责 (PART 0)，并包含 Root Cause 分析。
- Reviewer 审计: 检查“是否包含历史战术问责？(Yes/No)”和“是否已包含交互与生理数据？(Yes/No)”

### Phase 2: Hand-off (双轨交接)
- 审计报告完成并审核通过后，停止生成主报告。
- **Mentat Insight 影子通道**: 你必须独立于主报告之外，按照 OODA 框架额外生成一份底层架构反思（Mentat Insight）。
- **交接指令**: 明确向 `personal-diary-writer` 发送交接指令，要求其执行以下动作：
  1. 落盘主日志文本。
  2. 执行 `Mentat Insight Archival`，落盘上述 OODA 报告。
  3. (若 `cognitive_depth_score >= 4`) 执行 `Strategic Sync`，落盘高价值记忆。

## 3. Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "personal-cognitive-auditor", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 4. 历史失效先验 (Gotchas)
- **[PROMPT_MANDATE]**: 必须强制读取 `prompts/weekly.md` 或 `prompts/MONTHLY.md`，严禁仅依赖简化大纲。
- **[TABLE_MANDATE]**: 战术问责必须使用 Markdown Table 格式，并包含 Root Cause 分析。
- **[TACTICS_EXTRACT]**: `extract_tactics` 必须支持 Level 2/3 标题及多种中文同义词（如“下周重点任务”）。
- DO NOT summarize historical tactics. 必须无损抓取并问责。
