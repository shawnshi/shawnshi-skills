---
name: personal-monthly-insights
description: 战略元分析与摩擦基因解码器。当用户提到“效率低”、“协作摩擦”、“指令依赖高”，或要求“出具系统交互报告/复盘”时激活。通过审计对话、日志与系统元数据，提取人机协作的负熵规律，并沉淀可复制的 Prompt / Checklist / 自动化候选。
---

# personal-monthly-insights (V9.0: Audit Contract Edition)

This skill audits human-agent collaboration as a structured operating system, not as a free-form monthly recap.

## Core Workflow

Execute the pipeline in order:

1. **Extract**: Run `analyze_insights_v4.py --period <PERIOD> --extract-only` and `system_retro.py`.
2. **Analyze**: Read `raw_metrics_<PERIOD>.json` and identify anti-patterns, objective signals, and workflow leverage.
3. **Serialize**: Save reasoning to `~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json` following [references/SCHEMA.md](references/SCHEMA.md).
4. **Validate**: Run `validate_agent_audit.py` before rendering.
5. **Deliver**: Run `analyze_insights_v4.py --period <PERIOD> --render --agent-file ...` and summarize the top strategic adjustment.

Supported periods: `1d`, `7d`, `30d`, `90d`, `year`.

## Delivery Standard

Never stop at a file path. Always deliver:

- **Top 1 strategic adjustment**
- **One ready-to-copy workflow asset**
- **One next-cycle action**

## Result Gate

A valid audit must satisfy all five conditions:

1. It identifies one core collaboration anti-pattern.
2. It aligns subjective friction with at least one objective metric or telemetry signal.
3. It provides one ready-to-copy Prompt / Checklist / Constraint asset.
4. It proposes at least one automation or skill candidate.
5. It gives one next-cycle action that can be verified in the next audit window.

## Telemetry & Metadata

Task complete: save metadata to `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`.
JSON structure: `{"skill_name": "personal-monthly-insights", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## NLAH Gotchas

- `IF [Action == "Update JSON Structure"] THEN [Require Alignment with "references/SCHEMA.md"]`
- `IF [Field == "coach_summary"] THEN [Require qualitative coaching] AND [Halt if mostly raw numbers]`
- `IF [Field == "behavioral_analysis.points"] THEN [Require length == 8]`
- `IF [Action == "Render"] THEN [Require validate_agent_audit.py pass first]`
- `IF [Action == "File Persistence"] THEN [Require Path starts_with "~/.gemini/" OR runtime-resolved reports dir]`
