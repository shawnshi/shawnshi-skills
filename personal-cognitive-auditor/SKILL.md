---
name: personal-cognitive-auditor
description: 战略认知联合审计官 (V8.0 Dehydrated)。当用户提出“复盘今日日志”“周结/月结/年结”或需要深层认知审计、多源数据整合与战术问责时激活。
---

# Personal Cognitive Auditor (V8.0: Frictionless Pipeline)

> **Vision**: 将原本包含大模型手工查阅日历、历史 `grep` 查询、并行呼叫处方代理和自我门控审查的繁复管线，重构为 I/O 脱水的 Python 流水线。大模型现只负责前置的数据收集和最终的转移落盘。

## Workflow

1. **环境上下文收集 (Context Gathering)**:
   作为主代理，你首先需要使用原生的工具获取客观上下文证据：
   - 优先使用 `mcp_google-workspace_calendar` 拉取近期事件。
   - 使用 `grep_search` 在 `~/.gemini/MEMORY/raw/privacy/Diary/` 查找上一周期的 `Next Tactics`（下期战术承诺）。
   - （将这两部分信息分别提炼为简短的字符串备用）。

2. **触发审计管线 (Launch Orchestrator)**:
   带上你抓取到的数据，触发底层管线。脚本会在后台自动完成“核心认知审计”、“无情的战术问责”、“认知处方生成”以及“最终门控审计”：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/personal-cognitive-auditor/scripts/run_cognitive_auditor.py" --period "daily/weekly/monthly/annual" --calendar "日历信息概括" --tactics "上期战术承诺概括"
   ```

3. **落盘移交 (Handoff)**:
   脚本完成后，会在 `C:/Users/shich/.gemini/tmp/cognitive_audit_payload_[period].md` 中生成包含最终审计结果与处方卡的完整 Payload。
   你需要读取该文件，并基于系统约定，将内容原封不动地 Hand-off 给 `personal-diary-writer` 技能完成物理落盘。你本人无需（也不应）手动使用 `write_file` 写入长篇日志。
