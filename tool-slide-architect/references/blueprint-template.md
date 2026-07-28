# Blueprint Field Guide

机器输入的唯一 Schema 是 [outline-template.md](outline-template.md)。本文件只解释字段含义，不定义第二套格式，也不使用 `VISUAL_CODE`、独立 `LAYOUT` 或其他历史标记。

| 区块或字段 | 用途 |
| :--- | :--- |
| `DECK_METADATA` | 主题、受众、目标、语言、页数和生成日期 |
| `STYLE_INSTRUCTIONS` | 全局视觉规则；不是逐页内容 |
| `Type` / `Page` | 页面类型与连续页码 |
| `NARRATIVE GOAL` | 本页在故事线中的任务 |
| `Title` | 本页主要结论；技术页可使用准确的描述性标题 |
| `Arc Logic` | 与前后页面的逻辑关系 |
| `Sub-headline` | 支撑标题的限定或背景 |
| `Key Insight` | 听众需要记住的判断 |
| `Content / Data` | 页面可见的事实、数据或待决定事项 |
| `Evidence / Trust Anchor` | 来源、资料日期和适用范围 |
| `Layout` | 从布局库选择的布局名或清晰的自定义描述 |
| `Visual Description` | 构图、层级、图形与必要资产 |
| `Chart Suggestion` | 图表类型；不需要图表时写 `none` |
| `Speaker Notes` | 不应只是朗读页面的讲稿要点 |
| `Delivery Notes` | 停顿、转场、风险提示或问答准备 |

使用顺序：

1. 复制 `outline-template.md` 的代码块。
2. 增删 `Content` 页面并同步 `Slide_Count`。
3. 填完所有占位符。
4. 运行校验器。
5. 人工复核故事线、证据、视觉质量和承诺风险。
