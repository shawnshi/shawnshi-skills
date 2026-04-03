---
name: personal-health-analysis
description: 首席医疗官(CMO)级生理审计引擎。当用户提到“心率/睡眠/压力/HRV/感冒迹象/身体电量/健康审计/准备度/生理状态/健康洞察/运动分析/热力图/90天”等指标时务必激活。通过Garmin数据执行全链路审计与决策准备度管理。
---

# Personal Health Analysis (CMO/Strategic Architect Level)

通过自然语言查询 Garmin Connect 数据，提取临床级生理指标，生成**军工级交互式审计看板（Bloomberg Terminal 审美）**，并执行高级生理智能分析（认知准备度与代谢摩擦）。

该技能定位为“企业级/高管专属的前置医疗防线与战略决策引擎（对齐 `USER.md` 中的战略咨询总经理身份）”，采用 **GEB-Flow V2.0** 架构进行全链路审计：
- **Data Lake Layer** (`GarminDB`): 本地物理数据湖。通过 SQLite 存储历史基线，实现毫秒级查询。
- **Adapter Layer** (`garmin_sqlite_adapter.py`): 语义垫片。将本地 SQL 数据转换为标准化分析结构。
- **Intelligence Layer** (`garmin_intelligence.py`): 二阶战略审计分析。优先调用本地数据源，对抗 API 熔断。
- **Presentation Layer** (`garmin_chart.py`): 生成高密度、暗黑模式的 Tactical Command 战略大屏。

## Execution Protocol (智能体混合执行协议)

AI 必须严格按照以下阶段线性推进，并在模式之间流转：

- **[Phase 0: Data Sync & Pre-flight (PLANNING Mode)]**
  - **Action**: 隐式执行 `garmindb_cli.py --latest` 以尝试更新本地数据湖（确保命令在环境中可用）。
  - **Failsafe**: 如果遇到 429 报错，**不阻塞后续执行**，直接转入本地已有的 SQLite 库进行审计（即读取“历史快照”）。

- **[Phase 1: Precision Data Extraction (EXECUTION Mode)]**
  - **Action**: 优先调用 `garmin_intelligence.py` 加载本地数据。支持通过 `--period 90d` 提取长程宏观数据。
  - **Failsafe**: 如果本地库缺失，回退至 `garmin_data.py` 发起 API 请求。

- **[Phase 2: Strategic Synthesis (EXECUTION Mode)]**
  - **Action**: 调用 `garmin_intelligence.py` 执行深度诊断。
  - **Constraint**: 利用“耗散结构”计算每日高压耗散时长（Zone Dissipation），并追踪 30 天基线漂移。

- **[Phase 3: Executive Output (VERIFICATION Mode)]**
  - **Action**: 生成最终的高管简报，并调用 `garmin_chart.py` 生成战术级大屏。
  - **Constraint**: 输出必须锚定商业决策视角。HTML 大屏必须坚守“密不透风的高信息密度”与纯暗黑高对比度原则，严禁使用柔和的消费级圆角UI。

## ⚠️ Agentic Guardrails (智能体硬约束)
1. **No Hallucination**: 绝对禁止编造生理数据。
2. **Execution Context**: 执行脚本前，确保明确使用绝对路径（如 `C:\Users\shich\.gemini\skills\personal-health-analysis\scripts\garmin_data.py`）或在 `run_shell_command` 中使用 `dir_path` 切换到对应目录。
3. **Path Resolution**: 处理活动文件（FIT/GPX）和 HTML 报告时，必须使用绝对路径展示（例如：`[查看生物态势看板](file:///{user_root}/.gemini/memory/raw/garmin/tactical_board_7days_2026xxxx.html)`）。
4. **Pipelining**: `garmin_intelligence.py` 等分析脚本依赖基础数据正确返回。严格确保前序步骤成功后再执行后续的深度审计。

## Output Schema & Intent Routing (三级输出协议)

系统必须根据用户的提问意图，执行严格的降噪与分级输出：

