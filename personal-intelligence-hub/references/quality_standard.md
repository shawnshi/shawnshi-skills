# Intelligence Quality Standard

## 1. Intelligence Levels
- **L1 Signal**: 原始信号，尚未形成上下文。
- **L2 Info**: 已获得基本上下文，但行动价值有限。
- **L3 Insight**: 已完成 `fact -> connection -> deduction`，并能解释对当前战略重心的影响。
- **L4 Alpha**: 非共识、可直接触发动作，且已经过红队或保守验证。

## 2. Mandatory Structured Fields
每条进入 Top 集合的情报必须包含：

- `fact`: 发生了什么
- `connection`: 与当前战略主题、竞对或资产的关系
- `deduction`: 这意味着什么
- `actionability`: 可以做什么动作
- `intelligence_level`: `L1/L2/L3/L4`
- `confidence`: `low/medium/high`

## 3. So-What Audit
所有高价值情报必须通过三段论：

1. **事实**: 发生了什么？
2. **联结**: 它和当前战略重心、竞对、主题有什么关系？
3. **推演**: 结论是什么？该采取什么动作？

## 4. Narrative Discipline
- 不用“重大”“革命性”这类空洞形容词。
- 先给动作，再给总结。
- 优先保留反直觉或高杠杆信号。
- Corporate PR 只有在能引出真实结构变化时才允许保留。

## 5. Delivery Contract
最终简报必须满足：

- 有明确 `punchline`
- `action_levers` 可以为空；有动作时必须包含责任人类型、触发条件和观察指标
- `top_10` 为 0–10 条且 URL 不重复；没有足够证据时允许为空
- 所有 Top 项目有摘要
- 未审计的 L4 不得交付

## 6. JSON 合同

最终结构以 `briefing_schema.json` 为唯一机器合同。模板和脚本不得另建字段协议。

- 正文默认使用中文；URL、来源名和专有名词保持原文。
- 实体双链是可选展示能力，不是 Schema 或发布阻断条件。
- `event_date`、`published_at`、`retrieved_at` 分开记录；无法确认事件日期时显式写 `unknown`。
- 每条事实、推断和行动建议分别落入 `fact`、`deduction` 和 `actionability`。
- L4 只有在存在结构化 `adversarial_audit` 时允许交付。

## 7. 分层校验

- 硬检查：JSON 语法、Schema 字段与类型、日期、枚举、URL 重复、占位符、L4 审计。
- 软提示：信号数量、关键词权重、语言空泛、可能缺少第二来源。
- 人工判断：结论是否被证据支持、行动是否适配、反证是否充分。
