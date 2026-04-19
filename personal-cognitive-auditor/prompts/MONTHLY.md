# Monthly Audit Prompt (V2.0)

你要生成一份 `monthly-audit`。输出必须是 Markdown，且遵循统一骨架。缺 Garmin、Calendar、交互日志或工作产出时，不得脑补，必须写 `【数据缺口】`。

## 必须覆盖
- 上月承诺与执行审查
- 月度时间/能量/产出概览
- 交互/工作模式与观点演化
- 1 个核心系统性问题
- 3 个下月目标
- 取舍/剥离建议
- hand-off payload

## STRICT Output Format

```markdown
# [YYYY-MM] Monthly Cognitive Audit

## Context Snapshot
- **本月主线:** [主线]
- **关键事件:** [事件]
- **【数据缺口】:** [若存在]

## Tactical Accountability
| 上月承诺 | 执行状态 | 真实阻力/偏离原因 | 问责判定 |
| :--- | :--- | :--- | :--- |
| [Tactic] | 🟢/🟡/🔴 | [Root Cause] | [战略漂移/执行偏差/合理调整] |

## Signals
- **Physiology Trend:** [恢复、疲劳、稳定性]
- **Calendar Allocation:** [会议/深度工作/救火]
- **Energy Curve:** [高低点与共因]

## Interaction & Work Patterns
- **交互模式:** [本月对话与问题意识的变化]
- **工作洞察:** [产出物、专业沉淀、知识增量]
- **观点演化:** [被强化或被修正的看法]

## Core Insight
- **核心洞察:** [一句话]
- **被证伪的假设/盲点:** [具体说明]

## Strategic Diagnosis
- **核心系统性问题:** [一句话]
- **下月 3 个关键目标:** [SMART 风格]
- **必须停止/剥离:** [1-3 件]

## Next Tactics
1. [高优先级]
2. [中优先级]
3. [低优先级]

## Long-Cycle Outlook
- **长期风险:** [未来 1-3 个月风险]
- **长期机会:** [未来 1-3 个月机会]

## Handoff Payload
```json
{
  "period_type": "monthly",
  "audit_title": "[YYYY-MM] Monthly Cognitive Audit",
  "next_tactics": ["..."],
  "followup_flags": ["accountability", "long_cycle"],
  "requires_mentat_diary": false
}
```
```
