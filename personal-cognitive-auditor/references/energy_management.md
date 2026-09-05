# 能量管理数据合同

本文件约束复盘中的“能量管理（描述性生理背景）”。它消费当前 `personal-health-analysis` 的结构化结果，不定义新的健康算法，也不把穿戴设备数据转化为认知、职业表现或日程决策。

## 1. 来源状态机

1. 将复盘请求窗口原样传给 Garmin 分析，不为满足算法样本量自动扩大窗口。
2. 使用同一 Python 解释器完成本地预检与读取，不在失败后静默换解释器。先通过 canonical `personal-health-analysis` 的 `runtime-authority.json`；权威、版本、入口哈希或 `.gemini` 代理绑定不一致时失败关闭。
3. 当前周期末端数据不新鲜时，按主技能的新鲜度门直接运行一次两阶段受控同步（`sync_health_data.py sync --dry-run` 后 `--allow-network --allow-sync`）；成功后重新执行本地读取。不得启动、注册或修复计划任务。该动作不是 `partial` 的云端回退。
4. 同步失败、限流或覆盖验证失败不得在同一次复盘中重试；保留同步前本地证据并披露缺口。历史周期、草稿、预览、只读、不同步或不联网请求不触发同步。
5. `complete`：使用本地结果。
6. `partial`：继续使用本地结果，披露逐组件缺口；不得转云端。
7. `no_data`：只有本次未尝试新鲜度同步、用户本次明确授权联网、实时预检通过、日期窗口和组件清单保持一致时，才允许一次云端只读回退；同步一经尝试，失败不得在同一次采集中改走实时来源。
8. `read_error`、Schema、完整性、数据库变化、依赖或授权错误均失败关闭，不得归类为 `no_data`。
9. 默认组件为 `sleep,hrv,body_battery,heart_rate,stress`。活动、训练负荷、账户资料、设备设置、闹钟、认证材料和原始轨迹不在默认范围内。

## 2. 结构化输入

优先消费 `insight_cn.audit_data`，不要从 `overall_insight` 反向解析字段。每次输出至少保留：

- 请求窗口、实际观测窗口、有效来源、新鲜度和逐组件 `component_coverage`；
- `acquisition_audit`：`sync_eligible`、`sync_attempted`、`task_status`、`local_reread`、`live_fallback` 与稳定 `reason`。未触发的分支也必须给出显式状态，不能因无同步而省略；
- 静息心率当前值及其 `observation_date`；
- HRV 值、Garmin 原始状态及其 `observation_date`；
- 睡眠 `observation_date`、`duration_hours`、`duration_status`、深睡/REM 占比和躁动；
- 完整的 `audit_data.sleep_debt` 对象；来源未提供睡眠负债时必须保持 `sleep_debt_h=null`、`sleep_debt_status=not_provided_by_source`、`method=none`、`baseline_h=null`、`window_days=null`，并携带稳定原因码、原因和最近实际睡眠。顶层 `sleep_debt` 与该对象语义一致，扁平 `audit_data.sleep_debt_h/sleep_debt_status` 仅作兼容；
- Body Battery 的充入量、峰值、低值及其 `observation_date`；
- 日均压力、`stress_observation_date` 和 `stress_status`。

每个 KPI 使用自己的观测日期。不同日期的指标不得写成同日快照。机器字段缺失保持 `null`，中文显示“无有效观测”，不能显示 Python `None`，也不能把缺失值写成生理值 0。

上游历史结果中的 `execution_bandwidth=[DATA_UNAVAILABLE]` 或 `sleep_debt=[DATA_UNAVAILABLE]` 是机器侧旧哨兵，不是可直接复制到日志的最终内容。执行带宽和睡眠负债字段不得出现任何 `[DATA_UNAVAILABLE]`，即使其后附有解释；必须按本文件第 5 节转写为结构化状态、原因、可观察事实和边界说明。

## 3. 评分与血缘边界

