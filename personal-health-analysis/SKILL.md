---
name: personal-health-analysis
version: 8.2.0
description: 首席医疗官(CMO)级生理健康审计引擎。当用户提到“心率/睡眠/压力/HRV/感冒迹象/身体电量/健康审计/准备度/生理状态/健康洞察/运动分析/热力图/90天”等指标时务必激活。通过Garmin数据执行全链路审计与决策准备度管理。
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

# Personal Health Analysis (CMO Level V8.2 Native)

本技能定位为“高管专属的前置医疗防线与战略决策引擎”，采用 **GEB-Flow V2.0** 架构进行全链路审计：通过本地物理数据湖 (GarminDB) 实现毫秒级查询，配合高级生理智能分析判定认知准备度与代谢摩擦。

## 1. 核心流程与架构 (The Protocol)

主代理必须严格按照以下阶段线性推进：

### Phase 0: Data Sync & Pre-flight (同步先行) [Mode: PLANNING]
- **强制动作**: 在做任何分析前，主代理必须使用原生 `run_command` 执行同步脚本尝试更新本地数据湖。
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\sync_health_data.py"`
- **降级防线**: 如果遇到 API 429 限流报错，**不阻塞后续执行**，系统会自动转入已有的本地 SQLite 库进行审计（读取历史快照）。

### Phase 1: Precision Data Extraction (核心数据提取) [Mode: EXECUTION]
根据用户的提问深度，使用原生 `run_command` 调用对应的工具箱（务必带上 UTF-8 编码锁）。
- **单项指标 (Level 1)**: `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" [sleep|hrv|heart_rate|body_battery|stress] --days 7`
- **综合摘要 (Level 2)**: `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" summary --days 7`
- **准备度查询**: `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" readiness --days 1`
- **Flu 疾病探测**: `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" flu_risk --days 7`

### Phase 2: Strategic Synthesis (战略级综合诊断) [Mode: EXECUTION]
- 对于常规的日结复盘或深层体检，调用：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" insight_cn --days 7`
- **诊断聚焦**: 必须提取 `Executive Readiness (0-100)`、利用耗散结构计算高压耗散时长、并重点探测“Garmin Flu”患病模式（RHR 飙升 + HRV 骤降 + 呼吸率异常升高）。

### Phase 3: Executive Output (高管级降噪输出) [Mode: VERIFICATION]
- **微观问题**: < 50 字军工级指令，直接回答行不行，禁止废话。
- **日结复盘**: 输出四层模块文本简报（必须采用 BLUF 结构）。
- **长程战略 (90天/热力图)**: 强制调用 `garmin_chart.py` 生成大屏：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_chart.py" dashboard --period 90d`
  （HTML大屏链接必须以绝对物理路径返回给用户：`[查看生物态势看板](file:///C:/Users/shich/.gemini/MEMORY/raw/garmin/tactical_v2_...)`）

## 2. <Contracts> (输出与交付契约)
- **四维评价体系**:
  1. 🟢 **系统动量**: 当前生理演化方向与摩擦定性。
  2. 📊 **执行带宽**: 认知带宽与物理防线评分，高压耗散与睡眠惩罚。
  3. ⚠️ **摩擦与风险**: 如果出现 Garmin Flu 必须标红高亮。
  4. 🎯 **战术指令**: 明确指令（降级/强攻/休眠）。
- **Telemetry 落盘**: 任务结束时，使用 `write_to_file` 工具将元数据以 JSON 格式保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **幻觉工具调用 (Tool Hallucination)**：严禁使用伪命令 `run_shell_command`，必须走 `run_command`。严禁使用 `write_file`，必须走 `write_to_file`。
- **路径与编码崩溃 (Pathing & Encoding Deadlocks)**：严禁使用相对路径或非法的 `C:\Users\shich\.gemini\skills\...`（漏掉 config 目录）。所有 Python 脚本的调用必须钉死在 `C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\...` 并在头部悬挂 `$env:PYTHONIOENCODING="utf-8"`。
- **盲目捏造 (Data Forgery)**：绝对禁止大模型凭空推演生理数据，一切评判必须锚定 SQLite 库的真实读取记录。
- **降级死锁 (Silent API Fallback)**：`[FAIL_FAST_MANDATE]`：如果在读取本地 SQLite 数据湖时发生路径或缺失错误，严禁静默降级去无脑调取在线 API！必须抛出 `Critical Path Error` 并阻断大模型的瞎猜，防止整个视图层逻辑坍塌。
- **跳过前置同步 (Bypass Phase 0)**：`[MANDATORY_PHASE_0]`：只要用户发起健康请求，主代理必须无条件优先跑通 Phase 0 同步脚本。历史上曾发生过因跳过同步读取了过期老数据，导致大病前夕误判绿灯的严重事故。
