# Daily Audit Prompt (V2.0)

你要生成一份 `daily-audit`。输出必须是 Markdown，且遵循下列统一骨架。缺失的外部数据不能脑补，必须写 `【数据缺口】`。

## 必须覆盖
- 今日上下文与关键事件
- 若存在上周期战术，则做轻量问责；若不存在，显式写明
- 生理/日程信号与认知表现的关系
- 1 条核心洞察
- 1 个核心诊断
- 1-3 条明日战术
- hand-off payload

## STRICT Output Format

```markdown
# [YYYY-MM-DD] [星期X] Daily Cognitive Audit

## Context Snapshot
- **关键事件:** [事件]
- **核心产出:** [产出]
- **【数据缺口】:** [如无日程/生理数据则说明]

## Tactical Accountability
| 项目 | 状态 | 根因 | 判定 |
| :--- | :--- | :--- | :--- |
| [若无上周期战术，则写“无可追责战术项”] | [—] | [—] | [—] |

## Signals
- **Physiology:** [睡眠/恢复/疲劳/缺口]
- **Calendar:** [会议密度/关键事件/缺口]
- **Body-Mind Link:** [身体状态如何影响认知表现]

## Core Insight
- **核心洞察:** [一句话]
- **触发场景:** [具体触发]

## Strategic Diagnosis
- **今日核心问题:** [最重要的认知或执行问题]
- **熵增对抗:** [今天实际减少了什么混乱]

## Next Tactics
1. [高优先级]
2. [中优先级]
3. [低优先级或留空]

## Handoff Payload
```json
{
  "period_type": "daily",
  "audit_title": "[YYYY-MM-DD] Daily Cognitive Audit",
  "next_tactics": ["..."],
  "followup_flags": [],
  "requires_mentat_diary": false
}
```
```
