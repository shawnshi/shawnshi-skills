# Agentic Analysis Pipeline for personal-monthly-insights (V9.0)

This workflow remains Agent-Native. Python handles extraction, aggregation, validation, and rendering. The Agent owns interpretation.

## Stage 1: Data Extraction
1. Run `python analyze_insights_v4.py --period <PERIOD> --extract-only`.
2. Valid periods: `1d`, `7d`, `30d`, `90d`, `year`.
3. Run `python ~/.gemini/skills/scripts/system_retro.py` to collect execution telemetry when available.

## Stage 2: Cognitive Reasoning
1. Read `~/.gemini/MEMORY/raw/personal-insights/raw_metrics_<PERIOD>.json`.
2. Identify:
   - one dominant collaboration anti-pattern
   - one metric-backed explanation
   - one workflow asset
   - one automation candidate
   - one next-cycle action

## Stage 3: Insight Serialization
1. Save reasoning to `~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json`.
2. Follow [SCHEMA.md](SCHEMA.md) exactly.
3. Set `version` to `9.0`.

## Stage 4: Validation Gate
1. Run `python validate_agent_audit.py ~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json`.
2. Do not render if validation fails.

## Stage 5: Render & Deliver
1. Run `python analyze_insights_v4.py --period <PERIOD> --render --agent-file ~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json`.
2. Deliver the report with a concise strategic wrap-up, not just the generated path.
