# Blueprint field guide

机器输入只使用 [outline-template.md](outline-template.md)。本文件解释设计意图，不定义另一套格式。

## Deck level

| 字段 | 用途 |
|---|---|
| `Topic` | 演示主题，不等同于结论 |
| `Audience` | 实际主听众及其职责或专业水平 |
| `Objective` | 演示后希望发生的可观察结果 |
| `Occasion` | 董事会、院务会、培训、周报等真实场合 |
| `Deck_Mode` | `full`、`section` 或 `one_pager`，决定拓扑规则 |
| `Duration_Minutes` | 约束叙事长度和讲稿密度 |
| `Confidentiality` | 决定共享、截图、引用和资产处理边界 |
| `Status` | 决定未结构化占位符能否放行 |
| `Template_Ref` | 已授权模板的可定位引用 |
| `Decision_Owner` | 有权作出关键决定的人或治理主体 |
| `Source_Cutoff` | 资料检索或核验截止日期 |
| `Must_Keep` | 不得删除或改写的事实、措辞、页面或合规声明 |
| `Deck_ID` / `Revision` | 稳定稿件标识与版本 |
| `Prepared_By` / `Reviewed_By` | 已实际完成编制/复核的责任记录；计划复核人不得提前写入 `Reviewed_By` |

## Page level

| 字段 | 用途 |
|---|---|
| `Slide_ID` | 与页码解耦的稳定追踪 ID |
| `Goal` | 该页对故事线承担的任务 |
| `Title` | 页面可见标题；结论式或准确描述式均可 |
| `Takeaway` | 听众看完该页应保留的判断 |
| `Body` | 页面可见内容，不包含证据元数据 |
| `Decision` | 明确的批准、选择、确认或授权请求 |
| `Action` | 决策后或当前可执行的动作 |
| `Layout` | 布局库 ID；自定义布局使用 `custom:<slug>` |
| `Visual Description` | 构图、层级、图形关系和必要标注 |
| `Chart` | 图表类型、字段、单位和重点；不需要时写 `none` |
| `Assets` | 图片、Logo、截图、图标或模板及其权利与脱敏状态 |
| `Speaker Notes` | 对判断、限制和转场的口头补充，不照读页面 |
| `Delivery Notes` | 时间、停顿、问答、敏感点或备份页提示 |

## Claims and evidence

不要把事实、推断、假设和建议混在一段“依据”里。

| Claim 类型 | 含义 | 使用要求 |
|---|---|---|
| `fact` | 来源可核验的外部或内部事实 | 引用 Evidence；如尚未核验，明确状态与开放项 |
| `inference` | 基于事实推导出的判断 | 引用支撑证据，并保留推导边界 |
| `assumption` | 为方案或测算暂时采用的条件 | 明确可验证方式和失效影响 |
| `recommendation` | 面向行动的建议 | 说明依据、取舍和责任边界 |

`verified / partial / unverified` 描述核验状态，不描述主张重要性。最终稿可以保留结构化 `unverified` 主张和 Open Items，但必须在页面可见内容或讲稿中准确呈现其不确定性，不能把它们写成已证实事实。一个 Claim 可引用多个 Evidence ID；禁止悬空引用。

Evidence 的 `locator` 应让复核者找到原文，例如页码、表名、URL、文档章节、工作底稿单元格或会议纪要条目。`undated` 只表示来源没有日期，不替代定位信息。

## Open items, risks and assets

- `Open Items` 用于尚未闭合但可分派的输入、决定、资产或合规事项。写清责任人和计划日期；确实未排期才用 `unscheduled`。
- `Risk Flags` 用于可能影响隐私、安全、法律、财务、临床、交付或声誉的事件。风险描述写触发条件和影响，mitigation 写具体控制措施。
- `Assets` 记录资产引用、权利状态和脱敏状态。`permission-pending` 或 `pending` 不代表可在最终 PPT 中使用；构建前必须替换、取得许可或执行脱敏。
- 最终稿可以保留真实且已知的风险或开放项，但不能保留未结构化占位符。

## Page-type minimums

| Type | 最低业务要求 |
|---|---|
| `Cover` | 主题、对象和场合清晰 |
| `Executive-Summary` | 结论、依据、影响或行动可在一页读完 |
| `Section` | 明确下一段要回答的问题 |
| `Content` | 一个主要判断及其支撑 |
| `Data` | 至少一条可定位 Evidence；单位、时间和范围清楚 |
| `Comparison` | 统一比较维度和边界 |
| `Roadmap` | 阶段、结果、责任或依赖清楚 |
| `Decision` | 至少一条结构化 Decision 记录 |
| `Risk` | 至少一条结构化 Risk Flags 记录 |
| `Closing` | 形成总结、行动或有意义的结束 |
| `Appendix` | 只保留支撑主体的补充材料 |
| `References` | 至少一条可定位 Evidence 记录 |

## Working order

1. 建 brief 和核心主张。
2. 选择叙事模式、`Deck_Mode` 与页面类型。
3. 建稳定 `Slide_ID` 并写页面任务。
4. 写 Claims，再补 Evidence、Open Items 和 Risk Flags。
5. 设计页面可见内容、视觉表达和结构化 Assets。
6. 写讲稿并运行结构校验；结构通过不等于可以发布。
7. 只在需要机器交接或实际 PPT 时生成 JSON handoff。
