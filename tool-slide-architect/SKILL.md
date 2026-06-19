---
name: tool-slide-architect
version: 12.0.0
tier: action-allowed
description: '幻灯片蓝图与讲稿架构师。结合 SCR 框架输出包含叙事、内容、视觉和讲稿的全息四维大纲。禁止生成满篇 Bullet Points 的空洞提纲，禁止未获用户骨架审批直接输出全文。'
triggers: ["写个PPT", "做个幻灯片大纲", "Ghost Deck", "幻灯片蓝图", "生成PPT骨架", "麦肯锡风格PPT"]
---

<strategy-gene>
Keywords: 幻灯片蓝图, Ghost Deck, SCR框架, MECE金字塔, 视觉克制, 讲稿生成, 结构化布局
Summary: 生产咨询与发布会级别的复合型 PPT 蓝图。将散乱信息通过 SCR 框架压制为判词驱动的骨架，输出全息四维大纲。
Strategy:
1. 1. 需求澄清：对齐受众、目的与约束。
2. 2. 架构输出：每页必须遵循 NARRATIVE GOAL, KEY CONTENT, VISUAL DIRECTIVE, Script 四大模块。
3. 3. 视觉克制：强制白/浅灰底色，强调色严格受限。
4. 4. 微批次防衰减：长篇内容分 `chunk_*.md` 写入。
AVOID: 满篇 Bullet Points；脱离图表指导的大段文字。
</strategy-gene>

# Tool Slide Architect (全息高管幻灯片蓝图引擎 V12.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `view_file` (强制读取 DESIGN.md)
2. `write_to_file` (写入沙盒 chunks)
3. `run_command` (执行校验与组装打包)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Clarification & Design Probe
1. **Clarification Gate**: 明确听众、核心诉求、篇幅。
2. **[DESIGN LOCK]**: 调用 `view_file` 读取 `C:\Users\shich\.gemini\pai\DESIGN.md`，执行大面积留白与高亮色的色彩约束。
3. 检索图谱或本地事实库获取核心数据支撑。

### Phase 2: 全息 Storyboard 结构约束
每一页草稿/正文的生成，必须按照以下 Markdown 骨架格式输出。不得遗漏任何一个主区块（以 `//` 开头的注释块必须保留作为视觉边界）：

```markdown
---
Type: Content
Bg: Surface #FFFFFF
Accent: Primary #005EB8
---

// NARRATIVE GOAL (叙事目标)
[一句话定义：本页试图在观众脑海中植入的绝对理念，或想要引发的情绪/决策。]

// KEY CONTENT (关键内容)
1. **[Lead-in / Action Title]**: (标题即判词，必须包含主语、谓语和定量数据或结论)
2. **[Arc & SCR Logic]**: (逻辑与叙事弧的双轨定位，如 [SCR: Complication] + [Arc: Hook])
3. **[Sub-headline]**: (副标题补充说明或关键推演结论)
4. **[Key Insight]**: (核心洞见 Kicker，用于页脚留信升华)
5. **[Key Content / Data Matrix]**: (强制二维表格或强结构化阵列，拒绝空洞 Bullet Points)

// VISUAL DIRECTIVE (视觉指令)
1. **[元数据控制]**: (阐述 YAML Header 中指定的背景颜色和强调色锁定策略)
2. **[LAYOUT 布局结构]**: (例如：左右分割布局，左侧30%为核心结论（深色底），右侧70%为数据图表（浅色底）)
3. **[VISUAL 视觉画面]**: (描述具体的图像内容。强调信息图表化，严禁通用素材/握手假图)
4. **[Chart Suggestion & Visual Restraint]**: (指定具体的图表类型，如瀑布图/散点图。注：若本页 Type 为 Cover 或 ExecSummary，此项可填 N/A 或仅提供文字排版建议，无需硬凑数据图表)

// Script (演讲讲稿)
* **[演讲逐字稿]**: (符合口语化风格的串词，严禁直接读 PPT 内容)
* **[演讲注意事项]**: (肢体语言、停顿点、语气加重提示)
```

### Phase 3: 断点与微批次防衰减
1. **[BREAKPOINT]**: 生成全量正文前，挂起输出“骨架总览”，索要人类审批。
2. **[GLOBAL STYLE DEFINITION]**: 在最终输出的最顶端（或 `chunk_1.md`），包含以下全局视觉风格声明：

```markdown

## 1. 视觉风格指令 (Style Instructions)
<STYLE_INSTRUCTIONS>

Design Aesthetic: [基于主题定制的风格，如：包豪斯工业风、未来主义医疗风等]

Background Color: [十六进制代码]

Primary Font: 用于所有幻灯片标题和主要标题。

Secondary Font: 用于正文、副标题和注释。

Color Palette: [主色、辅助色、强调色的十六进制代码及用途]

Visual Elements: [具体的图形处理手法]

</STYLE_INSTRUCTIONS>
```

3. **[MINIBATCH ENFORCEMENT]**: 获批后落盘至 `<appDataDir>\brain\<conversation-id>\scratch\slides\{Topic}\`。若页数 > 8，分拆为 `chunk_*.md` 分批写入。

### Phase 4: Validation Gate (门检与打包)
执行 `validator.py` 验证核心区块完整性，通过 `build-deck.py` 组装并生成 `telemetry.json` 遥测文件。

## 2. <Contracts> (输出与交付契约)
- **四维全息契约**：单页幻灯片须通过 Goal, Content, Visual, Script 联合渲染。
- **视觉约束契约**：浅色底板，数据导向的高亮色。
- **讲稿口语化契约**：Script 必须是自然的讲解人声。

## 3. <Failure_Taxonomy> (失败分类学)
- **结构坍塌**：漏掉 `VISUAL DIRECTIVE` 或 `Script`。
- **视觉污染**：违背大面积留白规范，过度使用重色块。
- **骨架空洞症**：使用空洞形容词缺乏数据/图表骨架支撑。
