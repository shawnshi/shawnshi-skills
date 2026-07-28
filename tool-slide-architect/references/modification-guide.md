# Blueprint Revision Guide

本技能只维护 `outline.md` 和 `blueprint_bundle.json`。图片、PPTX 和 PDF 属于后续演示文稿构建流程，不在这里直接修改或重生成。

## 修改单页

1. 在 `outline.md` 中定位对应的 `Page`。
2. 只修改该页的四个顶层区块及其已声明字段。
3. 若增删页面，同步更新页码、`Type` 和 `Slide_Count`。
4. 运行 `scripts/validator.py`。
5. 运行 `scripts/build-deck.py` 重新生成 JSON 包。
6. 人工复核故事线、证据、视觉质量和承诺风险。

## 修改全局风格

只修改 `STYLE_INSTRUCTIONS`。不要在单页内创建另一套全局风格，也不要改变字段名来表达设计偏好。

## 修改数据或主张

- 同步更新 `Content / Data` 与 `Evidence / Trust Anchor`。
- 实际数字要保留来源、资料日期和适用范围。
- 没有证据时保留为草稿信息缺口；最终交付不得保留占位符。
- 标题风格、页面密度和章节重叠只作人工复核，不作为结构错误。

## 完成条件

- 校验器没有 `errors`。
- JSON 包的页数、页面类型和字段与 `outline.md` 一致。
- 未把 JSON 包误报为 PPTX。
- 物理演示文稿如由其他能力构建，应另行验证页数、可打开性、字体、图表和来源。
