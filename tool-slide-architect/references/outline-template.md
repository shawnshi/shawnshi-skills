# Canonical Outline Schema

本文件是 `outline.md` 唯一可供脚本解析的 Schema。字段名、大小写和区块顺序不得自行改写。模板中的双花括号是占位符；检查模板结构时使用 `validator.py --allow-placeholders`，最终交付不得保留占位符。

```markdown
# Slide Deck Outline

<DECK_METADATA>
Topic: {{TOPIC}}
Audience: {{AUDIENCE}}
Objective: {{OBJECTIVE}}
Language: {{LANGUAGE}}
Slide_Count: 2
Generated: {{ISO_DATE}}
</DECK_METADATA>

<STYLE_INSTRUCTIONS>
Design_Aesthetic: {{VISUAL_THESIS}}
Background: {{BACKGROUND}}
Typography: {{TYPOGRAPHY}}
Color_Palette: {{COLOR_PALETTE}}
Visual_Elements: {{VISUAL_ELEMENTS}}
Density_Guidelines: {{DENSITY_GUIDELINES}}
Style_Rules: {{STYLE_RULES}}
</STYLE_INSTRUCTIONS>

---
Type: Cover
Page: 1
---

// NARRATIVE GOAL
{{COVER_GOAL}}

// KEY CONTENT
[Title]: {{COVER_TITLE}}
[Arc Logic]: {{COVER_ARC}}
[Sub-headline]: {{COVER_SUBHEADLINE}}
[Key Insight]: {{COVER_INSIGHT}}
[Content / Data]: {{COVER_CONTENT}}
[Evidence / Trust Anchor]:
- Source: {{COVER_SOURCE}}
- As of: {{COVER_SOURCE_DATE}}
- Scope: {{COVER_SOURCE_SCOPE}}

// VISUAL DIRECTIVE
[Layout]: title-hero
[Visual Description]: {{COVER_VISUAL}}
[Chart Suggestion]: none

// SCRIPT
[Speaker Notes]: {{COVER_SPEAKER_NOTES}}
[Delivery Notes]: {{COVER_DELIVERY_NOTES}}

---
Type: Closing
Page: 2
---

// NARRATIVE GOAL
{{CLOSING_GOAL}}

// KEY CONTENT
[Title]: {{CLOSING_TITLE}}
[Arc Logic]: {{CLOSING_ARC}}
[Sub-headline]: {{CLOSING_SUBHEADLINE}}
[Key Insight]: {{CLOSING_INSIGHT}}
[Content / Data]: {{CLOSING_CONTENT}}
[Evidence / Trust Anchor]:
- Source: {{CLOSING_SOURCE}}
- As of: {{CLOSING_SOURCE_DATE}}
- Scope: {{CLOSING_SOURCE_SCOPE}}

// VISUAL DIRECTIVE
[Layout]: quote-callout
[Visual Description]: {{CLOSING_VISUAL}}
[Chart Suggestion]: none

// SCRIPT
[Speaker Notes]: {{CLOSING_SPEAKER_NOTES}}
[Delivery Notes]: {{CLOSING_DELIVERY_NOTES}}
```

## 硬检查

- `DECK_METADATA` 和 `STYLE_INSTRUCTIONS` 各出现一次且正确闭合。
- `Slide_Count` 是正整数，并与实际页数一致。
- 每页头只含 `Type` 和 `Page`；页码从 1 连续递增。
- 第一页为 `Cover`；两页及以上时最后一页为 `Closing`，中间页为 `Content`。
- 四个顶层区块按模板顺序各出现一次。
- 每个嵌套字段存在且非空。
- 最终稿不含双花括号占位符。

## 软提示与人工复核

- 标题是否足够直接、页面是否过密、证据是否足以支持主张，只产生提示。
- 故事线、图表选择、视觉质量、承诺风险和内容准确性必须人工复核。
