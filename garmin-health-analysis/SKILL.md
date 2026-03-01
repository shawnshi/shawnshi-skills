---
name: garmin-health-analysis
description: 私人首席医疗官(CMO)与生理战略引擎。基于客观数据执行全链路深度审计，管理高阶决策准备度与系统性战略风险。
category: analysis
execution_mode: hybrid
triggers: ["心率", "睡眠", "压力", "HRV", "感冒迹象", "身体电量", "健康审计", "准备度", "生理状态"]
---

# Garmin Health Analysis (CMO/Strategic Architect Level)

通过自然语言查询 Garmin Connect 数据，提取临床级生理指标，生成战略级交互式审计看板，并执行高级生理智能分析（认知准备度与代谢摩擦）。

该技能定位为“企业级/高管专属的前置医疗防线与战略决策引擎”，采用 **GEB-Flow** 架构进行全链路审计：
- **Auth Layer** (`garmin_auth.py`): 登录认证与 Token 管理。
- **Data Layer** (`garmin_data.py`, `garmin_data_extended.py`): 原始 JSON 数据提取，覆盖 20+ 指标。
- **Query Layer** (`garmin_query.py`): 时间点精确查询。
- **Activity Files** (`garmin_activity_files.py`): FIT/GPX/TCX 文件下载与解析。
- **Intelligence Layer** (`garmin_intelligence.py`): 二阶战略审计分析（三因子患病风险预警、基于睡眠债务扣分的决策准备度）。
- **Presentation Layer** (`garmin_chart.py`): 生成交互式 Bio-Metric Audit 看板，包含高阶 RHR vs HRV 韧性四象限分析。
- **FHIR Adapter** (`garmin_fhir_adapter.py`): 导出 HL7 FHIR 标准格式。

## Execution Protocol (智能体执行协议)

AI 必须严格按照以下阶段线性推进，禁止跳步：

- **[Phase 0: Pre-flight & Auth (PLANNING Mode)]**
  - **Action**: 在执行任何数据查询前，隐式检查当前是否有 401 Error 风险。如果脚本返回 401 错误，说明 Token 已过期。
  - **Failsafe**: 立即中断后续流程，引导用户运行 `python scripts/garmin_auth.py login --email YOUR_EMAIL --password YOUR_PASSWORD`。系统支持 `python scripts/garmin_auth.py status` 检查状态。

- **[Phase 1: Precision Data Extraction (EXECUTION Mode)]**
  - **Action**: 根据用户意图（User Query Mapping）选择最匹配的 1-2 个基础脚本（优先使用时间点精确查询或单项指标查询）。
  - **Constraint**: 避免一次性拉取所有全局数据（如同时运行多个 30 天的大范围查询）以防止 Token OOM 和上下文污染。

- **[Phase 2: Strategic Synthesis (EXECUTION Mode)]**
  - **Action**: 若涉及综合诊断（如准备度、患病风险），必须调用 `garmin_intelligence.py` 进行高阶计算。
  - **Constraint**: 数据层结果必须交由 Intelligence 模型层二次加工。

- **[Phase 3: Executive Output (VERIFICATION Mode)]**
  - **Action**: 生成最终的高管简报，并在必要时使用 `garmin_chart.py` 生成可视化报告的本地绝对路径链接供用户点击。

## ⚠️ Agentic Guardrails (智能体约束)
1. **No Hallucination**: 绝对禁止编造生理数据。如果 API 返回空值，必须报告“数据未同步”，并要求用户打开 Garmin Connect 手机端进行同步。
2. **Path Resolution**: 处理活动文件（FIT/GPX）和 HTML 报告时，必须使用绝对路径展示（例如：`[查看生物态势看板](file:///C:/Users/shich/.gemini/memory/garmin/report.html)`）。所有报告和活动文件默认保存至 `C:\Users\shich\.gemini\memory\garmin`。
3. **Pipelining**: `garmin_intelligence.py` 等分析脚本依赖基础数据正确返回。必须确保前置 API 调用不报错后再执行高阶审计。

## Output Schema (战略级输出规范)
必须采用 **BLUF (结论先行)** 结构输出结果：
- **🟢 核心判断 (Core Insight)**: 1句话概括当前的生理状态与决策建议。
- **📊 关键指标 (Key Metrics)**: 使用 Bullet points 列出核心数据（例如 RHR, HRV, 准备度, Body Battery）。
- **⚠️ 摩擦与风险 (Frictions & Risks)**: 如果探测到“Garmin Flu”迹象（RHR 飙升 + HRV/睡眠质量骤降 + 睡眠呼吸率异常升高）或睡眠剥夺严重，必须加粗高亮警告。
- **🎯 行动协议 (Action Protocol)**: 基于综合生理状态给出明确指令：绿灯 (推极限/商业破局)、黄灯 (维护运转)、红灯 (警示/限制交叉会议)、警报 (停机/深度对抗应激)。

---

## Tooling Reference & Workflow

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
| "我生病了吗？" / "有没有感冒迹象" | `garmin_intelligence.py flu_risk --days 7` (结合呼吸频率三因子验证)|
| "今天适合开会/做重大战略决策吗？" | `garmin_intelligence.py readiness` |
| "执行高管全链路健康审计" | `garmin_intelligence.py insight_cn --days 14` |
| "生成我的生物态势看板" | `garmin_chart.py dashboard --days 14` (含四象限图)|
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

- **Executive Readiness (0-100)**: 综合睡眠质量(40%)、Body Battery 峰值(40%)及压力负荷(20%)得出的决策能量得分。结合“睡眠债务”进行宏观衰竭扣分。
- **Stress Index (0-100)**: 全天压力负荷。
- **"Garmin Flu" Pattern**: 患病前 24-48h 的生理特征：RHR 飙升 (>3-5 bpm)、HRV 骤降 (>10-15%)、以及 **睡眠呼吸率异常升高 (>0.5 brpm)**。
- **Action Protocol**: 基于综合生理状态分为绿灯 (推极限/商业破局)、黄灯 (维护运转)、红灯 (警示/限制交叉会议)、警报 (停机/深度对抗应激) 四级。
