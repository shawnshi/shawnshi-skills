---
name: mentat-collaboration-audit
description: 系统与协作联合审计管线 (V8.0 Dehydrated)。当用户表达“复盘”、“效率低”、“系统绕弯路”或要求执行 Retro/月度交互洞察时触发。
triggers: ["复盘", "效率低", "系统绕弯路", "执行 Retro", "查看 Token 消耗"]
---

# Mentat Collaboration Audit (V8.0: Frictionless Pipeline)

> **Vision**: 本技能过去高达 80 行，且极度依赖大模型作为命令行调度器手动执行多个 Python 脚本并拼凑 JSON。现已被底层 `run_collaboration_audit.py` 全面接管。大模型现在只需一键触发流水线，并根据最终产出执行“物理规则挂载”。

## Workflow

1. **一键触发核心管线 (Launch Orchestrator)**:
   无需你手动执行 `system_retro.py` 或 `analyze_insights_v4.py`，直接调用管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/mentat-collaboration-audit/scripts/run_collaboration_audit.py" --mode "interaction" --period "monthly"
   ```
   *(Mode 可选 `telemetry` 纯数据视角，或 `interaction` 深度人机交互视角，Period 可自定义如 weekly/monthly)*

2. **高维校验与交付 (Review & Delivery)**:
   脚本会在后台静默完成遥测数据的提取与推演，草稿将存储在 `C:/Users/shich/.gemini/tmp/mentat_audit_payload_[mode]_[period].md`。
   你需要读取该文件，并原封不动地向用户宣读这份冰冷、粗暴的审计报告。

3. **主动物理围栏挂载 (Active Constraint Enforcement)**:
   若你在阅读生成的草稿时，发现内部包含了 `auto_constraint_writeback`（防御规则写回）提议，你**必须主动**调用 `multi_replace_file_content` 或 `write_to_file` 工具，将该防御规则强制注入系统底层的 `GEMINI.md` 或 `pai/` 相关规则文件，实现真正的闭环免疫演化。
