---
name: personal-health-analysis
version: 9.0.0
tier: action-allowed
description: 'CMO级生理健康审计引擎。通过 Garmin 数据执行全链路审计与决策准备度管理，支持热力图与长期分析。禁止跳过同步前置，禁止凭空编造生理数据。'
triggers: ["心率", "睡眠", "压力", "HRV", "身体电量", "健康审计", "生理状态", "运动分析"]
---

<strategy-gene>
Keywords: 生理健康审计, 执行带宽, 系统动量, Garmin Flu
Summary: 提取临床级生理指标并执行耗散结构分析，判定当前系统的认知准备度。
Strategy:
1. 同步先行：执行前必须隐式运行 sync_health_data.py 确保数据时效与 429 降级安全。
2. 动量诊断：计算 RHR 与 Stress 的 Delta 差值，判定系统处于超量恢复还是熵增。
3. 分级输出：微观问题 < 50 字指令；日结给出四层文本简报；长程战略强制 HTML 大屏。
AVOID: 绝对禁止编造生理数据；本地库缺失时严禁静默 fallback（Fail-Fast）；禁止跳过 Phase 0 同步。
</strategy-gene>

# Personal Health Analysis (CMO Level V9.0 Native)

本技能定位为“高管专属的前置医疗防线与战略决策引擎”，采用 **GEB-Flow V2.0** 架构进行全链路审计：通过本地物理数据湖 (GarminDB) 实现毫秒级查询，配合高级生理智能分析判定认知准备度与代谢摩擦。

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. un_command (强制执行 sync_health_data.py)
2. un_command (提取核心指标或调用智能诊断脚本)
3. un_command (可选：生成大屏或长程视图)
4. write_to_file (写入遥测沙盒数据)

## 1. 核心流程与架构 (The Protocol)

主代理必须严格按照以下阶段线性推进：

### Phase 0: Data Sync & Pre-flight (同步先行)
- **强制动作**: 在做任何分析前，主代理必须使用原生 un_command 执行同步脚本尝试更新本地数据湖。
  $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\sync_health_data.py"
- **降级防线**: 如果遇到 API 429 限流报错，系统会自动转入本地 SQLite 库进行审计（读取历史快照）。

### Phase 1: Precision Data Extraction (核心数据提取)
根据用户的提问深度，使用原生 un_command 调用对应的工具箱（带上 UTF-8 编码锁）。
- **单项指标**: $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" [sleep|hrv|heart_rate|body_battery|stress] --days 7
- **综合摘要**: $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" summary --days 7
- **准备度查询**: $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" readiness --days 1
- **Flu 疾病探测**: $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" flu_risk --days 7

### Phase 2: Strategic Synthesis (战略级综合诊断)
- 常规复盘或深层体检，调用：
  $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" insight_cn --days 7
- **诊断聚焦**: 提取 Executive Readiness (0-100)、利用耗散结构计算高压耗散时长、重点探测患病模式（RHR 飙升 + HRV 骤降 + 呼吸率异常升高）。

### Phase 3: Executive Output (高管级降噪输出)
- **微观问题**: 精简的指令，直接回答行不行，禁止废话。
- **日结复盘**: 输出四层模块文本简报（采用 BLUF 结构）。
- **长程战略 (90天/热力图)**: 强制调用 garmin_chart.py 生成大屏：
  $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_chart.py" dashboard --period 90d
  （输出的绝对路径必须作为可点击链接返回）

## 2. <Contracts> (输出与交付契约)
- **四维评价体系**:
  1. 🟢 **系统动量**: 当前生理演化方向与摩擦定性。
  2. 📊 **执行带宽**: 认知带宽与物理防线评分，高压耗散与睡眠惩罚。
  3. ⚠️ **摩擦与风险**: 若出现患病指标必须标红高亮。
  4. 🎯 **战术指令**: 明确指令（降级/强攻/休眠）。
- **Telemetry 落盘**: 任务结束时，必须使用 write_to_file 将元数据以 JSON 格式保存至隔离沙盒：<appDataDir>\brain\<conversation-id>\scratch\telemetry.json，规避高频并发死锁。
- **交付链接契约**: 无论生成的是日常简报还是 HTML 大屏，主代理最后必须通过聊天框向用户输出可点击的 Markdown 链接（例如：[查看生物态势看板](file:///C:/Users/shich/...)）。

## 3. <Failure_Taxonomy> (失败分类学)
- **环境死锁与乱码 (Encoding Crash)**：调用 Python I/O 脚本时缺失 $env:PYTHONIOENCODING="utf-8" 前缀。
- **盲目捏造 (Data Forgery)**：禁止大模型凭空推演生理数据，一切评判必须锚定 SQLite 库的真实读取记录。
- **降级死锁 (Silent API Fallback)**：本地 SQLite 缺失时严禁静默 fallback，必须抛出错误并阻断瞎猜。
- **跳过前置同步 (Bypass Phase 0)**：无论提问，必须无条件优先跑通 Phase 0 同步脚本以确保时效性。
