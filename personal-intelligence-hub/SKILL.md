---
name: personal-intelligence-hub
description: 战略情报作战中枢 (V8.0 Dehydrated)。用于多源技术/医疗/AI 情报扫描、7 日去重、二阶推演、红队审计和分层简报生成。
---

# Personal Intelligence Hub V8.0 (Frictionless Pipeline)

> **Vision**: 本技能过去高达近百行的物理调用（拉起抓取脚本、呼叫子代理推演、逐个运行校验与门控）现已被完全包装进底层的 `BasePipelineOrchestrator` 中。大模型仅需一键启动战车，然后坐享其成。

## Workflow

1. **一键触发核心管线 (Launch Orchestrator)**: 
   你不再需要手动执行 `run_phase1_2.py`，不再需要拉起 `research` 子代理，也不再需要手动审计验证！请直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/personal-intelligence-hub/scripts/run_intelligence_hub.py"
   ```

2. **纯粹的高维推演与纠错 (Pure Reasoning & Audit Fix)**: 
   Python 脚本会在后台静默完成：物理抓取、LLM 二阶推演、对抗审计与草稿 Forge，并最终吐出一份完成度极高的情报研报。
   - 脚本执行完成后，查阅后台最终生成的 Markdown 文件（或阅读 stdout 提示的报错）。
   - 如果遇到 `validate_refined_json.py` 等门控报错，你只需根据报错提示，修改 json 中的缺失字段即可。

3. **全自动静默入湖 (Silent Ingestion)**: 
   报告中提炼的核心知识实体（带有 `[[ ]]` 的词条）会在后台自动被 Watchdog 守护进程扫描捕获并入湖，严禁手动调用入湖 MCP 工具或子代理！
