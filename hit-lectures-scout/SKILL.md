---
name: hit-lectures-scout
description: 医疗数字化前沿科研侦察兵。Primary owner for medical AI paper scouting, clinical literature scanning, RWE filtering, and frontier academic breakthrough watch.
---

# HIT Intel Scout (V8.0 Dehydrated Edition)

> **Vision**: 本技能的繁重流程控制流、子代理派发与门控审计已被全面下沉至底层的 `BasePipelineOrchestrator`。大模型仅需专注核心语义推演与报错修复。

## When to Use
- 当用户要求扫描医疗 AI 论文、追踪医疗大模型突破，或输出带商业含义的科研战报时使用。

## Workflow

1. **触发核心管线 (Launch Orchestrator)**: 
   你不再需要自己手动拉起多个子代理去分别阅读预印本或期刊！请直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-lectures-scout/scripts/run_lectures_scout.py"
   ```

2. **纯粹的高维推理与修复 (Pure Reasoning & Fix)**: 
   Python 脚本会在后台自动完成 DeepXiv 检索、中英期刊扫描、RWE 真实世界证据过滤，并生成草稿存储在 `C:/Users/shich/.gemini/tmp/draft_hit_scout.md`。脚本也会自动调用 `hit_audit_gate.py` 进行质量审计。
   - **如果审计通过**：读取草稿，进行最后的高管视角润色，使用 `write_file` 落盘至最终目录 `MEMORY/raw/DigitalHealthLecturesScout/`，并向用户交付。
   - **如果审计失败**：仔细阅读 Orchestrator 输出的报错日志，针对性修改草稿并重新审计，直到通过。

3. **全自动静默入湖 (Silent Ingestion)**: 
   你不再需要操心知识图谱的同步！若你在润色过程中提取出了核心概念并写入了 `MEMORY/wiki/`，底层的 Watchdog 守护进程会自动扫描并异步向量化。严禁手动调用入湖工具！
