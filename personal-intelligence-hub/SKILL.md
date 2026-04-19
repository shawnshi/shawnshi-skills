---
name: personal-intelligence-hub
description: 战略情报作战中枢。用于多源技术/医疗/AI 情报扫描、7 日去重、二阶推演、红队审计和分层简报生成。必须读取 `references/strategic_focus.json`、`references/quality_standard.md`、`references/briefing_template.md` 和 `references/karpathy_feeds.json`，并通过 `blackboard`、`history_manager`、`briefing_gate` 保证状态、去重与交付质量。
---

# Personal Intelligence Hub V8.0

## 0. 核心约束
- **配置优先**: 扫描范围、主题、优先源、排除词都以 [strategic_focus.json](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/strategic_focus.json:1>) 为准。
- **质量合同**: 每条高价值情报必须满足 [quality_standard.md](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/quality_standard.md:1>) 的 `fact / connection / deduction / actionability` 结构。
- **状态显式化**: 运行状态必须写入 `blackboard`，去重必须走 `history_manager`，交付前必须通过 `briefing_gate`。
- **可降级运行**: 无 LLM runner 时允许退化为启发式精炼，但不得伪装成 Alpha 级情报。

## 1. 运行资产
- **Feeds**: [karpathy_feeds.json](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/karpathy_feeds.json:1>)
- **Strategy Config**: [strategic_focus.json](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/strategic_focus.json:1>)
- **Quality Contract**: [quality_standard.md](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/quality_standard.md:1>)
- **Briefing Template**: [briefing_template.md](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/briefing_template.md:1>)
- **State Scripts**:
  - [blackboard.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/blackboard.py:1>)
  - [history_manager.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/history_manager.py:1>)
  - [briefing_gate.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/briefing_gate.py:1>)

## 2. 执行协议

### Phase 1: Scan
1. 初始化黑板。
2. 运行 [fetch_news.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/fetch_news.py:1>)。
3. 采集结果写入运行态目录，而不是 skill 包内 `tmp/`。

### Phase 2: Refine
1. 运行 [refine.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/refine.py:1>)。
2. 对候选信号执行 7 日 URL + 语义指纹去重。
3. 为 Top 信号补齐：
   - `fact`
   - `connection`
   - `deduction`
   - `actionability`
   - `intelligence_level`
   - `confidence`

### Phase 3: Audit
1. 如存在 L4 候选，优先运行 [adversarial_audit.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/adversarial_audit.py:1>)。
2. 若无红队 runner，则必须保守降级，不得保留未审计的 L4。

### Phase 4: Forge
1. 运行 [forge.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/forge.py:1>)。
2. 严格使用 [briefing_template.md](<C:/Users/shich/.codex/skills/personal-intelligence-hub/references/briefing_template.md:1>) 渲染。
3. 交付前必须通过 [briefing_gate.py](<C:/Users/shich/.codex/skills/personal-intelligence-hub/scripts/briefing_gate.py:1>)。

## 3. 结果门
- `punchline` 不得为空。
- `action_levers` 至少 3 条。
- `top_10` 最多 10 条且 URL 不得重复。
- 每个 Top item 必须有 `summary`。
- 若仍存在 L4，则必须存在 `adversarial_audit`。

## 4. 反模式
- 禁止把“摘要”伪装成“洞察”。
- 禁止过去 7 天重复推送同一核心信号。
- 禁止在缺 Evidence 时输出高等级判断。
- 禁止把 skill 目录当作运行时数据库。

## 5. Telemetry
- 如具备文件写入能力，可记录 telemetry。
- 推荐结构：
```json
{"skill_name":"personal-intelligence-hub","status":"success","mode":"daily_brief","runner":"heuristic","top10_count":10}
```
