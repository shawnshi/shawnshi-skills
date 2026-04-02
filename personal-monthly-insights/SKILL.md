---
name: personal-monthly-insights
description: 战略元分析与摩擦基因解码器。当用户提到“效率低”、“协作摩擦”、“指令依赖高”，或要求“出具系统交互报告/复盘”时激活。通过审计对话与元数据，提取人机协作的负熵规律。
---

# personal-monthly-insights (V8.1: Agentic Edition)

This skill performs high-level strategic analysis of human-agent collaboration patterns, identifying friction points and proposing workflow improvements.

## 📋 Core Workflow Overview

This is an Agent-Native workflow. You MUST execute the [4-Stage Pipeline](references/WORKFLOW.md) carefully:

1.  **Extract (Physical)**: Run `analyze_insights_v4.py` and `system_retro.py` to gather data.
2.  **Analyze (Cognitive)**: Read `raw_metrics_<PERIOD>.json` and perform **Commander-mode** reasoning to identify collaboration anti-patterns.
3.  **Serialize (Structure)**: Save your reasoning to `~/.gemini/MEMORY/personal-insights/agent_audit_result.json` following the [SCHEMA.md](references/SCHEMA.md) strictly.
4.  **Deliver (Render)**: Run the renderer and provide a strategic wrap-up to the user.

## 🔄 Delivery Standard

NEVER end with just a file path. ALWAYS summarize the **Top 1 strategic adjustment** and provide an actionable **Workflow Asset (Prompt/Checklist)**.

**Example Delivery:**
✅ **Strategic Audit Complete (Last 7 Days)**
Dashboard: [file:///...]
> **💡 Top 1 Strategic Workflow Asset:**
> **Target Friction:** Missing context when modifying schemas.
> **Constraint Prompt:** `Before coding, output understanding of file structure and assumptions. Wait for confirmation.`

## 🛡️ Telemetry & Metadata (Mandatory)
Task complete: save metadata to `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`.
JSON structure: `{"skill_name": "personal-monthly-insights", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## ⚠️ Gotchas
- **[SCHEMA_SYNC]**: Updating JSON structure MUST align with `analyze_insights_v4.py` rendering logic.
- **[NO_DATA_REPETITION]**: `coach_summary` MUST be qualitative expert coaching, not a list of raw numbers.
- **[ELASTIC_RENDERING]**: Ensure `behavioral_analysis.points` has exactly 8 entries to avoid empty dashboard sections.
- **[PATH_LOCK]**: Always use standard `~/.gemini/` paths for persistence.
- **[CONTEXT_EFFICIENCY]**: 强制采用 `grep_search` 或时间戳边界框定策略获取索引，绝不允许跨月度或全量历史 `read_file` 载入。
