---
name: hit-solution-architect
description: 医院数字化转型解决方案架构师 (V8.0 Dehydrated)。提供医院 IT 顶层设计、信创改造方案、数据资产规划。
---

# HIT Solution Architect (V8.0: Frictionless Strategy Engine)

> **Vision**: 本技能过去高达 153 行的复杂文件 I/O、多子代理章节并发组装与繁重审计，现已被底层 `BasePipelineOrchestrator` 全面接管。大模型不再充当项目经理，而只需专注于方案的红队推演与最终交付润色。

## 0. 模式分流 (Modes)
- `brief`: 高管汇报版。
- `proposal`: 标准概要方案 (默认)。
- `blueprint`: 完整架构蓝图。

## 1. Workflow

1. **信息探针与一键触发 (Launch Orchestrator)**: 
   动笔前，向用户确认 `<课题 Topic>` 和 `<受众 Audience>`（如 CIO、卫健委、院长）。
   随后，直接调用工具执行管线调度器，严禁自己挂起写长文：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-solution-architect/scripts/run_solution_architect.py" --topic "具体课题" --audience "CIO" --mode "proposal"
   ```

2. **高维校验与交付 (Review & Delivery)**: 
   Python 脚本会在后台并发完成：痛点建模、架构与割接路径制图(Mermaid)、TCO 测算，并执行红队逻辑查杀。草稿将存储在 `C:/Users/shich/.gemini/tmp/solution_draft_[mode].md`。
   - 读取该草稿，进行最终的人类高管视角润色。
   - 确保方案不仅画了饼，还给出了**平滑割接路径**、**除外责任 (SOW Exclusions)** 和具体的**预算锚点**。
   - 确认无误后，使用 `write_file` 归档至 `MEMORY/raw/solutions/` 目录，并向用户正式交付。

3. **全自动静默入湖 (Silent Ingestion)**: 
   报告中提炼的任何专有产品实体、架构概念（带有 `[[ ]]` 的词条）会在后台自动被 Watchdog 扫描捕获并入湖，严禁手动调用入湖 MCP 工具！
