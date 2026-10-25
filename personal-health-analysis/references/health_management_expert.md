# 个人健康管理专家方法论与深度归因协议（Expert Playbook）

本参考定义如何利用本地多库生理资产（`garmin.db`、`garmin_monitoring.db`、`garmin_activities.db`、`garmin_summary.db`）与模型生理学推演能力，将穿戴数据转化为**非诊断性、个体化（N-of-1）、可验证的个人健康管理方案**。

---

## 1. 一键专家引擎入口（确定性多库聚合）

在完成 `runtime_preflight.py --mode local` 预检并获得当前请求的健康读取授权后，优先调用多库专家合成引擎（保留全部既有 `garmin_data.py`、`garmin_intelligence.py`、`garmin_health_profile.py` 与 `garmin_chart.py` 功能）：

```bash
<SKILL_PYTHON> scripts/garmin_expert_advisor.py --days 14 --source local --allow-health-data
```

该引擎在只读事务与全库前后 SHA-256 完整性校验下，一次性提取并对齐四大维度：
1. **多时间尺度个人基线（`multi_horizon_baselines`）**：自动计算 7 日急性窗、28 日滚动窗与 90 日季节性基线的均值、中位数、标准差与 Z-score，并提取 Garmin 原生动态 HRV 走廊（`hrv_baseline_low` .. `hrv_baseline_upper`）、7 日均值（`hrv_weekly_avg`）及副交感天花板储备（`hrv_ceiling_spread = hrv_5min_high - hrv_last_night`）。
2. **夜间 5 分钟级 HRV 恢复斜率与睡眠微结构（`intra_night_hrv` & `sleep_micro_architecture`）**：
   - 跨库对齐 `garmin_monitoring.db` 的 `monitoring_hrv_value`（每 5 分钟采样）与睡眠起止窗口，拆解**前半夜 HRV 均值（`first_half_hrv_avg`）**与**后半夜 HRV 均值（`second_half_hrv_avg`）**及恢复斜率（`intra_night_hrv_slope`）；
   - 从 `sleep_events` 提取夜间微觉醒次数（`awake_episode_count`）、前半夜深睡集中度（`deep_first_half_pct`）与睡眠阶段转换频次。
3. **昼夜分段压力动力学（`circadian_stress`）**：
   - 从分钟级 `stress` 表聚合上午（`08:00–12:00`）、下午（`12:00–18:00`）、傍晚（`18:00–21:00`）与**睡前 2 小时卸载窗口（`21:00–23:00`）**的压力均值及卸载差值（`wind_down_delta_vs_afternoon`）。
4. **心肺代谢与周期化负荷（`cardiorespiratory_and_activity_load`）**：
   - 提取 `VO2max`、7 日/28 日训练负荷、WHO 周累计中高强度活动分钟数（`7d_mvpa_minutes` vs 150 分钟目标）、日均步数与体重轨迹。

---

## 2. 四层专家推演框架（Model Reasoning Protocol）

模型在拿到 `garmin_expert_advisor.py` 的结构化 JSON 后，不再仅做逐字段数字播报，必须按以下四层结构开展专业推演：

### 第一层：基线定位与稳态负荷定性（Allostatic Load Positioning）
- **双锚点对照**：同时对照**个人 28d/90d 统计基线（Z-score）**与 **Garmin 原生生理走廊（`hrv_baseline_low`–`hrv_baseline_upper`）**。
- **天花板储备解读**：若 `hrv_last_night` 偏低但 `hrv_5min_high` 仍高（`ceiling_spread ≥ 20 ms`），说明副交感神经最大潜能未受损，仅前半夜受日间余波或晚间代谢抑制；若 `hrv_5min_high` 与 `hrv_last_night` 同步坍缩（如 `ceiling_spread < 10 ms`），提示深层交感持续占优或系统性恢复受阻。

### 第二层：跨时段因果机制链重构（Diurnal-to-Nocturnal Mechanism Chain）
将**前一日日间/睡前负荷**与**当夜微结构**及**次日晨起状态**串联成闭环机制链：
- `日间压力分布（08:00–18:00） + 睡前 2 小时（21:00–23:00）交感卸载程度`
  $\rightarrow$ `前半夜 HRV 均值（first_half_hrv_avg）与前半夜深睡集中度（deep_first_half_pct）`
  $\rightarrow$ `睡眠期平均压力（sleep_stress）与每小时睡眠电量回充率（bb_recharge_per_sleep_h）`
  $\rightarrow$ `次日晨起最高身体电量（bb_max）与静息心率（rhr）`。

### 第三层：非诊断性生理表型识别（Physiological Phenotyping）
根据多指标协同方向识别当前主导表型（严格保持非医疗诊断边界）：
1. **`AUTONOMIC_RECOVERY_ROBUST`（迷走张力充沛/稳态恢复期）**：HRV 位于走廊中上段（Z > +0.5），前半夜深睡占比 ≥ 75%，晨起 Body Battery ≥ 75。
2. **`PRE_SLEEP_SYMPATHETIC_CARRYOVER`（睡前交感残留/前半夜恢复延迟型）**：总睡眠时长尚可，但 `21:00–23:00` 压力 ≥ 20，导致前半夜 HRV 显著低于后半夜（`first_half_hrv_avg` 压低），深睡后移或微觉醒增加。
3. **`TRANSIENT_VAGAL_FLOOR_TOUCH`（急性负荷冲击/走廊探底型）**：高强度脑力或差旅后单夜 HRV 触及 `baseline_low`，RHR 较 28d 均值上浮 1–3 bpm。
4. **`LOW_AEROBIC_VOLUME_GAP`（高脑力久坐/有氧卸载不足型）**：日间压力偏高而日均步数 < 6,500、周 MVPA < 150 分钟，缺乏运动诱导的副交感反跳。
5. **`PRODROMAL_STRAIN_WATCH`（多维生理应激预警）**：RHR 显著升高（Z ≥ +1.5）+ HRV 跌破走廊下沿 + 夜间呼吸率（`sleep_rr`）较 28d 中位数升高 ≥ 1.0 次/分，提示身体处于显著生理应激，建议主动减负并观察体感症状。

### 第四层：四维可验证健康管理处方（N-of-1 Verifiable Playbook）
所有管理建议必须具体到**触发阈值、时间窗口、量化剂量与下一次 Garmin 验证指标**（以条件式策略与参考方案呈现，不作强制医疗或强制行政命令）：
1. **认知与日程配速（Cognitive & Schedule Pacing）**：基于当日晨起 `bb_max` 与夜间 HRV 走廊位置，划分高认知攻坚窗口（如 09:00–12:00）与午后神经卸载窗口（NSDR / 散步微间歇）。
2. **睡眠与昼夜节律处方（Sleep & Circadian Hygiene）**：基于个人 28d 平均入睡时点（`bedtime_28d_mean_clock`）向前推算 120 分钟，设定高认知工作、强蓝光与进食截断时点，控制 `21:00–23:00` 睡前压力 ≤ 16。
3. **运动与恢复周期化（Exercise & Recovery Periodization）**：结合当前自主神经恢复状态与周 MVPA 缺口，给出精确心率区间（如 Zone 2 115–132 bpm 每次 35–45 分钟，或恢复日柔韧/散步）与久坐打断频率。
4. **N-of-1 闭环核验指标（Verification Targets）**：明确列出未来 1–7 天同步 Garmin 数据时用于检验处方是否奏效的客观指标及目标阈值（如 `first_half_hrv_avg ≥ 38 ms`、`pre_sleep_21_23 ≤ 16`、`bb_recharge_per_sleep_h ≥ 7.5`）。
