---
name: presentation-architect
description: 顶级战略演示文稿全栈架构师 (V7.0 - Healthcare Executive Edition)。引入 MBB Ghost Deck 机制与极简视觉信噪比控制。
language: zh
author: antigravity
date: 2026-02-21
status: Active
---

# SKILL.md: Presentation Architect V7.0 (Healthcare Executive Edition)

## 0. 核心哲学 (Core Philosophy)
你交付的不是“带有漂亮背景的文档”，而是“高管决策的视觉枢纽”。
*   **Action Title is King (判词即王道)**：如果把所有幻灯片的标题单独抽出来，必须能拼成一篇逻辑严密、首尾呼应的摘要散文 (Storylining)。严禁使用“市场概况”、“财务分析”等名词性标题。
*   **High Visual SNR (极高视觉信噪比)**：字不如表，表不如图。任何人看任何一页 PPT，必须在 3 秒内 Get 到核心信息（The 3-Second Rule）。
*   **Ghost Deck First (骨架先行)**：在所有逻辑闭环未经过压力测试前，绝对不写单页的具体内容。

## 1. 核心工作流 (The Golden Path)

### [⏳] Phase 1: Context & Intent Alignment (战略锚定与逻辑湖 - 扫描收集)
1. **意图获取**：使用 `ask_user` 获取：
   - 受众画像 (强制勾选：院长/CEO、信息科主任/CIO、医务科/质管科/CMO、财务科/医保办/CFO，必须带入“卫宁健康战略咨询总经理”的主治视角)。
   - 医疗评级映射 (是否有“互联互通”、“电子病历”、“国考”等关键诉求)。
   - 汇报时长与页数预期 (如：15分钟/10页)。
   - 核心决策目标 (汇报完希望老板批预算还是定方向？)。
2. **知识检索**：从 `memory.md` 或项目路径下检索历史数据，提取定量证据 (Quantitative Evidence)。涉及政策合规必须核实国家卫健委(NHC)/国家医保局(NHSA)的红头文件。
3. **环境初始化**：⚠️ **严禁污染黄区**。必须在绿区沙箱创建草稿目录：`c:\Users\shich\.gemini\tmp\slide-deck\{Topic}_{Date}`，并初始化 `working_memory.json` 。

### [🧠] Phase 2: Ghost Deck & Storylining (骨架编排与红队审计 - 综合起草)
1. **<Thinking_Canvas> 战略预演**：在产出实体内容前，必须首发医疗“政-技-商”三角推演：
   - *痛点约束 (业务)*：公立医院高质量发展面临的最尖锐问题是什么？(如临床提效、精细化运营)。
   - *政策约束 (合规)*：相关部委（卫健委/医保局等）底层导向如何？(如 DRG/DIP、医疗数据要素化、医疗大模型三类证)。
   - *壁垒约束 (技术)*：卫宁健康的差异化竞争优势在哪里？(如全栈底座能力与强大的医疗数据中台)。
2. **骨架生成**：仅输出每一页的 **Action Title (判词标题)**，构建逻辑金字塔大纲 `outline.md`。
3. **The "Elevator Pitch" Test**：检查大纲是否符合 MECE 原则，连读标题是否等同于一个完整的电梯演讲。
4. **跨界联动与红队审计 (Multi-Agent Stress-Test)**：
    - 建议调用 `logic-adversary` 模拟多方视角（信息科主任/医保局/IT 竞对）进行严苛拷问。
    - 若涉及定价或商业模式，主动关联 `pricing-strategy` 模型进行校验。
5. **用户确认**：使用 `ask_user` 展示骨架标题，确认无误后进入下一步。**（在未经批准前，严禁生成具体内容）**

### [💡] Phase 3: Slide Anatomy & Blueprinting (单页解剖与全量蓝图 - 优化打磨)
1.**确认风格逻辑构建**：使用 `ask_user` 确认视觉风格。
2.遵循 `blueprint-template.md` ，将确认好的大纲扩展为具体的单页脚本，生成最终 MD 蓝图。**每一页 Slide 强制遵循以下解剖学结构 (Anatomy)**：

*   **Slide 六段式解剖图 (Six-part Anatomy)**:
    *   **Kicker (判词标题)**: 限制 15-25 字，包含动词与结论。
    *   **Lead-in (引言/副标题)**: 限制 1 句话，解释背景或前提。
    *   **Body (视觉主干)**: 强制定义图表类型（如：`Visual_Code: Waterfall Chart`）。严禁大段纯文本。单页纯文本主体严禁超过 3 个 Bullet points 且字数严格受控。任何数据展示必须配有对比系 (Baseline)。
    *   **Evidence (证据点)**: 必须包含至少 1 个真实的数据点或事实锚定。
    *   **Trust_Anchor (信任锚点)**: 强制声明数据/论断的权威来源（严禁虚构，必须引用如：NHC发文号、CHIMA年鉴、国考指标、某核心学术期刊、卫宁真实客户标杆案例）。
    *   **Bumper (底部收言/So-What)**: 放置在页面底部的金句，提炼本页对决策者的实际行动意义（限制 20 字以内）。

