# Deck Blueprint Page Template (MBB Reference)

<!-- 
Pos: C:\Users\shich\.gemini\skills\deck-blueprint\TEMPLATE.md
Vision: 每一页幻灯片的极致结构化定义
-->

## 页面设计蓝图规范

### Page [X]: [叙事性主题句 - 严禁描述性标题，必须包含观点/结论]

---

**// NARRATIVE GOAL (叙事目标)**
> [解释本页在 SCQA 或金字塔故事线中的核心作用。它解决了听众的哪个疑虑？或者为下一页的哪个结论做了什么铺垫？]

**// KEY CONTENT (关键内容)**
*   **Headline:** [有穿透力的主标题，直接回答“So What?”]
*   **Sub-headline:** [核心支撑逻辑或二级结论，用于快速浏览]
*   **Body/Data & Evidence:**
    *   [论据 1]: 源于素材的核心事实。`[Source: ...]`
    *   [数据点]: 具体数值、百分比或对比维度。
    *   [必须保留的细节]: 行业专有名词或特定约束条件。

**// VISUAL_CODE (结构化视觉微码)**
```json
{
  "chart_type": "[图表类型: 如 Waterfall, Radar, Pyramid, Comparison]",
  "layout_logic": "[1/3 Split, Golden Ratio, Centered Focus]",
  "key_elements": ["[元素1]", "[元素2]"],
  "visual_metaphor": "[核心视觉隐喻]",
  "automation_prompt": "[供下游生成的提示词摘要]"
}
```

**// VISUAL_DESCRIPTION (视觉画面详述)**
> [详细描述构图、配色、阴影效果。例如：左侧 40% 放置核心断言文字，右侧 60% 为高对比度的趋势图表。]

**// LAYOUT (布局结构)**
> [例如：1/3 垂直分割布局。左侧为结论区（高对比度底色），右侧为详情区（白色背景），视线从左上角标题引导至右侧数据。]

**// Script (演讲脚本)**
*   **逐字稿**: [语气：专业、坚定、富有启发性。]
*   **注意事项**: [例如：此处需停顿 2 秒以增强视觉冲击力；注意强调数据背后的不确定性。]

---

## 视觉风格特别准则 (Poster-style Slides)

### 封面 (Title Slide)
*   **风格**: 海报式布局 (Poster-style)。
*   **视觉**: 满版出血大图 (Full-bleed) 或 极端简约的几何构图。
*   **文字**: 只有主标题、副标题和品牌标识，严禁任何细碎文字。

### 封底 (Closing Slide)
*   **风格**: 行动锚点式 (Call to Action)。
*   **视觉**: 与封面遥相呼应，强调核心愿景。
*   **文字**: 一个强有力的金句或一个清晰的下一步行动建议。
