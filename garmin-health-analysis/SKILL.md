---
name: garmin-health-analysis
description: Talk to your Garmin data naturally - "what was my fastest speed snowboarding?", "how did I sleep last night?", "what was my heart rate at 3pm?". Access 20+ metrics (sleep stages, Body Battery, HRV, VO2 max, training readiness, body composition, SPO2), download FIT/GPX files for route analysis, query elevation/pace at any point, and generate interactive health dashboards. From casual "show me this week's workouts" to deep "analyze my recovery vs training load".
---

# Garmin Health Analysis (GEB-Flow)

通过自然语言查询 Garmin Connect 数据，生成交互式 HTML 图表，并执行高级生理智能分析。

## Architecture Vision
该技能采用 **GEB-Flow** 架构：
- **Auth Layer** (`garmin_auth.py`): 登录认证与 Token 管理。
- **Data Layer** (`garmin_data.py`, `garmin_data_extended.py`): 原始 JSON 数据提取，覆盖 20+ 指标。
- **Query Layer** (`garmin_query.py`): 时间点精确查询（如"下午3点心率"）。
- **Activity Files** (`garmin_activity_files.py`): FIT/GPX/TCX 文件下载与深度解析。
- **Intelligence Layer** (`garmin_intelligence.py`): 二阶分析（患病风险预警、决策准备度、完整审计）。
- **Presentation Layer** (`garmin_chart.py`): 生成交互式 Bio-Metric Audit 看板。
- **FHIR Adapter** (`garmin_fhir_adapter.py`): 导出 HL7 FHIR 标准格式。

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
# 综合摘要（含所有核心指标）
python scripts/garmin_data.py summary --days 7

# 单项指标
python scripts/garmin_data.py sleep --days 14
python scripts/garmin_data.py hrv --days 7
python scripts/garmin_data.py heart_rate --days 7
python scripts/garmin_data.py body_battery --days 7
python scripts/garmin_data.py stress --days 7
python scripts/garmin_data.py activities --days 30
python scripts/garmin_data.py profile
```

### 2. 扩展指标 (Extended Metrics)
```bash
# 训练相关
python scripts/garmin_data_extended.py training_readiness --date 2026-02-21
python scripts/garmin_data_extended.py training_status --date 2026-02-21
python scripts/garmin_data_extended.py max_metrics --date 2026-02-21
python scripts/garmin_data_extended.py endurance_score
python scripts/garmin_data_extended.py hill_score

# 身体成分
python scripts/garmin_data_extended.py body_composition --date 2026-02-21
python scripts/garmin_data_extended.py weigh_ins --start 2026-01-01 --end 2026-02-21

# 日内详细数据
python scripts/garmin_data_extended.py spo2 --date 2026-02-21
python scripts/garmin_data_extended.py respiration --date 2026-02-21
python scripts/garmin_data_extended.py steps --date 2026-02-21
python scripts/garmin_data_extended.py floors --date 2026-02-21
python scripts/garmin_data_extended.py intensity_minutes --date 2026-02-21
python scripts/garmin_data_extended.py hydration --date 2026-02-21
python scripts/garmin_data_extended.py stress_detailed --date 2026-02-21
python scripts/garmin_data_extended.py hr_intraday --date 2026-02-21
```

### 3. 时间点精确查询 (Point-in-Time Query)
当用户问"我下午3点心率多少？"时：
```bash
python scripts/garmin_query.py heart_rate "3:00 PM" --date 2026-02-21
python scripts/garmin_query.py stress "15:00" --date 2026-02-21
python scripts/garmin_query.py body_battery "9:00 AM"
python scripts/garmin_query.py steps "18:00"
```

### 4. 活动文件分析 (Activity File Analysis)
当用户问"我上次滑雪最快时速？"或"跑步第5公里的海拔？"时：
```bash
# 下载活动文件
python scripts/garmin_activity_files.py download --activity-id 12345678 --format fit
python scripts/garmin_activity_files.py download --activity-id 12345678 --format gpx

# 解析文件（提取全部数据点）
python scripts/garmin_activity_files.py parse --file C:\Users\shich\.gemini\memory\garmin\activity_12345678_20260223_130000.fit

# 按距离查询（如"5公里处的数据"）
python scripts/garmin_activity_files.py query --file C:\Users\shich\.gemini\memory\garmin\activity_12345678_20260223_130000.fit --distance 5000

# 按时间查询
python scripts/garmin_activity_files.py query --file C:\Users\shich\.gemini\memory\garmin\activity_12345678_20260223_130000.fit --time "2026-02-21T14:30:00"

