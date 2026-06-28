---
name: personal-health-analysis
version: 10.0.0
tier: action-allowed
description: 'CMO级生理健康审计引擎 (Loop Engineering Edition)。通过 Garmin 本地数据湖极速执行全链路审计与决策准备度管理。支持热力图、PMC 负荷与异步自愈同步。'
triggers: ["心率", "睡眠", "压力", "HRV", "身体电量", "健康审计", "生理状态", "运动分析"]
---

<strategy-gene>
Keywords: 生理健康审计, 执行带宽, 系统动量, Garmin Flu, Loop Engineering, 异步自愈
Summary: 提取临床级生理指标并执行耗散结构分析，判定当前系统的认知准备度与战术动量。
Strategy:
1. 1. 异步数据泵 (Async Data Pump)：主代理应直接查询本地 SQLite 进行光速响应。若引擎返回 `is_stale: true`，请将 `sync_health_data.py` 推入后台执行 (`WaitMsBeforeAsync=5000`) 并交还控制权，实现“人退场，环自转”。
2. 2. 动量与负荷 (PMC & Momentum)：提取 VO2 Max、CTL/ATL/TSB 等深层指标，判定系统处于超量恢复还是结构性耗散。
3. 3. 分级输出：微观问题 < 50 字指令；日结给出四层文本简报；长程战略强制 HTML 大屏。
AVOID: 绝对禁止编造生理数据；本地库缺失时严禁静默 fallback（Fail-Fast）；严禁通过前台同步阻塞主代理 10 分钟。
</strategy-gene>

# Personal Health Analysis (CMO Level V10.0 Loop Engineering)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (提取核心指标或调用智能诊断脚本。注意：该操作基于本地 SQLite，极速响应)
2. **[条件分支]** 若诊断结果 JSON 中包含 `"is_stale": true` 或用户明确要求刷新：
   - 立即通过 `run_command` (设置 WaitMsBeforeAsync=5000 或更大) 将 `sync_health_data.py` 推入后台 (Background Task)。
   - 不必等待同步完成，直接向用户交付基于历史快照的审计报告，并在报告顶部温馨提示：“后台数据同步链路已拉起，本次报告基于昨日快照...”。
3. `run_command` (可选：生成大屏或长程视图)
4. `write_to_file` (写入遥测沙盒数据)

## 1. 核心流程与架构 (The Protocol)
主代理必须严格按照以下阶段推进：

### Phase 0: Local-First Query (本地极速优先)
- 不再要求同步先行。直接跳至 Phase 1/2。因为 SQLite 数据读取耗时 < 100ms。
- 若需同步，使用异步流：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\sync_health_data.py"
   ```
- **自愈防线 (Auto-Healing)**: `sync_health_data.py` 已内置自我修复逻辑，遇到 Cloudflare/Login 拦截会自动 `pip install --upgrade garminconnect` 并重试，无需主代理干预。

### Phase 1: Precision Data Extraction (核心数据提取)
根据用户的提问深度，使用原生 `run_command` 调用对应的工具箱（带上 UTF-8 编码锁）。
- **单项指标**: 
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" [sleep|hrv|heart_rate|body_battery|stress] --days 7
   ```
- **综合摘要**: 
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_data.py" summary --days 7
   ```
- **准备度查询**: 
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" readiness --days 1
   ```
- **Flu 疾病探测**: 
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" flu_risk --days 7
   ```

### Phase 2: Strategic Synthesis (战略级综合诊断)
- 常规复盘或深层体检，调用：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" insight_cn --days 7
   ```
- **诊断聚焦**: 提取 Executive Readiness (0-100)、提取 PMC 训练负荷 (VO2 Max, CTL, TSB)、利用耗散结构计算高压耗散时长、重点探测患病模式（RHR 飙升 + HRV 骤降 + 呼吸率异常升高）。

### Phase 3: Executive Output (高管级降噪输出)
- **微观问题**: 精简的指令，直接回答行不行，禁止废话。
- **日结复盘**: 输出四层模块文本简报（采用 BLUF 结构）。
- **长程战略 (90天/热力图)**: 强制调用 `garmin_chart.py` 生成大屏：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_chart.py" dashboard --period 90d
   ```
  （生成的绝对路径必须作为可点击 Markdown 链接返回）

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
- **同步死锁 (Sync Deadlock)**：严禁主代理通过 polling 等待 `sync_health_data.py`。该任务必须异步。
- **缺失属性 (Missing Attributes)**：若 DB 不包含 `attributes` 表，VO2 Max 将返回 `--`，这属于正常现象。
