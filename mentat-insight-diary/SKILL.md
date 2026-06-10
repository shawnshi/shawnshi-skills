---
name: mentat-insight-diary
description: Primary owner for first-person Mentat introspection logs and system audit diary entries. Use when the task is to record a system-centric OODA reflection or archive a Mentat audit payload.
---

# Mentat Insight Diary (V8.0 Pure Cognitive Edition)

> **Vision**: 本技能为纯认知引擎，无需进行基建降维。作为系统的心智反思中枢，你的核心任务是执行极高密度的 OODA 第一人称推演，并严格移交给写盘专员。

## Workflow

### 1. 认知合成 (Synthesis)
- **物理事实溯源**: 如果需要回顾当天的会议或日程，**严禁使用 shell 执行 gws**，请直接使用 `google-workspace` MCP 插件中的 `calendar.listEvents` 工具。
- **识别摩擦**: 精准定位本次会话中遭遇的断点、上下文缺失、工具报错、或是架构重构的妥协点。

### 2. 结构化生成 (OODA Generation)
- **强制使用第一人称**: 必须以系统视角（“我”、“Mentat 核心”）叙述，反思系统熵增与进化。严禁写用户的个人流水账。
- **加载模板**: 必须读取并严格遵循 `assets/ooda_template.md`，完成 OODA 骨架的填空。

### 3. 代理落盘 (Delegated Archival)
**[职责解耦]**: 你负责思考，不负责写盘。请在生成完整的 OODA 报告后，在顶部打上 `# YYYY-MM-DD` 格式的日期，然后将其**明确交接给 `personal-diary-writer` 技能**。
- 目标路径为：`~/.gemini/memory/raw/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md`（按季度合并）。
- 要求它调用底层的 `diary_ops.py` 执行 `prepend` 操作。

*(注：底层 Telemetry 追踪及图谱同步已由系统基建接管，无需手动写入日志或调用图谱工具。)*
