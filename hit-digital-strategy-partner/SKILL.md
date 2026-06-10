---
name: hit-digital-strategy-partner
description: 顶级医疗数字化战略专家 (V8.0 Dehydrated)。用于医疗IT深度咨询、ROI测算、重构商业模式、MBB框架分析、行业研究报告、董事会备忘录与高规格战略验证。
---

# HIT Digital Strategy Partner (V8.0: Frictionless Strategy Engine)

> **Vision**: 本技能过去长达百行的复杂文件 I/O、五层价值链并发与结果质量门审计，现已被底层的 `BasePipelineOrchestrator` 全面接管。你无需手动操作黑板状态机，仅需调用 Python 引擎并聚焦于最终战略交付。

## 0. 模式分流 (Modes)
- `brief`: 快速高密度战略简报 (默认)。
- `deep-dive`: 深度研究。
- `board-memo`: 董事会/高管备忘录，强调极度冷酷的行动指令。

## 1. Workflow

1. **一键触发核心管线 (Launch Orchestrator)**: 
   获取用户提供的 `<战略课题>` (topic) 和期望的 `<模式>` (mode) 后，直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-digital-strategy-partner/scripts/run_strategy_partner.py" --topic "战略课题" --mode "brief"
   ```

2. **高维校验与交付 (Review & Delivery)**: 
   Python 脚本会在后台完成：政策与竞品并发抓取、核心判断逻辑碰撞、悲观 ROI 压测以及草稿生成，并存储在 `C:/Users/shich/.gemini/tmp/strategy_draft_[mode].md` 中。
   - **如果审计通过**：读取草稿，进行高阶润色，确认是否具备“暴力执行动词”与“二跳推理”，随后将其落盘归档并呈现给用户。
   - **如果审计失败**：根据 Python 返回的 `strategy_gate.py` 报错提示，修改草稿中不达标的章节（如：缺乏明确的行动杠杆、或缺少悲观 ROI 数据），直到满足医疗战略专家的高压交付标准。

3. **全自动静默入湖 (Silent Ingestion)**: 
   报告中提炼的核心知识实体或概念图谱（带有 `[[ ]]` 的词条）会在后台自动被 Watchdog 扫描捕获并入湖，严禁手动调用入湖 MCP 工具或子代理！
