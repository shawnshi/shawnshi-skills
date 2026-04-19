# Intelligence Quality Standard (V8.0)

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
- 至少 3 条 `action_levers`
- Top 10 不重复
- 所有 Top 项目有摘要
- 未审计的 L4 不得交付