### Level 1: 微观战术 (Micro-Tactics)
- **触发条件**：用户询问具体的单个问题，如“我今晚能练深蹲吗？”、“今天睡得好吗？”。
- **输出约束**：**绝对禁止**输出全量战略简报。仅调用 `readiness` 分析，提取认知/物理防线得分。用 **< 50字** 的军工级指令直接回答行或不行，并给出依据。

### Level 2: 日结复盘 (Daily Audit)
- **触发条件**：常规触发，如“健康审计”、“今日状态”、“分析生理指标”。
- **输出约束**：调用 `insight_cn`，输出完整的**四层模块文本简报**（包含 ASCII 系统动量拓扑）。必须采用 **BLUF (结论先行)** 结构。

### Level 3: 长程战略 (Strategic Campaign)
- **触发条件**：包含“90天”、“趋势”、“全面体检”、“热力图”等宏观宏大词汇。
- **输出约束**：除了文本解析，**强制**调用 `garmin_chart.py dashboard` 生成 HTML 大屏，并提供本地绝对路径链接。

---
**核心评价维度**：
- **🟢 系统动量 (System Momentum)**: 1句话概括当前的生理演化方向与摩擦定性。包含终端可视化的能量拓扑 `[ ▂▃▄▅ ]`。
- **📊 执行带宽 (Execution Bandwidth)**: 包含认知带宽与物理防线的双重评分，以及高压耗散时长、社会时差(Social Jetlag)的惩罚。
- **⚠️ 摩擦与风险 (Frictions & Risks)**: 如果探测到“Garmin Flu”（RHR飙升+HRV骤降+呼吸率异常）或严重睡眠剥夺，必须加粗高亮警告。
- **🎯 战术指令 (Tactical Directives)**: 明确指令：日程降级/强攻、物理干预（强制负熵/绝对防御）、生化环境（深度冷却/熔断）。

---

## Tooling Reference & Workflow

*注意：执行以下脚本时，请确保工作目录为 `C:\Users\shich\.gemini\skills\personal-health-analysis\` 或使用绝对路径。*

### 1. 核心指令 (Core Operations)
```bash
# 综合摘要与高阶洞察 (Level 2)
python scripts/garmin_data.py summary --days 7
python scripts/garmin_intelligence.py insight_cn --days 7

# 单项指标查询 (Level 1)
python scripts/garmin_data.py [sleep|hrv|heart_rate|body_battery|stress] --days 7
python scripts/garmin_intelligence.py readiness --days 1

# 军工级交互大屏 / 宏观趋势 (Level 3)
python scripts/garmin_chart.py dashboard --days 7
python scripts/garmin_chart.py dashboard --period 90d

# 探测"Garmin 感冒"模式
python scripts/garmin_intelligence.py flu_risk --days 7
```

### 2. 进阶分析与特殊命令 (Advanced Tools)
对于特定的深度需求（如：**时间点精确查询、FHIR 临床导出、FIT/GPX 活动文件分析、扩展指标 SpO2/呼吸率**），请阅读参考文件以获取具体指令：
👉 **参阅 [references/advanced_tools.md](references/advanced_tools.md)**

## Key Insights Reference

- **Executive Readiness (0-100)**: 综合睡眠质量、Body Battery 峰值、压力负荷。结合“睡眠债务”与“高压耗散时长 (Zone Dissipation)”进行宏观衰竭扣分。
- **System Momentum**: 通过切割周期的前半段与后半段，计算 RHR 与 Stress 的 Delta 差值，判定系统是在“超量恢复”还是“熵增恶化”。
- **"Garmin Flu" Pattern**: 患病前 24-48h 的生理特征：RHR 飙升 (>3-5 bpm)、HRV 骤降 (>10-15%)、以及 **睡眠呼吸率异常升高 (>0.5 brpm)**。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "personal-health-analysis", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- **[EXPLICIT_SYNC_PATH]**: Win32 环境下 `garmindb_cli.py` 不在全局 PATH 中，且单纯 `--latest` 无效。必须强制执行全量增量指令：`python C:\Users\shich\AppData\Local\Programs\Python\Python313\Scripts\garmindb_cli.py --download --import --analyze --all --latest`。
