# Monthly Audit Template

本模板用于月度复盘，可按材料和用户目标裁剪。默认只读获取当月日历和本地 Garmin 健康摘要；窗口包含当前自然日且末日数据不新鲜时，可按主技能新鲜度门执行一次受控两阶段同步并披露结果。其他联网和来源只使用当前任务明确授权的数据。日历安排不等于实际出席或完成。只有请求窗口本身满足资格时才使用本地 `patterns`，不自动扩窗。

## 自动保存契约

- 月审计通过内容门、周期拓扑门和受保护请求门后默认保存。只有精确 canonical 请求或 `AUDIT_AUTOSAVE` 结构化命令可触发；草稿、预览、只读、不保存及其他修饰请求保持只读。
- payload 的第一个非空行且唯一 H2 必须是 `## [YYYY-MM] Monthly Cognitive Audit｜起始日期 至 结束日期`；其余标题只能是 H3 或更深。
- 运行 `audit_gate.py --period-type monthly --period-id YYYY-MM --enforce-template-fields` 后，使用同一字节 payload、`periodic-audit-request-v1` artifact 和 `diary_ops.py scope/replace --action replace-monthly-audit --month YYYY-MM`。完整保留月末日期块的日记及其他周期审计；日期块不存在时只创建日期标题与本月审计。

## 建议内容

```markdown
## [YYYY-MM] Monthly Cognitive Audit｜[起始日期] 至 [结束日期]

### 时间范围与证据
- **周期:** [日期与时区]
- **材料与覆盖:** [来源、起止日期、缺失天数]
- **数据缺口:** [说明]

### 关键事实与产出
- [事实、证据及其适用范围]

### 承诺对照
| 承诺 | 状态 | 证据 | 外部约束或未知 |
|---|---|---|---|
| [承诺] | [完成/部分完成/未完成/无法判断] | [证据] | [说明] |

### 重复模式与变化
- **观察:** [重复出现或发生变化的模式]
- **证据强度:** [高/中/低及理由]
- **替代解释:** [不能排除的原因]

### 时间背景
- [描述日程覆盖窗口和缺口；安排不等于出席或完成]

### 能量管理（描述性生理背景）
- **数据范围与来源:** [请求窗口、实际观测窗口、本地/实时来源]
- **组件覆盖与新鲜度:** [逐组件状态、最近观测日期和缺口]
- **采集审计:** `sync_eligible=<true|false>; sync_attempted=<started|waited_existing|direct|not_attempted>; task_status=<success|failed|timeout|invalid|start_failed|interrupted_or_terminated|not_checked>; local_reread=<accepted|rejected|not_run>; local_status=<complete|partial|no_data|read_error|not_run>; live_fallback=<used|not_used>; reason=<稳定原因码>`
- **睡眠观察:** [时长、阶段占比、躁动和观测日期]
- **HRV 与静息心率观察:** [值、原始状态和各自观测日期]
- **Body Battery 与压力观察:** [值和各自观测日期]
- **趋势资格:** [patterns/baseline_change 的状态、样本数与失败关闭原因]
- **执行带宽:** `not_scored`；[说明不从健康指标生成认知、职业表现或日程承载评分；主观状态如有则另列来源]
- **睡眠负债:** [来源提供时写 sleep_debt_h、sleep_debt_status=provided_by_source、method、baseline_h 和 window_days；未提供时写 sleep_debt_h=null、sleep_debt_status=not_provided_by_source、method=none、baseline_h=null、window_days=null 及原因]
- **摩擦解构:** [分列当月已记录负荷、主观感受、生理观测、外部约束和未知项]
- **交叉归因:** [只描述时间共现、日期错位、时期差异和替代解释，不写因果或能力推断]
- **干预指令:** [可选；写触发条件、最小动作和完成标准，由用户结合主观状态决定]
- **数据缺口与不可判断事项:** [日期错位、时期不可比、来源限制]

### 风险、取舍与未知
- [风险或需要用户决定的取舍]

### 下月行动
1. [触发条件、最小动作、完成标准]
```

canonical 自动保存不等于交接授权。只有用户明确要求交接时，才根据 `references/handoff_contract.md` 另加 `Handoff Payload`。
