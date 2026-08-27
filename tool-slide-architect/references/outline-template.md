# Canonical outline Schema v2

本文件是 `outline.md` 唯一可供脚本解析的格式。字段名、大小写、记录分隔符和顶层区块标记不得改写；字段采用下列规范顺序，偏离顺序只产生提示，顶层区块顺序错误会阻断。双花括号仅用于可复用模板；草稿中会告警，最终稿中会阻断。

```markdown
<DECK_METADATA>
Schema_Version: 2
Topic: {{TOPIC}}
Audience: {{AUDIENCE}}
Objective: {{OBJECTIVE}}
Occasion: {{OCCASION}}
Deck_Mode: full
Duration_Minutes: 15
Language: zh-CN
Aspect_Ratio: 16:9
Confidentiality: internal
Status: draft
Slide_Count: 3
Generated: {{YYYY-MM-DD}}
Template_Ref: none
Decision_Owner: {{DECISION_OWNER}}
Source_Cutoff: {{YYYY-MM-DD_OR_NOT_APPLICABLE}}
Must_Keep: none
Deck_ID: {{DECK_ID}}
Revision: {{REVISION}}
Prepared_By: {{PREPARED_BY}}
Reviewed_By: {{REVIEWED_BY}}
</DECK_METADATA>

<STYLE_INSTRUCTIONS>
Style_ID: corporate
Design_Aesthetic: 克制、结构化的决策汇报
Background: 白底为主，章节页可使用深蓝底
Typography: 无衬线字体，标题与正文形成明确层级
Color_Palette: navy #17365D; blue #2F75B5; gray #5B6573; white #FFFFFF
Density: balanced
Citation_Treatment: visible-footer
Brand_Rules: 仅使用已授权模板、Logo和品牌色；保留必要引用及保密标记
Accessibility: 正文和背景保持足够对比；不只依靠颜色传达含义；图表提供直接标签
</STYLE_INSTRUCTIONS>

---
Slide_ID: S001
Type: Cover
Page: 1
Section: Opening
---

// NARRATIVE
[Goal]: 建立主题、对象与汇报目的
[Title]: {{DECK_TITLE}}
[Takeaway]: {{OPTIONAL_COVER_TAKEAWAY}}

// CONTENT
[Body]: {{COVER_SUBTITLE_AND_CONTEXT}}

// EVIDENCE
[Claims]: none
[Evidence]: none
[Open Items]: none
[Risk Flags]: none

// VISUAL
[Layout]: title-hero
[Visual Description]: {{COVER_VISUAL_DESCRIPTION}}
[Chart]: none
[Assets]: none

// DELIVERY
[Speaker Notes]: {{COVER_SPEAKER_NOTES}}
[Delivery Notes]: {{OPTIONAL_COVER_DELIVERY_NOTES}}

// END SLIDE

---
Slide_ID: S002
Type: Content
Page: 2
Section: Core
---

// NARRATIVE
[Goal]: 用证据建立核心判断
[Title]: {{CONTENT_TITLE}}
[Takeaway]: {{CONTENT_TAKEAWAY}}

// CONTENT
[Body]: {{VISIBLE_CONTENT}}
[Decision]: none
[Action]: none

// EVIDENCE
[Claims]:
- C1 | fact | verified | {{FACT_STATEMENT}} | E1
- C2 | inference | partial | {{INFERENCE_STATEMENT}} | E1
- C3 | recommendation | unverified | {{RECOMMENDATION_STATEMENT}} | none
[Evidence]:
- E1 | {{SOURCE_NAME}} | {{YYYY-MM-DD_OR_UNDATED}} | {{SCOPE}} | {{LOCATOR}}
[Open Items]:
- O1 | data | {{MISSING_INPUT}} | {{OWNER}} | {{YYYY-MM-DD_OR_UNSCHEDULED}}
[Risk Flags]:
- R1 | delivery | medium | {{RISK_DESCRIPTION}} | {{MITIGATION}}

// VISUAL
[Layout]: {{LAYOUT_ID}}
[Visual Description]: {{VISUAL_DESCRIPTION}}
[Chart]: {{CHART_OR_NONE}}
[Assets]:
- A1 | {{ASSET_REFERENCE}} | permission-pending | pending

// DELIVERY
[Speaker Notes]: {{SPEAKER_NOTES}}
[Delivery Notes]: {{OPTIONAL_DELIVERY_NOTES}}

// END SLIDE

---
Slide_ID: S003
Type: Decision
Page: 3
Section: Close
---

// NARRATIVE
[Goal]: 明确请求并结束主体叙事
[Title]: {{DECISION_TITLE}}
[Takeaway]: {{DECISION_TAKEAWAY}}

// CONTENT
[Body]: {{DECISION_CONTEXT}}
[Decision]:
- D1 | approve | {{REQUEST}} | {{OWNER}} | {{YYYY-MM-DD_OR_UNSCHEDULED}}
[Action]: {{ACTION_OR_NONE}}

// EVIDENCE
[Claims]: none
[Evidence]: none
[Open Items]: none
[Risk Flags]: none

// VISUAL
[Layout]: decision-card
[Visual Description]: {{DECISION_VISUAL_DESCRIPTION}}
[Chart]: none
[Assets]: none

// DELIVERY
[Speaker Notes]: {{DECISION_SPEAKER_NOTES}}
[Delivery Notes]: {{OPTIONAL_DECISION_DELIVERY_NOTES}}

// END SLIDE
```

## Metadata contract

必填字段的规范顺序如下：

