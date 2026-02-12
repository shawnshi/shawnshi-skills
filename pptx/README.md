# pptx
<!-- Input: Content specs, templates, .pptx files. -->
<!-- Output: Professional slide decks, thumbnails, XML-level edits. -->
<!-- Pos: Creative/Output Layer (Visual Storytelling). -->
<!-- Maintenance Protocol: Update 'scripts/office/unpack.py' for XML structure changes. -->

## 核心功能
高阶幻灯片工程引擎。支持基于 `pptxgenjs` 的从零构建、基于 XML 的模板注入，以及涵盖 10 种专业配色的视觉系统设计。

## 战略契约
1. **视觉统治力**: 严禁生成只有文字的白底幻灯片，每一页必须包含视觉元素（图表、图标或形状），并遵循 60-30-10 颜色权重法则。
2. **严苛 QA**: 产出后必须执行 `Thumbnail -> Subagent Inspection` 流程，识别并修正元素重叠、文字溢出等视觉缺陷。
3. **XML 语义控制**: 涉及复杂排版变更时，必须通过 `unpack -> XML edit -> pack` 流程确保文件结构的专业性。
