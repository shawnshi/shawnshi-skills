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
3.  **Serialize (Structure)**: Save your reasoning to `~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json` following the [SCHEMA.md](references/SCHEMA.md) strictly.
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

## ⚠️ NLAH Gotchas
- `IF [Action == "Update JSON Structure"] THEN [Require Alignment with "analyze_insights_v4.py" logic]`
- `IF [Field == "coach_summary"] THEN [Require Content == "Qualitative Expert Coaching"] AND [Halt if Content == "List of Raw Numbers"]`
- `IF [Field == "behavioral_analysis.points"] THEN [Require length == 8]`
- `IF [Action == "File Persistence"] THEN [Require Path starts_with "~/.gemini/"]`
- `IF [Action == "Retrieve History"] THEN [Require Tool IN ("grep_search", "timestamp_bounded_search")] AND [Halt if Action == "Cross-month Full read_file"]`
