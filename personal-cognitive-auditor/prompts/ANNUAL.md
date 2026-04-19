# Annual Audit Prompt (V2.0)

你要生成一份 `annual-audit`。输出必须是 Markdown，且遵循统一骨架。语气冷静、直接、历史化。缺任何关键数据时必须写 `【数据缺口】`，不能用叙事补洞。

## 必须覆盖
- 上年终局承诺审查
- 年度关键转折与能力演化
- 生理/时间/关系/工作资产负债
- 交互/工作模式与长期矛盾
- 下一年必须停止与必须开始的事项
- 1 个年度北极星指标
- hand-off payload

## STRICT Output Format

```markdown
# [YYYY] Annual Cognitive Audit

## Context Snapshot
- **年度一句话定义:** [一句话]
- **关键转折:** [事件]
- **【数据缺口】:** [若存在]

## Tactical Accountability
| 上年承诺 | 执行状态 | 真实阻力/偏离原因 | 问责判定 |
| :--- | :--- | :--- | :--- |
| [Tactic] | 🟢/🟡/🔴 | [Root Cause] | [战略漂移/执行偏差/合理调整] |

## Signals
- **Physiology Trend:** [年度恢复与透支模式]
- **Time Allocation:** [播种 vs 救火]
- **Resource Balance:** [时间/健康/关系/财务的主要状态]

## Interaction & Work Patterns
- **交互模式:** [全年问题意识、决策风格、盲点]
- **工作模式:** [长期产出、能力地图、职业定位]
- **被反复忽视的摩擦:** [持续未解的顽固问题]

## Core Insight
- **年度核心洞察:** [一句话]
- **最大自我欺骗/被证伪假设:** [具体说明]

## Strategic Diagnosis
- **年度核心矛盾:** [一句话]
- **必须停止的 3 件事:** [列表]
- **必须开始的 3 件事:** [列表]
- **下一年北极星指标:** [唯一指标]

## Next Tactics
1. [高优先级]
2. [中优先级]
3. [低优先级]

## Long-Cycle Outlook
- **5 年视角下的主要风险:** [风险]
- **5 年视角下的主要机会:** [机会]
- **最大取舍:** [必须舍弃什么]

## Handoff Payload
```json
{
  "period_type": "annual",
  "audit_title": "[YYYY] Annual Cognitive Audit",
  "next_tactics": ["..."],
  "followup_flags": ["accountability", "long_cycle", "yearly_reset"],
  "requires_mentat_diary": true
}
```
```