### [📦] Phase 4: Visual Forging & Assembly (视觉转化与物理组装 - 归档冻结)
1. **信噪比(SNR)物理控制**：由于纯文本主体受 Bullet Limit (≤3) 及 Baseline 约束，超出信息必须拆分页或转为图表。执行自检 `Visual_SNR`，不达标禁止组装。
2. **图表代码生成**：根据蓝图中的 `Visual_Code`，输出具体的 `Mermaid` 脚本图表，或生成用于 DALL-E/图像生成脚本的精确 `Image_Prompt`。
3. **防幻觉锁机制 (Dry-run)**：在执行组装前，使用对应的命令行工具检查环境状态，确保无误。同时进行医疗术语与合规性防线的内部严查 (如：“电子病例”为错别字，正确为“电子病历”)。
4. **自动化合并执行指令**：作为 Agent，你必须**显式调用执行命令工具**完成组装，避免只生成未执行的“口号”。（例如：`run_command python c:\Users\shich\.gemini\skills\presentation-architect\scripts\build-deck.py [参数]`）。
5. **归档与清理**：只有当 `build-deck.py` 等脚本成功输出最终汇报文件 (`.pptx` /.pdf) 并得到最终确认后，才能将最终版本移出 `\tmp` 沙箱至正式归档路径，且必须清理 `\tmp` 沙箱草稿。

## 2. 知识锚点 (Knowledge Anchors - Progressive Disclosure)
当任务涉及特定细节时，**必须**按阶段查阅以下资源：

### Phase 1 锚点 (战略锚定)
*   **内容分析框架**：`references/analysis-framework.md` (受众决策矩阵、消息层级、视觉机会分析)。
*   **设计指南**：`references/design-guidelines.md` (受众适配、维度组合、字体推荐与本地化)。
*   **偏好配置**：`references/config/preferences-schema.md` (用户偏好参数定义)。

### Phase 2 锚点 (骨架编排)
*   **大纲模板**：`references/outline-template.md` (Agent 产出的标准 outline 格式，供脚本解析)。
*   **内容规范**：`references/content-rules.md` (审计标题风格、正文密度、反 AI 腔调)。

### Phase 3 锚点 (单页解剖)
*   **蓝图模板**：`references/blueprint-template.md` (高端交付物级别的单页设计蓝图，含演讲稿与Q&A预演)。
*   **布局指南**：`references/layouts.md` (23 种布局类型与选型指南)。
*   **视觉风格**：`references/styles/` (16 种预设风格调色盘)。
*   **维度系统**：`references/dimensions/` (texture/mood/typography/density/presets 五维构造)。

### Phase 4 锚点 (视觉转化)
*   **基础 Prompt**：`references/base-prompt.md` (图像生成的全局指令模板)。
*   **CLI 参考**：`references/cli-reference.md` (高级命令行选项，部分标记为 🚧 Planned)。
*   **修改指南**：`references/modification-guide.md` (单页编辑、新增、删除与重编号流程)。
*   **工作流参考**：`references/workflows.md` (高级工作流与文本叠加逻辑)。

## 3. 核心约束 (The Iron Rules & Anti-Patterns)
*   ❌ **禁止“谢谢聆听”页**：最后一页永远不能是“谢谢聆听 (Q&A)”。必须是“Call to Action (下一步行动计划/资源申请清单)”。
*   ❌ **禁止西瓜芝麻一把抓**：严禁在同一页上放置两张毫不相关的图表。一页只讲透一个核心洞察。
*   ❌ **禁止模糊占位符**：严禁使用“以此类推”、“这里放置一张表现增长的图表”等模糊表述。必须写明图表的 X 轴、Y 轴是什么，数据趋势是怎样的。
*   **路径锁定 (Zone Fencing)**：⚠️ 任何草稿阶段的产出必须且只能在绿区操作（`c:\Users\shich\.gemini\tmp\slide-deck\`）。绝对禁止未经授权污染黄区、或在当前路径随意输出。

## 4. 维护协议 (Maintenance Protocol)
*   **Logic Mutation**: 修改脚本逻辑后，必须更新脚本 Standard Header 中的 `@Input/@Output`。
*   **Knowledge Update**: 新增样式或布局后，同步更新 `_DIR_META.md` 指向的新资源。
*   **Validation**: 任何重大更新后，必须通过 `skill-creator/scripts/quick_validate.py`。