---
name: tool-slide-architect
description: 设计、审阅和重构高管汇报、咨询路演、战略方案、项目进展、提案、培训材料与单页演示的叙事结构、逐页蓝图和讲稿；也用于把复杂材料改造成决策型 PPT 大纲，或为实际 PowerPoint/PPTX 制作提供可验证的内容交接。
---

# Slide Architect

把演示文稿设计成可追溯、可修改、可交付的叙事蓝图。蓝图不是 `.pptx`；只有用户需要实际演示文稿时才进入 PPT 构建与物理 QA。

## Production flow

1. **建立 brief**：确认受众、决策或学习目标、场合、时长、语言、比例、保密级别、资料截止日期、品牌模板、必须保留内容和交付物。信息足够时直接推进；只有缺口会改变故事线或风险边界时才提问。
2. **选择叙事**：读取 [workflows.md](references/workflows.md)，在 `decision / strategy / status / proposal / educational / single-slide / revision` 中选择主模式。先写一句核心主张，再确定最小充分故事线。
3. **编写蓝图**：严格使用 [outline-template.md](references/outline-template.md) 的 v2 Schema。选择 `full / section / one_pager`，使用稳定唯一的 `Slide_ID`；页面类型与必填记录按页面任务选择。从零开始且模式、页数已知时可用 `scripts/scaffold.py` 生成结构合规的草稿骨架，但必须替换其示例文案。迁移旧稿时按 [modification-guide.md](references/modification-guide.md) 调用 `scripts/migrate_v1.py`，再人工复核。
4. **分离判断层级**：把事实、推断、假设、建议分别写为 `Claims` 记录；用 ID 将主张与证据连接。未知内容写入 `Open Items`，风险写入 `Risk Flags`，不得用虚假确定性补齐。
5. **设计信息表达**：按需读取 [content-rules.md](references/content-rules.md)、[design-guidelines.md](references/design-guidelines.md)、[layouts.md](references/layouts.md) 和选定的单个样式文件。样式入口是 [styles/index.json](references/styles/index.json)；不要默认加载全部样式或维度文件。
6. **行业合规**：医疗、政府、金融材料必须核对隐私、脱敏、资产授权、保密、数据地域与政策适用性。界面截图、患者/客户信息、品牌元素和第三方图片仅在获得授权且完成必要脱敏后使用。
7. **校验与人工复核**：页面重排后用 `scripts/renumber.py` 修复 `Page`，不改变 `Slide_ID`；再运行 `scripts/validator.py`。它只做结构校验（`validation_scope: structural`）；结构、日期、引用、拓扑和最终稿未结构化占位符等错误必须阻断。结构通过不代表可发布，故事线、数字真实性、视觉质量、承诺风险和法规适用性仍需人工复核。
8. **按交付物分流**：
   - 只要故事线或逐页蓝图：交付已验证的 `outline.md`，无需 JSON。
   - 需要机器交接或实际 `.pptx`：运行 `scripts/build-deck.py` 生成 JSON handoff，再读取 [pptx-handoff.md](references/pptx-handoff.md)，交给可用的演示文稿能力构建、渲染并做物理 QA。

## Draft and final

- `Status: draft`：允许未闭合项，但必须通过 `Open Items` 明确责任人和计划日期；占位符会产生警告。
- `Status: final`：禁止 moustache、`TBD`、`TODO`、`待补`、`待确认`、`待核验`、`[INSERT]`、`[BASELINE]` 等未结构化占位符。允许保留结构化 `unverified` Claims 和 Open Items，但必须如实呈现状态、责任人和后续动作；资产授权或脱敏仍为 pending 时保持 `draft`。
- 最终稿不得把 `none` 当作规避证据责任的写法。没有证据支撑的事实必须准确降级为推断或假设、建立结构化开放项，或删除。

## Release rules

- `Deck_Mode: full` 的第一页使用 `Cover`；叙事必须以 `Closing` 或 `Decision` 结束，终点之后只允许 `Appendix` 或 `References`。
- `section` 和 `one_pager` 不强制封面或叙事终点；`one_pager` 可使用除 `Appendix`、`References` 外的任意页面类型。
- `Data` 与 `References` 必须含有效 Evidence 记录；`Decision` 必须含 Decision 记录；`Risk` 必须含 Risk Flags 记录。
- 存在 Evidence 记录时，`Citation_Treatment` 不能使用 `not-applicable`。
- 引用、保密标记和经授权的品牌元素属于必要信息，不得因样式偏好而删除。
- 不把 JSON 包称为 PPT，不把未做渲染检查的 `.pptx` 称为最终版。

## Reference routing

- 场景故事线：[workflows.md](references/workflows.md)
- v2 唯一机器 Schema：[outline-template.md](references/outline-template.md)
- 字段语义与记录格式：[blueprint-template.md](references/blueprint-template.md)
- 论证分析：[analysis-framework.md](references/analysis-framework.md)
- 内容、证据与合规：[content-rules.md](references/content-rules.md)
- 设计与可访问性：[design-guidelines.md](references/design-guidelines.md)
- 页面布局：[layouts.md](references/layouts.md)
- 修订既有材料：[modification-guide.md](references/modification-guide.md)
- 命令用法：[cli-reference.md](references/cli-reference.md)
- 实际 PPT 交接：[pptx-handoff.md](references/pptx-handoff.md)