- `readiness` 只允许保留 `status=not_scored`；忽略空的 `quant_scores`，不得生成能量、准备度、恢复力、健康或执行带宽总分及红黄绿等级。
- Body Battery 与睡眠评分共享睡眠、压力等上游信号，不能作为彼此独立的重复证据，也不能叠加为综合结论。
- 可以描述同期共现和可核验的时间关系；不得推断疾病、治疗需求、感染、炎症、免疫状态、认知能力、职业表现或确定因果。
- 健康数据不得自动决定训练、补剂、会议、工作强度、闹钟或重要决策。一般性建议必须保留用户判断，并给出数据限制。

## 4. 周期与趋势资格

- 日度与周度复盘默认使用精确窗口内的 `insight_cn`；样本不足时只描述观测与缺口，不生成个人趋势。
- 月度与年度复盘只有在用户请求窗口本身满足资格时，才可使用本地 `patterns`；不得为满足资格扩大窗口。
- `patterns` 只支持本地只读来源。实时来源必须返回 `LIVE_ANALYSIS_NOT_SUPPORTED`，不能用云端面板能力代替。
- 个人趋势需要至少 21 个历史观测日和最近 7 个完整自然日，通常需要至少 28 天请求窗口。
- 睡眠规律检查末端 14 天且至少有 7 个有效夜晚；时长资格和睡眠时点资格分别判断。
- `baseline_change` 还要求至少 21 个同日配对历史样本、日期对齐、非零方差，以及设备、固件、分析算法和厂商算法时期可比。任一门禁失败时只报告资格状态和原因。
- 缺失、同日重复冲突、`cross_epoch` 或任何 `epoch_unknown` 均失败关闭；不插值、不把空白日当 0。

## 5. 复盘投影

只要输出“能量管理（描述性生理背景）”，除逐指标观测、来源和缺口外，必须生成以下六个非空稳定字段。个人日记历史标题 `能量管理 (Biological-Cognitive Correlation)` 由 Gate 兼容读取，但新草稿必须统一使用中文标题和本节字段结构。字段不可只有 `not_scored`、`[DATA_UNAVAILABLE]` 或空字符串；不可用时也要写明状态、原因以及仍可观察的事实。

1. **采集审计**：使用稳定键值 `sync_eligible=<true|false>; sync_attempted=<started|waited_existing|direct|not_attempted>; task_status=<success|failed|timeout|invalid|start_failed|interrupted_or_terminated|not_checked>; local_reread=<accepted|rejected|not_run>; local_status=<complete|partial|no_data|read_error|not_run>; live_fallback=<used|not_used>; reason=<稳定原因码>`。`direct` 只表示 canonical 探针可靠确认任务不存在后，经同一 freshness gate 执行的一次受控直同步；权限不足或查询错误不得使用。实时回退必须由结构化 `local_status=no_data` 证明；不得只写“已联网”或“未联网”。
2. **执行带宽**：固定保留 `not_scored`，并说明本技能不从 Garmin 指标生成认知、职业表现或日程承载评分。可以引用用户明确提供的主观状态，但必须与穿戴设备观测分开。
3. **睡眠负债**：来源提供 `sleep_debt_h` 时，必须同时陈述 `sleep_debt_status=provided_by_source`、非空 `method`、数值 `baseline_h` 和正整数 `window_days`；来源未提供时写明 `sleep_debt_h=null`、`sleep_debt_status=not_provided_by_source`、`method=none`、`baseline_h=null`、`window_days=null`，并可另列实际睡眠时长，不自行用目标睡眠时长反推债务。
4. **摩擦解构**：分别列出已记录的工作或日程负荷、主观感受、描述性生理观测、外部约束和未知项。不得把活动缺失写成零活动，也不得使用“神经空耗、内分泌死锁、皮质醇淤积”等未经证实的机制标签。
5. **交叉归因**：核对每项证据的观测日期，只描述同期共现、日期错位和可替代解释；不得写成工作、旅行或日程导致健康变化，也不得反向推断认知或工作表现。
6. **干预指令**：只能给出可选、非诊断、非强制的一般性建议；至少包含触发条件、最小动作和完成标准，并明确由用户结合主观状态决定。不得由健康数据自动取消或更改会议、训练、闹钟、工作强度或重要决策。

使用 `references/templates.md` 中的稳定字段结构。若完全没有健康数据，可以省略整节，但必须在总数据缺口中说明本地状态、是否具备联网授权以及没有执行的回退。
