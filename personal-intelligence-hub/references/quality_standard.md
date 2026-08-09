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
- `primary_domain`: `technology/healthcare_digital`
- `secondary_domains`: 可为空；不得重复 `primary_domain`
- `major_signal`: 是否触发当日比例调整
- `major_signal_reason`: 触发依据；未触发时写 `none`

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
- 默认按技术 40%、医疗数字化 60% 选择；条目数不足 10 时使用最大余数法换算。
- 先执行证据门槛，再执行领域配额；不得用弱资讯填补比例。
- 混合事件仅按 `primary_domain` 计数。
- 比例偏离必须由高影响资讯调整或合格候选不足触发，并在 `mix` 中记录。

## 6. 领域配比与动态调整

- 默认比例：`technology=0.4`、`healthcare_digital=0.6`。
- 单日最大调整幅度：20 个百分点，即技术侧最多 60%、医疗数字化侧最多 80%。
- 高影响资讯只允许两种判定：经过红队审查的 L4；或同时具备高可信 L3、原始来源和近期决策影响。
- 同时出现两个领域的高影响资讯时维持默认比例，按领域内分数选择。
- 某领域合格候选不足时，允许另一领域补位，但必须填写 `supply_exception`，并保留覆盖缺口。

## 7. JSON 合同

最终结构以 `briefing_schema.json` 为唯一机器合同。模板和脚本不得另建字段协议。

- 正文默认使用中文；URL、来源名和专有名词保持原文。
- 实体双链是可选展示能力，不是 Schema 或发布阻断条件。
- `event_date`、`published_at`、`retrieved_at` 分开记录；无法确认事件日期时显式写 `unknown`。
- 每条事实、推断和行动建议分别落入 `fact`、`deduction` 和 `actionability`。
- L4 只有在存在结构化 `adversarial_audit` 时允许交付。
- `mix.actual_counts` 必须与 `top_10[].primary_domain` 的实物计数一致。
- `mix.target_counts` 必须与有效比例和保留条目数一致。

## 8. 分层校验

- 硬检查：JSON 语法、Schema 字段与类型、日期、枚举、URL 重复、占位符、L4 审计、领域分类、比例计算和偏离说明。
- 软提示：信号数量、关键词权重、语言空泛、可能缺少第二来源。
- 人工判断：结论是否被证据支持、行动是否适配、反证是否充分。
