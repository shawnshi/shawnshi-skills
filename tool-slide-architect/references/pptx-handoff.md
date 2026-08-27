# PPTX handoff and physical QA

只在用户需要实际 PowerPoint/PPTX，或明确需要机器可读交接时读取本文件。蓝图交付不需要 JSON。

## Preconditions

1. `outline.md` 已运行结构校验，报告包含 `validation_scope: structural`。
2. 人工复核已覆盖核心主张、数字、引用、政策适用性、承诺和保密边界。
3. 计划进入实际 PPT 的 Assets 均为 `owned / licensed / public-domain`，且脱敏状态为 `not-required / verified`。
4. `Template_Ref`、比例、语言、字体回退和必要品牌规则已确认。

存在 `permission-pending` 或脱敏 `pending` 的资产时，不得把它嵌入最终物理文件。可用经过许可的替代资产或明确的非敏感占位形状继续构建草稿。

## Create the handoff

运行 `scripts/build-deck.py` 生成 `blueprint_bundle.json`。JSON 是受验证 Schema 的结构化副本，不是 `.pptx`，也不证明内容正确或可发布。

Handoff 应保留：

- deck metadata、style instructions 和 `Slide_ID`；
- 页面类型、区块和记录关联；
- Claim、Evidence、Open Item、Risk、Decision 和 Asset 状态；
- 结构校验结果及 `validation_scope: structural`。

## Build the PPTX

将 JSON handoff 与已授权模板/资产交给当前可用的演示文稿能力：

1. 映射 `Slide_ID` 到实际页，不用页码作为稳定标识。
2. 保持页面可见内容与 Claim 状态一致；不要在构建时擅自强化结论。
3. 按 `Citation_Treatment` 放置可见引用；保留保密标记和必要品牌元素。
4. 图表使用已核验数据、单位和范围；不得从视觉稿反推数值。
5. 讲稿写入 notes 区，而不是压缩到页面正文。
6. Appendix 和 References 保持在叙事终点之后。

## Physical QA loop

1. 保存 `.pptx` 后渲染所有页面为 PNG 或 PDF。
2. 逐页检查标题断行、文本溢出、对象重叠、边缘裁切、字体替换和图像分辨率。
3. 检查图表数据、轴、单位、图例、直接标签、引用和来源定位。
4. 检查保密标记、页码、Logo、模板一致性和 CJK/非拉丁字形。
5. 检查所有截图与资产的权利、脱敏和可识别信息。
6. 对照 JSON 检查页面遗漏、顺序、`Slide_ID`、Decision、Risk 和 Open Items。
7. 修复后重新渲染；重复到无阻断问题。

## Completion language

- 只有蓝图：称为“已验证结构的演示蓝图”，不要称为 PPT。
- 已生成但未完成渲染 QA：称为“PPT 草稿”。
- 完成内容、合规和物理 QA 后，才称为“最终 PPT”。
