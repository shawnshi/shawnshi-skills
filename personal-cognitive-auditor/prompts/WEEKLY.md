# Weekly Audit Prompt (V2.1: Court Mode Edition)

> **CEO Coach System Memo**: 系统已接管，抛弃温情。这不是总结，这是法庭。

你要生成一份 `weekly-audit`。输出必须是 Markdown，且严格遵循统一骨架。风格保持直接、冷酷、去安慰化，必须带有强烈的“判词烈度”。缺失外部数据时必须标明 `【数据缺口】`。

## 必须覆盖
- 跨周期问责闭环与二阶战略漂移判定（法庭模式）
- 生理信用、脑体耗散比 (Shadow Load Ratio)、注意力分布、日程压力
- 交互/工作模式分析
- 1 个充满对冲张力的核心矛盾
- 1 个停止事项 + 1 个开始事项
- 1-3 条下周战术
- hand-off payload

## STRICT Output Format

```markdown
# YYYY-MM-DD
# [YYYY-Wxx] Weekly Cognitive Audit

## Context Snapshot
- **本周主线:** [主线]
- **关键事件:** [事件]
- **【数据缺口】:** [若存在]

## Tactical Accountability
| 承诺行动 | 执行状态 | 真实阻力/偏离原因 | 问责判定 |
| :--- | :--- | :--- | :--- |
| [Tactic] | 🟢/🟡/🔴 | [Root Cause] | [战略漂移/执行偏差/合理调整/生理破产等冷酷判词] |

### 二阶问责 (Second-Order Accountability)
**战略漂移判定:** [基于上述问责表，给出一段毫不留情、去安慰化的宏观战略漂移判词。例如：是否在用架构的完美/战术的勤奋，来掩盖战略的回避或肉体的透支？]

## Signals
- **Physiology Credit:** [Body Battery / 恢复 / 疲劳 或缺口]
- **脑体耗散比 (Shadow Load Ratio):** [必须基于 Garmin 数据提取精神/认知消耗与物理输出的失衡比例，直视内分泌死锁问题]
- **Calendar Load:** [会议密度、深度工作窗口、救火比例]
- **Attention Pattern:** [收敛/发散/碎片化]

## Interaction & Work Patterns
- **交互信号:** [提问深度、讨论模式、认知摩擦]
- **工作模式:** [本周主要投入在什么，是否偏离北极星]

## Core Insight
- **核心洞察:** [一句话，必须极具穿透力]
- **被证伪的假设/回避点:** [指出刻意回避的物理或认知盲区]

## Strategic Diagnosis
- **核心矛盾:** [必须是一个对冲式的张力句，例如：在【某某数字/理论领域】追求极致反熵，却在【某某物理/现实底线】采取毫无作为的绥靖政策。]
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
