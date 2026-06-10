---
name: hit-weekly-brief
description: 医疗行业战区研报中枢 (V8.0)。Primary owner for weekly think-tank, consulting, and whitepaper briefs in healthcare or digital health.
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

# HIT Weekly Brief (行业战区周报) V8.0 Dehydrated Edition

> **Vision**: 消除智库研报中的“共识幻觉”。本技能的四路并发抓取、跨界映射与硬核审计流均已深度下沉至 `BasePipelineOrchestrator`。大模型仅需专注最后的反向验证与交付。

## When to Use
- 当用户要求生成数字健康周报、扫描本周智库/白皮书、或提炼医疗行业周度战略信号时使用。

## Workflow

1. **一键触发核心管线 (Launch Orchestrator)**: 
   你不再需要手动拉起 4 个 Subagent 去进行四路并发！请直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-weekly-brief/scripts/run_weekly_brief.py"
   ```

2. **纯粹的高维推演与纠错 (Pure Reasoning & Audit Fix)**: 
   Python 脚本会在后台静默完成：4 条赛道（政策、技术、战略、跨界）的情报抓取、语义翻译与模板组装，并生成草稿存储在 `C:/Users/shich/.gemini/tmp/draft_hit_brief.md`。脚本也会自动调用 `hit_audit_gate.py` 进行质量审计。
   - **如果审计通过**：读取草稿，进行最后的高管视角润色，使用 `write_file` 落盘至最终归档目录 `MEMORY/raw/DigitalHealthWeeklyBrief/`，并向用户交付。
   - **如果审计失败（例如缺少 Contrarian 反向观点、有死链接等）**：仔细阅读 Orchestrator 输出的报错日志，针对性修改草稿并重新审计，直到通过。

3. **全自动静默入湖 (Silent Ingestion)**: 
   你不再需要操心知识图谱的同步！若你在润色过程中提取出了核心实体概念（如：`[[Medical Semantic Layer]]`）并写入了 `MEMORY/wiki/` 目录，底层的 Watchdog 守护进程会自动扫描并异步向量化。严禁手动调用入湖 MCP 工具！
