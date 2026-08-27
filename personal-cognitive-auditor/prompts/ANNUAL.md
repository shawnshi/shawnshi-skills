# Annual Audit Template

本模板用于年度复盘，可按材料和用户目标裁剪。默认只读获取年度范围内可用的日历与本地 Garmin 摘要；窗口包含当前自然日且末日数据不新鲜时，可按主技能新鲜度门启动一次已授权同步任务并披露结果。年度叙事必须由可核验事件和资料支撑，不用连贯故事填补数据空白。只有请求窗口本身满足资格时才使用本地 `patterns`，并披露长期设备、固件和算法时期可比性。

## 建议内容

```markdown
# [年份] Annual Audit

## 时间范围与证据
- **周期:** [日期与时区]
- **材料与覆盖:** [来源、覆盖月份、主要缺口]
- **数据缺口:** [说明]

## 年度关键事实与转折
- [事件、证据及影响]

## 承诺对照
| 承诺 | 状态 | 证据 | 外部约束或未知 |
|---|---|---|---|
| [承诺] | [完成/部分完成/未完成/无法判断] | [证据] | [说明] |

## 重复模式与能力变化
- **观察:** [长期重复或变化]
- **证据强度:** [高/中/低及理由]
- **替代解释:** [样本、环境变化或其他可能]

## 时间、关系与工作背景
- [使用用户材料和默认只读日历，分别说明覆盖窗口和不能推出的结论]

## 能量管理（描述性生理背景）
- **数据范围与来源:** [请求窗口、实际观测窗口、本地/实时来源]
- **组件覆盖与新鲜度:** [逐组件状态、最近观测日期和主要空档]
- **采集审计:** `sync_eligible=<true|false>; sync_attempted=<started|waited_existing|not_attempted>; task_status=<终态|not_checked>; local_reread=<accepted|rejected|not_run>; local_status=<complete|partial|no_data|read_error|not_run>; live_fallback=<used|not_used>; reason=<稳定原因码>`
- **睡眠观察:** [时长、阶段占比、躁动和观测日期]
- **HRV 与静息心率观察:** [值、原始状态和各自观测日期]
- **Body Battery 与压力观察:** [值和各自观测日期]
- **趋势资格:** [patterns/baseline_change 的状态、样本数、时期可比性和失败关闭原因]
- **执行带宽:** `not_scored`；[说明不从健康指标生成认知、职业表现或日程承载评分；主观状态如有则另列来源]
- **睡眠负债:** [来源提供时写 sleep_debt_h、sleep_debt_status=provided_by_source、method、baseline_h 和 window_days；未提供时写 sleep_debt_h=null、sleep_debt_status=not_provided_by_source、method=none、baseline_h=null、window_days=null 及原因]
- **摩擦解构:** [分列年度已记录负荷、主观感受、生理观测、外部约束和未知项]
- **交叉归因:** [只描述时间共现、日期错位、时期差异和替代解释，不写因果或能力推断]
- **干预指令:** [可选；写触发条件、最小动作和完成标准，由用户结合主观状态决定]
- **数据缺口与不可判断事项:** [覆盖月份、日期错位、时期不可比或来源限制]

## 风险、机会与取舍
- [基于事实的风险、机会和待决事项]

## 下一周期行动
1. [触发条件、最小动作、完成标准]
```

只有用户明确要求保存或交接时，才根据 `references/handoff_contract.md` 另加 `Handoff Payload`。年度复盘不得自动触发日记、记忆或其他长期写入。
