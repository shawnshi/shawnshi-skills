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

## 6. JSON Schema & Localization Contract
最终输出**必须**是一个严格符合以下结构的 JSON 对象。
**CRITICAL**: 所有正文分析内容（除原始 URL、专有名词外）**必须输出为中文 (zh-CN)**，并且对所有核心实体使用 `[[ ]]` 进行图谱双链标记。

```json
{
  "punchline": "全局一句话核心结论（中文）",
  "insights": "Weaver Insights 的宏观推演（中文）",
  "digest": "Strategic Digest 战略摘要（中文）",
  "market": "Market Watch 市场观察（中文）",
  "action_levers": [
    {
      "domain": "动作所属领域（如：产品研发/商业化）",
      "task": "具体的行动建议（中文）"
    }
  ],
  "top_10": [
    {
      "title": "原始英文标题",
      "title_zh": "中文翻译标题（必填）",
      "url": "https://...",
      "source": "来源（如 NEJM）",
      "date": "YYYY-MM-DD",
      "fact": "事实描述（中文）",
      "connection": "战略关联（中文）",
      "deduction": "推演结论（中文）",
      "actionability": "可操作动作（中文）",
      "intelligence_level": "L2/L3/L4",
      "confidence": "high/medium/low",
      "summary_zh": "中文摘要（必填）"
    }
  ]
}
```