# 活动统计分析
python scripts/garmin_activity_files.py analyze --file C:\Users\shich\.gemini\memory\garmin\activity_12345678_20260223_130000.fit
```

### 5. 生理智能分析 (Advanced Analysis)
```bash
# 探测"Garmin 感冒"模式（RHR 上升 + HRV 下降）
python scripts/garmin_intelligence.py flu_risk --days 7

# 高阶决策准备度（认知端 + 物理端双维度）
python scripts/garmin_intelligence.py readiness --days 1

# 完整生理审计（系统状态 → 恢复环路 → 负荷摩擦 → 行动协议）
python scripts/garmin_intelligence.py audit --days 7

# 中文专家级综合洞察报告
python scripts/garmin_intelligence.py insight_cn --days 7
```

### 6. 交互式看板 (Dashboard & Charts)
```bash
# 完整仪表盘（含全部图表 + 审计报告）
python scripts/garmin_chart.py dashboard --days 7

# 单项图表
python scripts/garmin_chart.py sleep --days 14
python scripts/garmin_chart.py hrv --days 7
python scripts/garmin_chart.py body_battery --days 7
python scripts/garmin_chart.py stress --days 7
python scripts/garmin_chart.py activities --days 30
python scripts/garmin_chart.py load --days 7

# 运行不带 --output 则会自动保存至 C:\Users\shich\.gemini\memory\garmin 并打开
python scripts/garmin_chart.py dashboard --days 7

# 手动指定保存路径
python scripts/garmin_chart.py dashboard --days 7 --output C:\Users\shich\.gemini\memory\garmin\report.html
```

### 7. 临床互操作 (FHIR Export)
当用户要求导出给医生看时：
```bash
python scripts/garmin_fhir_adapter.py hrv --days 30
python scripts/garmin_fhir_adapter.py rhr --days 30
python scripts/garmin_fhir_adapter.py sleep --days 14
python scripts/garmin_fhir_adapter.py stress --days 7
```

## User Query Mapping

| User Question | Tooling Strategy |
|---------------|------------------|
| "我生病了吗？" / "有没有感冒迹象" | `garmin_intelligence.py flu_risk --days 7` |
| "今天适合开会/做决策吗？" | `garmin_intelligence.py readiness` |
| "我最近身体怎么样？" | `garmin_intelligence.py insight_cn --days 7` |
| "看看我上周的运动看板" | `garmin_chart.py dashboard --days 7` |
| "我昨晚睡得怎么样？" | `garmin_data.py sleep --days 1` |
| "最近7天的 HRV 趋势" | `garmin_data.py hrv --days 7` 或 `garmin_chart.py hrv --days 7` |
| "我下午3点心率多少？" | `garmin_query.py heart_rate "3:00 PM"` |
| "我今天的血氧数据" | `garmin_data_extended.py spo2` |
| "我的体重变化趋势" | `garmin_data_extended.py weigh_ins --start YYYY-MM-DD --end YYYY-MM-DD` |
| "上次跑步最快配速?" | 先 `garmin_data.py activities` 获取 ID → `garmin_activity_files.py download` → `analyze` |
| "我的 VO2 Max 多少？" | `garmin_data_extended.py max_metrics` |
| "训练准备度如何？" | `garmin_data_extended.py training_readiness` |
| "导出数据给医生" | `garmin_fhir_adapter.py hrv/rhr/sleep/stress --days N` |
| "生成完整健康审计报告" | `garmin_intelligence.py audit --days 7` 或 `garmin_chart.py dashboard --days 7` |

## Key Insights Reference

- **Executive Readiness (0-100)**: 综合睡眠质量(40%)、Body Battery 峰值(40%)及压力负荷(20%)得出的决策能量得分。分为认知端（REM、HRV、压力）和物理端（深睡、BB、RHR）两个维度。
- **Stress Index (0-100)**: 全天压力负荷。低值 (0-25) 通常代表休息或高效专注，高值 (>50) 代表生理/心理消耗。
- **"Garmin Flu" Pattern**: 患病前 24-48h 的生理特征：RHR 飙升 (>3-5 bpm) 且 HRV 骤降 (>10-15%)。
- **Action Protocol**: 基于综合生理状态分为绿灯 (推极限)、黄灯 (维护运转)、红灯 (主动刹车)、警报 (停机) 四级。

## Troubleshooting
- **Missing Data**: 确认设备已同步至 Garmin Connect。
- **401 Error**: Token 过期，重新运行 `garmin_auth.py login`。
- **File Not Found**: 检查 `C:\Users\shich\.gemini\memory\garmin` 目录，生成的 HTML/活动文件存放在该处。
- **Windows 路径**: 报告和活动文件默认保存到 `C:\Users\shich\.gemini\memory\garmin` 目录。
