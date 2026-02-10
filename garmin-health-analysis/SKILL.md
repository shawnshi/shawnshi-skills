---
name: garmin-health-analysis
description: Talk to your Garmin data naturally - "what was my fastest speed snowboarding?", "how did I sleep last night?", "what was my heart rate at 3pm?". Access 20+ metrics (sleep stages, Body Battery, HRV, VO2 max, training readiness, body composition, SPO2), download FIT/GPX files for route analysis, query elevation/pace at any point, and generate interactive health dashboards. From casual "show me this week's workouts" to deep "analyze my recovery vs training load".
---

# Garmin Health Analysis (GEB-Flow)

通过自然语言查询 Garmin Connect 数据，生成交互式 HTML 图表，并执行高级生理智能分析。

## Architecture Vision
该技能采用 **GEB-Flow** 架构：
- **Data Layer** (`garmin_data.py`): 原始 JSON 数据提取。
- **Intelligence Layer** (`garmin_intelligence.py`): 二阶分析（如患病风险预警、决策准备度）。
- **Presentation Layer** (`garmin_chart.py`): 生成交互式看板。

## Authentication & Session
**CRITICAL**: 如果脚本返回 401 错误，说明 Token 已过期。
**Action**: 引导用户运行：
```bash
python scripts/garmin_auth.py login --email YOUR_EMAIL --password YOUR_PASSWORD
```
使用 `python scripts/garmin_auth.py status` 可检查当前登录状态。

## Standard Workflows

### 1. 基础查询 (Raw Data)
```bash
python scripts/garmin_data.py summary --days 7
python scripts/garmin_data.py sleep --days 14
```

### 2. 生理智能分析 (Advanced Analysis)
当用户询问“我最近身体怎么样”或“我有没有生病”时：
```bash
# 探测“Garmin 感冒”模式（静息心率上升 + HRV 下降）
python scripts/garmin_intelligence.py flu_risk --days 7

# 计算高阶决策准备度（基于睡眠、BB 和压力）
python scripts/garmin_intelligence.py readiness --days 1
```

### 3. 临床互操作 (FHIR Export)
当用户要求导出给医生看时：
```bash
# 导出 HRV 或 RHR 为 FHIR Observations
python scripts/garmin_fhir_adapter.py hrv --days 30
```

## User Query Mapping

| User Question | Tooling Strategy |
|---------------|-------------------|
| "我生病了吗？" | `scripts/garmin_intelligence.py flu_risk --days 7` |
| "今天适合开会/做决策吗？" | `scripts/garmin_intelligence.py readiness` |
| "看看我上周的运动看板。" | `scripts/garmin_chart.py dashboard --days 7` |
| "我昨晚睡得怎么样？" | `scripts/garmin_data.py summary --days 1` |

## Key Insights Reference

- **Executive Readiness (0-100)**: 综合睡眠质量(40%)、Body Battery 峰值(40%)及压力负荷(20%)得出的决策能量得分。
- **"Garmin Flu" Pattern**: 患病前 24-48h 的生理特征：RHR 飙升 (>3-5 bpm) 且 HRV 骤降 (>10-15%)。

## Troubleshooting
- **Missing Data**: 确认设备已同步。
- **File Not Found**: 检查 `output/` 目录，生成的 HTML 通常存放在该处。
