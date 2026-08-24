# Garmin 多维健康画像合同

只在用户要求“全面健康分析”“深入健康指导”“多维健康画像”或比较睡眠、恢复、活动与夜间生理信号时读取本资料。画像是本地、只读、非诊断性分析，不生成健康总分、训练许可、疾病概率、药物或补剂建议。

## 1. 入口与读取范围

```bash
<SKILL_PYTHON> scripts/garmin_health_profile.py --days <N> --source local --timezone <IANA_TIMEZONE> --allow-health-data
```

- 未指定窗口时仍使用技能默认最近 7 天；脚本允许 1–366 天，不得为了满足分析资格静默扩窗。
- 画像读取 `garmin.db` 中请求日期范围内的 `daily_summary|days_summary`、`sleep`、`hrv`、`weight`，`attributes` 中最新的 `vo2max_running|vo2max_cycling`，以及 `garmin_activities.db` 中非位置化的活动汇总字段。体重和活动各可额外读取截至窗口末端的单条最近记录，只用于报告新鲜度与 `outside_requested_window`，不得纳入请求窗口趋势。
- 活动查询只允许 `type`、起始日期、耗时、移动时间、距离、平均/最高心率、热量及 Garmin 训练负荷/效果字段；不得查询或输出活动 ID、名称、描述、设备序列号、起止坐标或原始轨迹。活动库缺失时只将该模块标为 `source_unavailable`，不能遮蔽其他健康模块。
- 睡眠起止时间缺少偏移时，只有调用方明确传入 IANA 时区才计算钟点规律；输出必须标记为 `caller_timezone_applied_to_naive_source`。没有时区时保持 `timezone_required`。
- `--adult-18-64-guideline` 只有在用户确认属于 18–64 岁成年人且明确要求公共卫生参考比较时才能附加。默认只展示 Garmin 强度分钟和用户设备中的目标，不判断是否达到 WHO 建议。
- 整次读取必须位于单一数据库指纹窗口内；数据库、Schema、WAL 或 SHM 在读取中变化时失败关闭。

## 2. 核心模块

| 模块 | 直接字段 | 允许派生 | 最低资格 | 禁止解释 |
|---|---|---|---|---|
| 睡眠健康 | 时长、起止、清醒、阶段、设备评分 | 时长标准差、入睡/起床钟点圆周标准差、`总睡眠/(总睡眠+清醒)` 设备估算连续性 | 规律性至少 3 个有效夜晚；时点还需明确时区 | 不把连续性称为临床睡眠效率，不用阶段比例诊断睡眠障碍 |
| 自主恢复 | 静息心率、昨夜 HRV、7 日 HRV、厂商基线区间与状态 | 7 日 HRV 相对厂商区间的位置 | 厂商基线字段同日齐全 | 不从 HRV 或静息心率推断感染、认知能力或训练许可 |
| 能量动态 | Body Battery 高、低、Charged | 日内峰谷跨度、中位 Charged | 至少 1 天可描述，趋势需逐项披露覆盖 | 不把 Body Battery、睡眠评分、HRV、压力当成相互独立证据或合成总分 |
| 日常活动 | 步数、活动热量、中高强度分钟、设备目标 | 最近 7 日中等分钟、剧烈分钟、Garmin 等效强度分钟、设备目标进度 | 强度比较需要完整披露有效天数 | 不使用通用“1 万步”阈值；不把目标进度当成训练处方或适运动证明 |
| 体重 | 体重 kg、测量日期 | 窗口中位数/范围；至少 3 次且跨 14 天后才计算首末变化和线性斜率 | 稀疏时只报告最近记录与新鲜度 | 不推断 BMI、体成分、目标体重、疾病或减重成效 |
| 已记录活动 | 类型、日期、耗时/移动时间、距离、心率、热量、厂商训练负荷/效果 | 窗口记录数、活跃记录日、总量、类型分布及厂商字段汇总 | 事件流按实际记录汇总，空白日不补零 | 不读取位置/标识/名称/描述，不把无记录解释为无活动或训练建议 |
| 夜间生理 | 睡眠/醒时呼吸率、平均及最低 SpO₂ | 请求窗口内中位数、范围和覆盖 | 至少 1 天可描述 | 不设置缺氧、呼吸疾病或睡眠呼吸暂停诊断阈值 |
| 心肺估计 | 跑步或骑行 VO₂max 最新估计及时间戳 | 距今新鲜度 | 单一模态最新有效值 | 不跨模态比较，不称为实验室测量，不用单点估计给训练许可 |

