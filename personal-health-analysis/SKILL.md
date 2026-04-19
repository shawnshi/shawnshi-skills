---
name: personal-health-analysis
description: Garmin 数据驱动的个人生理操作系统。用于分析心率、HRV、睡眠、压力、Body Battery、恢复、训练负荷、感冒迹象、执行准备度，以及 30-90 天健康趋势与决策看板；当用户询问“今天能不能练”“状态如何”“做个健康审计”“看趋势/热力图/90天复盘”等场景时启用。
---

# Personal Health Analysis (VNext Physiological Operating System)

这个技能不是泛健康闲聊器，而是基于 Garmin 数据的生理决策系统。目标不是生成漂亮结论，而是用本地数据湖、同步链路、分析引擎和看板层，给出可执行的恢复、训练、节奏管理与风险预警判断。

## 1. System Model

四层架构保持不变，但执行契约要更清楚：

- **Data Layer**: `GarminDB` / SQLite 本地历史库。承担基线、趋势和低延迟查询。
- **Adapter Layer**: [scripts/garmin_sqlite_adapter.py](scripts/garmin_sqlite_adapter.py)。把本地库转成标准化分析结构。
- **Intelligence Layer**: [scripts/garmin_intelligence.py](scripts/garmin_intelligence.py)。负责 readiness、flu risk、趋势判断、负荷解释等。
- **Presentation Layer**: [scripts/garmin_chart.py](scripts/garmin_chart.py)。负责把结果转成决策看板，而不是单纯趋势图。

核心原则：

1. **Local-first**: 能用本地 SQLite 就不用在线请求。
2. **Graceful degradation**: 同步失败不等于整条链失败，只要本地快照仍在可接受时效内，就继续执行。
3. **Action over prose**: 输出必须落到“今天/本周该做什么”。
4. **No fake medicine**: 禁止把生理推断表述成医学诊断。

## 2. Capability Contract

执行前先识别当前环境处于哪一层能力：

### Core
- 需要：本地 SQLite / GarminDB 数据可读。
- 能力：日度审计、趋势分析、readiness、flu risk、长期回顾。
- 优先级：最高。

### Sync
- 需要：可用的 Garmin 同步链路，例如 `garmindb_cli.py`。
- 能力：更新本地库，缩短数据延迟。
- 备注：这是增强层，不是唯一入口。

### Viz
- 需要：图表脚本依赖完整。
- 能力：生成 HTML 决策看板。
- 备注：看板失败不应阻塞文本结论。

如果 `Sync` 不可用但 `Core` 可用，继续执行并明确说明“基于本地快照”。
如果 `Core` 不可用且 `Sync` 也失败，才真正阻塞，并说明缺的依赖或数据源。

## 3. Execution Protocol

### Phase 0: Capability & Freshness Check
先检查三件事：

- 本地 SQLite 是否存在并可读。
- 本地数据是否在合理时效窗口内。
- 同步链路是否存在且可调用。

时效建议：

- `quick`: 当天或最近一次同步可用即可。
- `audit`: 最近 24 小时内的数据优先。
- `campaign`: 只要长周期数据完整即可，不要求强实时。

### Phase 1: Sync Gate (Degradable)
优先尝试同步本地库，但这是一个**可降级同步门**：

- 同步成功：使用最新数据。
- 同步失败，但本地快照仍在时效窗口内：继续执行，并明确标注“使用本地快照”。
- 同步失败，且本地库缺失或明显过期：阻塞，并说明不能给出可靠结论。

遇到 429、网络波动或上游熔断时，禁止把“同步失败”误判为“分析失败”。

### Phase 2: Intent Routing
根据用户问题把任务路由到 3 档输出模式：

#### `quick`
适用于“今天能不能练”“我昨晚睡得怎样”“今天状态如何”这类问题。

- 只提炼最少必要指标。
- 直接给结论。
- 输出要短，不扩展成长报告。

#### `audit`
适用于“健康审计”“今日/本周状态”“分析我的生理指标”。

- 输出结构化简报。
- 解释关键指标之间的关系。
- 给出今天和本周的行动建议。

#### `campaign`
适用于“90天趋势”“全面体检”“热力图”“长期负荷复盘”。

