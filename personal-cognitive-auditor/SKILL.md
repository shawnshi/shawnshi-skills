---
name: personal-cognitive-auditor
description: 战略认知联合审计官。当用户提出“复盘今日日志”“周结/月结/年结”或需要深层认知审计、多源数据整合与战术问责时激活。交付 daily、weekly、monthly、annual 四类认知审计报告，并通过显式 hand-off contract 交由 personal-diary-writer 落盘。
---

<strategy-gene>
Keywords: 认知审计, 战术问责, 能量复盘, Hand-off
Summary: 整合生理、日程与交互数据执行多维审计，通过战术问责驱动决策演化。
Strategy:
1. 证据优先：优先使用 Garmin 与 Calendar 真实数据，数据缺失必须显式标注。
2. 职责解耦：仅负责生成审计报告与 payload，物理落盘强制交给 diary-writer。
3. 统一骨架：日/周/月/年审计共享同一审计骨架，确保演化叙事不中断。
AVOID: 严禁未加载 Prompt 模板即生成；禁止在周审计中漏掉交互模式分析；禁止未生成 hand-off payload 即结束。
</strategy-gene>

# Personal Cognitive Auditor (V2.0: Unified Audit System)

## 0. 核心约束
- **证据优先**: 审计必须优先使用真实生理、日程、历史战术和对话/工作上下文；缺失时必须明确标注数据缺口。
- **职责剥离**: 本技能只生成审计报告和 hand-off payload；物理落盘统一交给 `personal-diary-writer`。
- **统一结构主权**: `daily / weekly / monthly / annual` 必须共享同一套审计骨架，只允许深度不同，不允许结构断裂。
- **可降级运行**: 缺 Garmin、Calendar、历史战术或交互数据时不得中止，必须切换为降级模式继续输出。

## 1. 周期模式
- `daily-audit`: 轻量日审计，强调上下文、核心洞察、次日战术。
- `weekly-audit`: 标准周审计，强调问责、能量模式、核心矛盾、下周战术。
- `monthly-audit`: 长周期审计，新增工作洞察、交互模式、资源配置。
- `annual-audit`: 历史级审计，新增年度叙事、能力演化、长期取舍。

## 2. 能力契约
输入能力按以下 4 类组织：

- `physiology_context`
  - 优先: Garmin / 健康基线
  - 降级: 用户手动提供睡眠、疲劳、恢复描述
- `calendar_context`
  - 优先: Calendar / 日程
  - 降级: 用户手动提供事件与会议
- `prior_tactics`
  - 优先: 上周期审计末尾的战术项
  - 降级: 用户自述上周期承诺
- `interaction_context`
  - 仅 `weekly / monthly / annual` 推荐使用
  - 缺失时必须写明 `【数据缺口】未注入交互上下文`

## 3. 执行协议

### Phase 1: Gather
1. 读取 [config.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/references/config.md:1>)，确认周期、时区、语言和降级规则。
2. 读取对应 prompt：
   - [DAILY.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/prompts/DAILY.md:1>)
   - [WEEKLY.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/prompts/WEEKLY.md:1>)
   - [MONTHLY.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/prompts/MONTHLY.md:1>)
   - [ANNUAL.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/prompts/ANNUAL.md:1>)
3. 汇总四类输入能力，并标出缺口。

### Phase 2: Audit
1. 使用统一骨架生成审计：
   - Context Snapshot
   - Tactical Accountability
   - Signals
   - Core Insight
   - Strategic Diagnosis
   - Next Tactics
   - Handoff Payload
2. `weekly / monthly / annual` 必须额外包含交互/工作模式模块。
3. `monthly / annual` 必须额外包含长期取舍或长期方向模块。

### Phase 3: Gate
1. 交付前运行 [audit_gate.py](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/scripts/audit_gate.py:1>)。
2. Gate 未通过时，优先修复：
   - 缺失问责
   - 缺失数据缺口说明
   - 缺失核心洞察/核心矛盾
   - 缺失 1-3 条下周期战术
   - 残留占位符

### Phase 4: Hand-off
1. 读取 [handoff_contract.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/references/handoff_contract.md:1>)。
2. 生成显式 hand-off payload，交给 `personal-diary-writer`。
3. 若审计揭示的是底层认知/架构级摩擦，可在 payload 中标注 `requires_mentat_diary: true`。

## 4. Telemetry & Metadata
- 如具备 `write_file` 能力，可选写入 telemetry。
- 推荐结构：
```json
{"skill_name":"personal-cognitive-auditor","status":"success","period_type":"weekly","data_sources":["calendar","garmin"],"handoff_ready":true}
```
- Telemetry 为增强项，不得阻断主交付。

## 5. 历史失效先验
- `IF [Prompt not loaded] THEN [Halt]`
- `IF [Section == "Tactical Accountability"] THEN [Require Markdown Table OR explicit no-prior-tactics note]`
- `IF [physiology_context missing AND calendar_context missing] THEN [Require explicit data-gap statement]`
- `IF [period_type IN ("weekly","monthly","annual")] THEN [Halt if missing interaction/work pattern analysis]`
- `IF [handoff payload missing] THEN [Halt before diary-writer hand-off]`
