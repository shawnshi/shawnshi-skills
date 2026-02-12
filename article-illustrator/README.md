# article-illustrator
<!-- Input: Markdown article path or content strings. -->
<!-- Output: Illustration suite (PNG/WebP) + Annotated Markdown. -->
<!-- Pos: Creative/Output Layer. -->
<!-- Maintenance Protocol: Styles must be synced in 'references/styles.md'. -->

## 核心功能
基于文章语义深度分析，应用 'Type x Style' 二维矩阵生成结构化配图，拒绝无意义的隐喻。

## 战略契约
1. **语义对齐**: 严禁字面意义绘图，必须可视化底层概念（如：代码逻辑而非物理链条）。
2. **流程强制**: 必须经过 Outline 确认阶段方可进入像素生成，确保视觉逻辑与文字叙事同频。
3. **资产化管理**: 所有生成图必须自动记录 Prompt 种子与风格参数。
