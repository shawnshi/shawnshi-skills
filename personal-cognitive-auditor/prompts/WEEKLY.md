# Weekly Audit Prompt (V2.0)

你要生成一份 `weekly-audit`。输出必须是 Markdown，且遵循统一骨架。风格保持直接、冷静、去安慰化。缺失外部数据时必须标明 `【数据缺口】`。

## 必须覆盖
- 上周承诺的战术问责
- 生理信用、注意力分布、日程压力
- 交互/工作模式分析
- 1 个核心矛盾
- 1 个停止事项 + 1 个开始事项
- 1-3 条下周战术
- hand-off payload

## STRICT Output Format

```markdown
# [YYYY-Wxx] Weekly Cognitive Audit

## Context Snapshot
- **本周主线:** [主线]
- **关键事件:** [事件]
- **【数据缺口】:** [若存在]

## Tactical Accountability
| 承诺行动 | 执行状态 | 真实阻力/偏离原因 | 问责判定 |
| :--- | :--- | :--- | :--- |
| [Tactic] | 🟢/🟡/🔴 | [Root Cause] | [战略漂移/执行偏差/合理调整] |

## Signals
- **Physiology Credit:** [Body Battery / 恢复 / 疲劳 或缺口]
- **Calendar Load:** [会议密度、深度工作窗口、救火比例]
- **Attention Pattern:** [收敛/发散/碎片化]

## Interaction & Work Patterns
- **交互信号:** [提问深度、讨论模式、认知摩擦]
- **工作模式:** [本周主要投入在什么，是否偏离北极星]

## Core Insight
- **核心洞察:** [一句话]
- **被证伪的假设/回避点:** [具体说明]

## Strategic Diagnosis
- **核心矛盾:** [一句话精准指出]
- **Stop:** [下周必须停止的一件事]
- **Start:** [下周必须开始的一件事]

## Next Tactics
1. [高优先级]
2. [中优先级]
3. [低优先级]

## Handoff Payload
```json
{
  "period_type": "weekly",
  "audit_title": "[YYYY-Wxx] Weekly Cognitive Audit",
  "next_tactics": ["..."],
  "followup_flags": ["accountability"],
  "requires_mentat_diary": false
}
```
```
