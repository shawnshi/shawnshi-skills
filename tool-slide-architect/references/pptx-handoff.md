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

- deck metadata、style instructions 和原始 `Slide_ID`（不得改写）；
- 页面类型、区块和记录关联；
- Claim、Evidence、Open Item、Risk、Decision 和 Asset 状态；
- 结构校验结果及 `validation_scope: structural`。

## Web handoff（人工映射契约）

用户选择 HTML 时，按 [Web 交付契约](../../tool-web-slide/references/delivery-contract.md) 人工构建；`build-deck.py` 只生成蓝图 JSON，没有已实现的自动 Web 适配器。

- 保留原始 `Slide_ID` / JSON `slide_id`；另存 source ID → target `data-slide-id` 对照表随交付提供。目标 ID 按源 ID 的 ASCII 大写转小写、每段非 `[a-z0-9]` 字符替换为 `-`、去除首尾 `-` 的顺序确定性映射；例如 `S001` → `s001`。结果须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`。
- 空结果或碰撞（如 `S001` 与 `s001`）立即拒绝交接，等待显式映射确认；不得静默追加页码、去重或改写源 ID。显式映射也须合法、唯一并固定保存，重排页面不改变它。
- 保留页数与源 `slides` 数组顺序，显式填写 Web `slides.order`；逐页对照 Claims、Evidence 及关联 ID/状态、speaker notes、Open Items（责任人/日期）、Risk、Decision 与资产授权。讲稿放入目标支持的讲稿区域；不能无损承载的字段保存在随附蓝图和对照表中并明确限制，不得丢弃或强化结论。
- 技术图复用同一份规范化 JSON 生成 SVG/按需 draw.io，按 [技术图 QA](../../technical-diagram-renderer/references/output-qa.md) 核对节点、边方向、不确定性及 draw.io 语义降级，不从图片重建事实。

## Build the PPTX

将 JSON handoff 与已授权模板/资产交给当前确实可用的演示文稿能力；仅在本地已具备且可验证时使用 officecli 或其他 PPTX 工具，不假定存在名为 `Presentations` 的能力。缺少构建或渲染能力时交付蓝图并明确未完成步骤，不把 JSON/HTML 改名伪装成 PPTX：

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
