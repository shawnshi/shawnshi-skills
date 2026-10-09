---
name: tool-slide-architect
description: 设计、审阅和重构高管汇报、咨询路演、战略方案、项目进展、提案、培训材料与单页演示的叙事结构、逐页蓝图和讲稿；也用于把复杂材料改造成决策型 PPT 大纲，或为实际 PowerPoint/PPTX 制作提供可验证的内容交接。
---

# Slide Architect

把演示文稿设计成可追溯、可修改、可交付的叙事蓝图。蓝图不是 `.pptx`；只有用户需要实际演示文稿时才进入 PPT 构建与物理 QA。

## Delivery depth

- **轻量叙事**：只要三句话故事线、标题顺序或局部建议时，直接给请求粒度的文本；不强制 v2 Schema、脚手架、校验脚本或文件。仅按需读取对应叙事参考，保留用户事实、限定条件和已知缺口。
- **完整蓝图**：逐页蓝图、大纲文件或结构化修订使用 v2 Schema，并做结构校验；不默认生成 JSON。`outline.md` 指格式契约，不意味着用户批准保存；明确“不保存”时交付同样结构的正文，用编码已验证的内存/标准输入通道校验，不落盘。
- **机器交接/实际演示**：在完整蓝图基础上按请求生成 JSON；只有用户需要实际 PPTX/HTML 才进入对应构建与渲染流程。授权和读取前隐私门适用于所有层级，不因轻量路径而跳过。

## Production flow

以下完整流程用于逐页蓝图与机器交接；轻量请求只执行读取前隐私门、必要 brief 和事实/语义复核，不自动运行其余步骤。

0. **读取前隐私门**：先依据用户说明和最小必要文件元数据核对源材料、现有授权与会话边界，再读取正文或截图。高度敏感的患者、第三方客户、合同或财务材料遵循适用运行时隐私合同；当前个人日记/健康或个人投资例外不自动覆盖第三方材料。必要隔离或授权不足时停在读取之前，请用户提供已脱敏的最小输入或合规会话。既有明确授权覆盖时不重复确认。`Confidentiality` 标签不是读取或外传许可；`--no-session` 也不保证扩展的工具归档或临时文件不落盘，须核对实际归档边界。行业合规步骤不能代替此入口门。
1. **建立 brief**：确认受众、决策或学习目标、场合、时长、语言、比例、保密级别、资料截止日期、品牌模板、必须保留内容和交付物。信息足够时直接推进；只有缺口会改变故事线或风险边界时才提问。
2. **选择叙事**：读取 [workflows.md](references/workflows.md)，在 `decision / strategy / status / proposal / educational / single-slide / revision` 中选择主模式。先写一句核心主张，再确定最小充分故事线。
3. **编写蓝图（非轻量路径）**：严格使用 [outline-template.md](references/outline-template.md) 的 v2 Schema。选择 `full / section / one_pager`，使用稳定唯一的 `Slide_ID`；页面类型与必填记录按页面任务选择。从零开始且模式、页数已知时可用 `scripts/scaffold.py` 生成结构合规的草稿骨架，必须补齐其可检测的 `{{...}}` 字段，不得仅改 Status。迁移旧稿时按 [modification-guide.md](references/modification-guide.md) 调用 `scripts/migrate_v1.py`，核对保留约束和开放项，再人工复核。
4. **分离判断层级**：类型与核验状态是独立维度；完整蓝图分别写为 `Claims`，用 ID 关联证据、Open Items 和 Risk Flags。未核验的事实性陈述保留 `fact` 类型并标 `unverified`，在可见内容或讲稿说明边界；只有真实论证性质改变时才改为推断或假设。轻量文本沿用同一语义区分，但不强制记录格式。
5. **设计信息表达**：按需读取 [content-rules.md](references/content-rules.md)、[design-guidelines.md](references/design-guidelines.md)、[layouts.md](references/layouts.md) 和选定的单个样式文件。样式入口是 [styles/index.json](references/styles/index.json)；不要默认加载全部样式或维度文件。
6. **行业合规**：医疗、政府、金融材料必须核对隐私、脱敏、资产授权、保密、数据地域与政策适用性。界面截图、患者/客户信息、品牌元素和第三方图片仅在获得授权且完成必要脱敏后使用。
7. **校验与人工复核（v2 蓝图）**：页面重排后用 `scripts/renumber.py` 修复 `Page`，不改变 `Slide_ID`；再运行 `scripts/validator.py`。它只做结构校验（`validation_scope: structural`）；结构、日期、引用、拓扑和最终稿未闭合占位符等错误必须阻断，教学字面量按 Schema 的窄化规则处理。结构通过不代表可发布，故事线、数字真实性、视觉质量、承诺风险和法规适用性仍需人工复核。记录实际复核主体与范围；模型自审不是人工或独立审查，尚未完成的复核不得标为已完成。
8. **按交付物分流**：
   - 轻量叙事：直接交付用户请求的文本，不生成蓝图或 JSON 文件。
   - 完整逐页蓝图：交付已验证结构的 v2 正文，仅在获准保存时写为 `outline.md`；无需 JSON。
   - 机器交接或实际 `.pptx`：先读取 [pptx-handoff.md](references/pptx-handoff.md)，再按相应前置条件运行 `scripts/build-deck.py` 生成 JSON。实际文件交给可用的演示文稿能力构建、渲染并做物理 QA；全局指令变化须遵循交接的全量重建标记。

## Draft and final

- `Status: draft`：允许未闭合项，但必须通过 `Open Items` 明确责任人和计划日期；占位符会产生警告。
- `Status: final`：禁止未闭合的 moustache、`TBD`、`TODO`、`待补`、`待确认`、`待核验`、`[INSERT]`、`[BASELINE]` 等占位符；正文/讲稿的精确字面量例外见 [Schema](references/outline-template.md#draft-and-final-validation)，不用于掩盖缺失数据。允许结构化 `unverified` Claims 和 Open Items，但必须如实呈现状态、责任人和后续动作；资产授权或脱敏仍为 pending 时保持 `draft`。
- 不用 `none` 规避证据责任，不用改 Claim 类型代替核验。缺证的事实性陈述应保留真实类型、标明未核验并建立开放项，必要时从交付中删去该陈述；已知事实不得为过校验而改写成假设。Status 也不证明人工、合规或物理 QA 已完成。

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
