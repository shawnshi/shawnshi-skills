# Agentic Analysis Pipeline for personal-monthly-insights (V8.1)

This workflow is 100% Agent-Native. The Python scripts serve as "Data Pumps," while the Agent (you) performs the high-level reasoning.

## Stage 1: Data Extraction (Physical)
1. **Extract Logs**: Run `python analyze_insights_v4.py --period <PERIOD> --extract-only`.
   - Valid periods: `1d`, `7d`, `30d`, `90d`, `year`.
2. **Gather Metrics**: Run `python ~/.gemini/skills/scripts/system_retro.py` to get skill execution metrics (Token usage, failure rates).

## Stage 2: Cognitive Reasoning (The Heart)
1. **Analyze Metrics**: Read the generated `~/.gemini/MEMORY/personal-insights/raw_metrics_<PERIOD>.json`.
2. **commander-mode Analysis**:
   - Transition from mere observation to **Strategic Coaching**.
   - Identify **Anti-patterns** (e.g., "blind coding without schema verification," "ineffective trial-and-error due to missing context").
   - Align **Subjective Complaints** with **Objective Telemetry** (e.g., does a feeling of low efficiency correlate with specific tool failure rates?).
   - Propose **Workflow Engineering** assets (Skills, Hooks, Constraints).

## Stage 3: Insight Serialization
1. **Save Reasoning**: Follow the strict structure in [SCHEMA.md](SCHEMA.md) and use `write_file` to save to `~/.gemini/MEMORY/personal-insights/agent_audit_result.json`.
2. **Formatting**: Ensure `coach_summary` is qualitative and `prompt_assets` are ready-to-copy.

## Stage 4: Render & Deliver
1. **Generate Dashboard**: Run `python analyze_insights_v4.py --period <PERIOD> --render --agent-file ~/.gemini/MEMORY/personal-insights/agent_audit_result.json`.
2. **Strategic Wrap-up**: Deliver the report to the user following the **Delivery Format** in SKILL.md.