`Schema_Version`、`Topic`、`Audience`、`Objective`、`Occasion`、`Deck_Mode`、`Duration_Minutes`、`Language`、`Aspect_Ratio`、`Confidentiality`、`Status`、`Slide_Count`、`Generated`。

- `Schema_Version` 固定为 `2`。
- `Deck_Mode`：`full / section / one_pager`。
- `Duration_Minutes` 与 `Slide_Count` 为正整数。
- `Confidentiality`：`public / internal / confidential / restricted`。
- `Status`：`draft / final`。
- `Generated`：ISO 日期 `YYYY-MM-DD`。

可选字段如使用，规范顺序如下：

`Template_Ref`、`Decision_Owner`、`Source_Cutoff`、`Must_Keep`、`Deck_ID`、`Revision`、`Prepared_By`、`Reviewed_By`。

`Source_Cutoff` 使用 ISO 日期或 `not-applicable`。

`Prepared_By` 与 `Reviewed_By` 只记录实际完成相应工作的主体；计划中的复核责任写入 Open Items，不要提前标记为已复核。

## Style contract

下列字段全部必填；规范顺序如下：

`Style_ID`、`Design_Aesthetic`、`Background`、`Typography`、`Color_Palette`、`Density`、`Citation_Treatment`、`Brand_Rules`、`Accessibility`。

- `Style_ID` 使用 [styles/index.json](styles/index.json) 中的 ID，或 `custom`。
- `Density`：`minimal / balanced / dense`。
- `Citation_Treatment`：`visible-footer / inline / source-note / not-applicable`。
- 任一页面存在 Evidence 记录时不能使用 `not-applicable`。

## Slide contract

- 页头必填顺序：`Slide_ID`、`Type`、`Page`；可选 `Section` 只能放在其后。
- `Slide_ID` 在整份材料中稳定且唯一；页码改变时不改 ID。
- `Type`：`Cover`、`Executive-Summary`、`Section`、`Content`、`Data`、`Comparison`、`Roadmap`、`Decision`、`Risk`、`Closing`、`Appendix`、`References`。
- 顶层区块按 `// NARRATIVE`、`// CONTENT`、`// EVIDENCE`、`// VISUAL`、`// DELIVERY` 排列，以独占一行的 `// END SLIDE` 结束。
- `// NARRATIVE`、`// VISUAL`、`// DELIVERY` 始终必填。`Cover`、`Section`、`Closing` 可省略 `// CONTENT` 和 `// EVIDENCE`；其他类型必须包含全部区块。省略区块时仍保持剩余区块的相对顺序。

## Field and record contract

- `NARRATIVE`：`Goal`、`Title` 必填；`Takeaway` 对 `Cover / Section / Closing` 可选，其他类型必填。
- `CONTENT`：区块存在时 `Body` 必填；`Decision`、`Action` 可选。`Decision` 类型必须含至少一条 Decision 记录。
- `EVIDENCE`：区块存在时按 `Claims`、`Evidence`、`Open Items`、`Risk Flags` 排列，每项使用 `none` 或对应记录。`Data`、`References` 必须含至少一条 Evidence 记录；`Risk` 必须含至少一条 Risk Flags 记录。
- `VISUAL`：`Layout`、`Visual Description` 必填；`Chart`、`Assets` 可选。`Layout` 使用 [layouts.md](layouts.md) 中的 ID，或 `custom:<slug>`；`Assets` 使用 `none` 或结构化 Asset 记录。
- `DELIVERY`：`Speaker Notes` 必填；`Delivery Notes` 可选。

记录使用半角竖线 `|` 分隔，字段数量固定：

```text
- D1 | action | request | owner | YYYY-MM-DD-or-unscheduled
- C1 | fact|inference|assumption|recommendation | verified|partial|unverified | statement | E1,E2-or-none
- E1 | source | YYYY-MM-DD-or-undated | scope | locator
- O1 | data|decision|asset|compliance | description | owner | YYYY-MM-DD-or-unscheduled
- R1 | privacy|security|legal|financial|clinical|delivery|reputation|other | low|medium|high|critical | description | mitigation
- A1 | reference | owned|licensed|public-domain|permission-pending|not-applicable | not-required|verified|pending
```

ID 在各自记录类型内唯一。`Claims` 引用的 Evidence ID 必须存在于同页 Evidence 记录中；`none` 表示没有记录，不得与记录混用。

## Deck topology

- `Deck_Mode: full` 的第一页必须是 `Cover`；主体叙事必须以 `Closing` 或 `Decision` 结束；终点之后只允许 `Appendix` 或 `References`。
- `Deck_Mode: section` 不强制 `Cover` 或叙事终点，用于可嵌入其他演示的连续页面。
- `Deck_Mode: one_pager` 必须正好一页，允许除 `Appendix`、`References` 外的任意页面类型。

## Draft and final validation

- `draft`：moustache、`TBD`、`TODO`、`待补`、`待确认`、`待核验`、`[INSERT]`、`[BASELINE]` 等占位符产生警告；用 `Open Items` 记录未闭合事项。
- `final`：上述未结构化占位符全部阻断；允许结构化 `unverified` Claims 和 Open Items。结构化记录中的非法枚举、无效日期、缺失引用或悬空 ID 必须阻断；`permission-pending` 或脱敏 `pending` 的资产也必须先闭合或替换。
- 内容真实性、法规适用性、资产授权、视觉效果和讲稿质量必须人工复核。
- 校验报告固定声明 `validation_scope: structural`。结构通过不等于 release-ready。
