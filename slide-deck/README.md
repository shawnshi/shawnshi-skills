# slide-deck
<!-- Input: Markdown content, style selection, language flags. -->
<!-- Output: Presentation images, professional .pptx/.pdf files. -->
<!-- Pos: Narrative/Visual Output Layer (The Architect). -->
<!-- Maintenance Protocol: Sync 'scripts/generate-images.py' with rendering API updates. -->

## 核心功能
基于语义分析的幻灯片架构师。支持“断点续传”渲染逻辑，通过将 Markdown 直接转化为具备专业商务风格的演示文稿，实现叙事的可视化跃迁。

## 战略契约
1. **可编辑逻辑**: 优先使用 `--editable-text` 模式，确保生成的 PPT 具备原生文本框，方便下游手动微调。
2. **断点容错**: 强制维护 `status.json`，在网络中断或生成失败时支持从断点位置物理续传，杜绝重复渲染。
3. **大纲确认**: 生成像素前必须产出 `outline.md` 并获得用户对视觉逻辑的最终确认。
