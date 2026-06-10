---
name: hit-industry-radar
description: 医疗行业战略雷达。Primary owner for weekly healthcare IT news, competitor moves, bids, vendor dynamics, and market-event battle reports. 
---

# HIT Industry Radar (V8.0 Dehydrated Edition)

> **Vision**: 本技能的繁重流程控制流已被全面下沉至底层的 `BasePipelineOrchestrator`。大模型已从“状态机搬运工”中解放，仅需专注核心语义推演。

## When to Use
- 面对用户生成“医疗 IT 战报”、“竞对动态”、“行业周报”的诉求时使用。

## Workflow

1. **触发核心管线 (Launch Orchestrator)**: 
   你不再需要自己手动循环、挂起、管理临时文件或拉起多个子代理并发！请直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-industry-radar/scripts/run_industry_radar.py"
   ```

2. **纯粹的高维推理 (Pure Reasoning)**: 
   Python 脚本会在后台自动拉取所有战区的简报、自动去重、自动过滤水分。脚本执行完毕后，会将脱水草稿生成在 `C:/Users/shich/.gemini/tmp/draft_hit_radar.md`。
   你只需读取该草稿，进行最后的高管视角润色或直接交付用户即可。

3. **全自动静默入湖 (Silent Ingestion)**: 
   你不再需要操心知识图谱的同步！若你在润色过程中提取出了核心概念并写入了 `MEMORY/wiki/`，底层的 Watchdog 守护进程会自动扫描并异步向量化。严禁在大模型端手动调用入湖工具！