日度连续指标的派生结果要同时输出数据日期、单位、有效天数、覆盖率、最长缺失段和窗口末端缺失段。体重按稀疏测量序列输出测量次数与跨度；已记录活动按事件流输出记录数和有记录日期数，二者都不得把无记录日期补成生理值 0。当天尚未形成完整记录时返回 `partial`，不能写成同步失败。

## 3. 指标血缘与避免重复计数

- HR、HRV 是压力、Body Battery 和部分睡眠指标的共同上游信号。
- Body Battery 还结合活动、休息和睡眠；睡眠评分结合时长、阶段、压力等输入。
- 强度分钟由设备型号、设置、心率区间或步频规则决定；新旧设备计算方法可能不同。
- 因此跨模块只能并列展示“相互一致或不一致的观察”，不能把同源变化累加成置信度、风险概率或总健康分。

## 4. 指导输出合同

画像输出按以下顺序形成建议，但不直接替用户作训练、医疗或日程决定：

1. 数据是否足够新、覆盖是否完整、是否存在佩戴或同步空档。
2. 睡眠时长、时点与连续性中，哪个维度最值得继续观察；不设置未经配置的好坏阈值。
3. 体重与已记录活动是否足够新；稀疏或落在窗口外时只报告最近值和记录日期，不伪造趋势或零活动日。
4. 最近 7 日活动强度分布与用户自己的 Garmin 目标是否一致；人口指南比较必须单独满足年龄与意图门禁。
5. HRV 厂商状态、静息心率、压力和 Body Battery 是否出现同日一致变化，同时明确共同血缘与混杂因素。
6. 夜间呼吸/血氧仅在个人时间趋势中描述；持续变化伴随症状时建议携带原始记录咨询合格医疗人员。

禁止输出 `health_score`、`readiness_score`、红黄绿灯、疾病风险分数、强制训练/停训、补剂剂量、会议或工作能力判断。

## 5. 非核心或低覆盖模块

- 饮水与汗液：手工录入和设备估算可能混合，覆盖不足时只报告 `insufficient_coverage`，不推断脱水或给补液量。
- 逐活动明细、活动名称/描述、位置、轨迹及原始 FIT/GPX/TCX：继续要求用户明确请求并遵循活动文件授权边界。默认画像只读取不含位置和标识的汇总字段；训练负荷/效果只按 Garmin 厂商值聚合，不生成训练处方。
- Fitness Age、Training Readiness、Training Status：只可展示 Garmin 原始值及新鲜度，不反向重建厂商算法，也不与本画像合成分数。

## 6. 证据与来源

以下资料访问于 2026-08-24，仅用于解释设备字段、方法边界和公共卫生参照：

- [Garmin HRV Status](https://www.garmin.com/en-IE/garmin-technology/health-science/hrv-status/)：7 日平均、约 3 周个人基线及厂商状态语义。
- [Garmin Body Battery](https://www.garmin.com/en-US/garmin-technology/health-science/body-battery/)：HRV、压力、睡眠和活动的共同输入及充放电语义。
- [Garmin Sleep Tracking](https://support.garmin.com/en-IN/?faq=mBRMf4ks7XAQ03qtsbI8J6)：睡眠时长、起止、阶段、呼吸和 Pulse Ox 的设备能力差异。
- [Garmin Intensity Minutes](https://support.garmin.com/en-CA/?faq=pNU9nnDzzGAHmEavp9rpY8)：强度分钟受设备与计算设置影响，剧烈强度可双倍计入目标。
- [Garmin Heart Rate Monitoring](https://www.garmin.com/en-US/garmin-technology/health-science/heart-rate-monitoring/) 与 [VO₂max](https://www.garmin.com/en-GB/garmin-technology/running-science/physiological-measurements/vo2-max/)：腕式心率与心肺估计的来源、模态和个体化限制。
- [WHO 身体活动指南](https://www.who.int/publications/i/item/9789240015128)：18–64 岁成人每周活动建议；只有人口和意图门禁满足时才做参考比较。
- [睡眠规律性专家共识](https://pubmed.ncbi.nlm.nih.gov/37684151/)：睡眠起止规律是独立健康维度，但不提供适用于消费设备的统一阈值。
- [AASM 消费级睡眠技术立场](https://aasm.org/advocacy/position-statements/consumer-sleep-technology/)：消费设备不能替代睡眠疾病诊断或治疗验证。
