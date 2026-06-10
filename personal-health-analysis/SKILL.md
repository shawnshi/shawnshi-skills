---
name: personal-health-analysis
description: 首席医疗官(CMO)级生理健康审计引擎 (V8.0 Dehydrated)。当用户提到“心率/睡眠/压力/HRV/感冒迹象/身体电量/健康审计/准备度/生理状态/健康洞察/运动分析/热力图/90天”等指标时务必激活。
---

# Personal Health Analysis (V8.0: CMO / Strategic Architect Level)

> **Vision**: 本技能过去高达 135 行的繁复文件与脚本交互（包括手动要求模型运行 `sync_health_data.py` 同步数据、再按需调用不同统计脚本、还要判断生成 HTML）现已被完全封装至底层的 `run_health_analysis.py` 调度器中。

## Workflow

1. **评估意图层级 (Level)**: 
   - **Level 1 (微观战术)**: 回答诸如“今晚能练深蹲吗”、“今天状态如何”。
   - **Level 2 (日结复盘/常规)**: 常规的“健康审计”、“近 7 天状态”。
   - **Level 3 (长程战略)**: 提到“90天”、“大屏”、“热力图”等宏观需求。

2. **触发管线 (Launch Orchestrator)**:
   根据意图，直接调用底层流水线：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/personal-health-analysis/scripts/run_health_analysis.py" --level [1/2/3] --days [1/7/90]
   ```
   *注意：脚本已内置 `sync_health_data.py` (Phase 0) 同步机制，无需再手动执行同步！*

3. **读取并交付 (Delivery)**:
   脚本执行完成后，最终生成的 CMO 级评估简报会存放在 `C:/Users/shich/.gemini/tmp/health_audit_payload_L[level].md` 中。
   请直接读取该文件，并原汁原味地向用户汇报。