- 输出长周期趋势解释。
- 需要时调用看板。
- 必须标出系统演化方向，而不是只罗列指标。

### Phase 3: Analysis
优先调用 [scripts/garmin_intelligence.py](scripts/garmin_intelligence.py)。

分析时至少覆盖：

- 恢复状态：睡眠、HRV、RHR、Body Battery。
- 压力与耗散：压力暴露、恢复缺口、社会时差。
- 训练负荷：近期负荷、恢复承压、是否应减量或维持。
- 风险信号：异常疲劳、疑似感冒模式、持续性透支。

如果用户只问一个点，不要把整套框架全部展开。

### Phase 4: Executive Output
输出遵循以下原则：

- **BLUF first**: 第一行必须给结论。
- **Metrics second**: 只列出支撑结论的关键指标，不堆数据。
- **Actions third**: 给出今天/本周的具体动作。
- **Uncertainty last**: 明确指出数据缺口或可信度限制。

`campaign` 模式下，如果图表能力可用，调用 [scripts/garmin_chart.py](scripts/garmin_chart.py) 生成决策看板。
看板目标不是“展示所有图”，而是回答三个问题：

1. 当前系统是在恢复、持平还是恶化。
2. 哪个变量最拖后腿。
3. 接下来一周该减量、维持还是加量。

## 4. Result Gate

最终输出必须通过结果门，而不是风格门。至少满足以下 5 条：

1. **明确结论**: 回答必须能落到“能/不能”“该/不该”“偏绿/偏黄/偏红”。
2. **证据锚定**: 至少点明最关键的 2-4 个指标依据。
3. **动作可执行**: 至少给出一个今天可执行动作和一个本周节奏建议。
4. **不确定性披露**: 若数据缺失、快照过期、同步失败，必须显式说明。
5. **边界清晰**: 禁止把健康分析包装成临床诊断或治疗意见。

如果无法通过这 5 条，宁可缩短输出，也不要扩展成空洞长文。

## 5. Runtime Guardrails

- **禁止编造数据**。
- **禁止把平均值当趋势**，长周期结论必须参考基线变化或阶段对比。
- **禁止硬编码路径**。技能根目录应从当前 `SKILL.md` 所在位置或当前工作目录解析，不要假设 `.gemini` 或 `.codex` 固定存在。
- **禁止因图表失败而吞掉文本结论**。
- **禁止在无数据、无同步、无快照时给出强结论**。

## 6. Core Commands

在技能根目录下执行：

```bash
# 基础摘要
python scripts/garmin_data.py summary --days 7

# 恢复/准备度
python scripts/garmin_intelligence.py readiness --days 1
python scripts/garmin_intelligence.py insight_cn --days 7
python scripts/garmin_intelligence.py flu_risk --days 7

# 长期趋势 / 看板
python scripts/garmin_chart.py dashboard --days 7
python scripts/garmin_chart.py dashboard --period 90d
```

对于更细的时间点查询、FHIR 导出、FIT/GPX 分析、SpO2/呼吸率扩展命令，按需读取：
[references/advanced_tools.md](references/advanced_tools.md)

## 7. Installer Expectations

`install.ps1` 不应再被理解为“装完就全可用”。VNext 的执行预期是：

- 如果 `Sync` 层未准备好，明确说明当前只能基于本地库分析。
- 如果本地库也不存在，提示缺少 GarminDB / SQLite 数据源，而不是假装可以正常审计。
- 当用户需要修复安装链时，再进入依赖排查或脚本修订。

## 8. Output Templates

### `quick`
- 结论
- 依据
- 动作

### `audit`
- BLUF
- 恢复与压力
- 训练与节奏
- 风险与缺口
- 今日/本周动作

### `campaign`
- 总体趋势判断
- 关键驱动变量
- 风险窗口
- 30-90 天行动建议
- 看板路径（若生成成功）

## 9. Historical Failure Priors

- `IF [sync_failed AND local_snapshot_fresh] THEN [continue_with_snapshot]`
- `IF [sync_failed AND local_snapshot_missing] THEN [halt_with_dependency_gap]`
- `IF [mode == quick] THEN [forbid_long_report]`
- `IF [mode == campaign AND viz_available] THEN [prefer_dashboard]`
- `IF [medical_claim_without_data] THEN [halt]`
