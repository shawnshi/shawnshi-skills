---
name: tool-slide-architect
version: 14.0.0
tier: action-allowed
description: '全息高管幻灯片蓝图与路演策划引擎 (DBS-Resonate Edition)。结合 SCR 框架与 DBS 五维传播心理学，输出具备认知劫持能力的幻灯片骨架，并直译为 Web-Slide 兼容契约。具备“无效干货排异”与“视听双轨洗脑”指令。'
triggers: ["写个PPT", "做个幻灯片大纲", "Ghost Deck", "幻灯片蓝图", "生成PPT骨架", "麦肯锡风格PPT"]
---

<strategy-gene>
Keywords: 幻灯片蓝图, 认知劫持, 五维雷达, 双轨制讲稿, 无效干货排异, SCR框架
Summary: 生产具备现实扭曲力场的咨询级路演 Deck。利用传播心理学重构内容张力，将散乱信息通过 SCR 框架压制为判词驱动的骨架，输出全息视听大纲。
Strategy:
1. 1. 协议直连：架构必须与 `tool-web-slide` 的 `spec_lock.md` 规范无缝接轨。
2. 2. 五维雷达前置：在生成架构前，进行整包级心理扫描（沉默解除、立场框架等），锁定听众情绪。
3. 3. 干货陷阱排异：精准重于全面。所有数据矩阵必须具备逻辑推演或制造认知落差的作用，拒绝毫无意义的参数罗列。
4. 4. 双轨洗脑拆分：视觉图表负责“理性压制”，Teleprompter 讲稿负责“情绪刺穿与立场宣发”。
5. 5. 异步资产：使用子代理并发生成高质量图表素材。
AVOID: 纯数据罗列的“干货陷阱”；讲稿直接朗读 PPT 上的文字。
</strategy-gene>

# Tool Slide Architect (全息高管幻灯片蓝图引擎 V14.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `view_file` (强制读取 `C:\Users\shich\.gemini\pai\DESIGN.md`)
2. `view_file` (强制读取 Web-Slide 版式：`C:\Users\shich\.gemini\config\skills\tool-web-slide\references\layout-patterns.md`)
3. `invoke_subagent` (可选：派发资产生成任务)
4. `write_to_file` (输出包含幻灯片骨架的 `spec_lock.md` 或 `chunk_*.md`)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 5D Resonance Radar & Design Probe (心理定调与门禁左移)
1. **五维心理阵列定调 (DBS Radar)**: 动笔前，评估整套幻灯片必须实现的精神控制力：
   - *沉默解除*：戳穿了听众什么心照不宣的痛点？
   - *立场框架*：我们的内容阵营在哪？在替谁发声讨伐谁？
   - *信念结构*：将打破听众什么旧常识，建立什么新标准？
2. **[TOKEN LOCK]**: 严格限制在 Web-Slide 预定义的 CSS 变量和 Layout ID 中进行挑选。严禁凭空捏造。

### Phase 2: 全息 Storyboard 结构约束 (认知劫持骨架)
每一页正文生成必须遵循以下 Markdown 骨架格式。禁止任何无推演意义的“大字报”或“清单展示”：

```markdown
---
Type: Content
Bg: Surface #FFFFFF
Accent: Primary #005EB8
---

// PSYCHOLOGICAL ANCHOR (心理靶点)
[一句话定义本页目标：本页用来打破听众的什么幻觉？或用来提供什么情绪宣泄/不可辩驳的证据？基于五维雷达。]

// KEY CONTENT (关键内容)
1. **[Hijack Title / 认知劫持标题]**: (不再是枯燥判词，必须制造认知落差。例如用反直觉的陈述或尖锐的提问)
2. **[Arc & SCR Logic]**: (定位叙事弧，如 [SCR: Complication] 激化矛盾)
3. **[Sub-headline]**: (数据结论或逻辑推演结果)
4. **[Key Insight]**: (核心洞见，用作页脚留信重锤)
5. **[Data Matrix / 无效干货排异区]**: (强制二维表格或结构化阵列。**注意**：所有罗列的数据必须附带一条推演结论或刺眼的反差比，不准单纯堆砌中立事实)

// VISUAL DIRECTIVE (视觉指令 & spec_lock)
1. **[Layout Combination]**: (精确指定 Web-Slide 版式，例如 `Layout: #Primary-Split + #Mod-FloatCard`)
2. **[CSS Tokens]**: (合法的预设字典背景色/强调色)
3. **[Image Asset URL]**: (占位路径或真实路径)
4. **[Subagent Dispatch]**: (是否需派发给 `tool-drawio` 绘制拓扑？)

// Script (演讲讲稿 - 双轨制控制链)
* **[底层逻辑说明]**: 画面负责“理性证据”，声音负责“感性洗脑”。严禁让演讲者念 PPT 上的原话！
* **[逐字演讲稿]**: (从一个反常识的切入点开始，利用屏幕上的图表做引子，向听众输出强烈的立场与情绪。这是被注入 `data-presenter-notes` 的武器)
* **[演绎提示]**: (肢体动作、长停顿制造压迫感、重音提示)
```

### Phase 2.5: 医疗数字化 (HIT) 专属会议级约束 [HIT_CONSTRAINT]
1. **[底层逻辑]**: 放弃 C 端互联网流量叙事。价值必须落在：临床质控、医护减负、DRG/DIP 降本增效、评级过审上。
2. **[视觉底盘]**: 彻底摒弃空洞科技风。强制要求使用真实的临床业务拓扑图、数据治理流向图或高密度 ROI 对比。
3. **[用词脱水]**: 严禁“赋能”、“颠覆”。强制切换为临床/架构黑话，如：“全院级数据湖底座”、“互联互通标准化”。

### Phase 3: Asynchronous Media Orchestration (资产异步管线)
确立图表需求时，直接使用 `invoke_subagent` 派发任务至 `image-nano-gen` 或 `tool-drawio`。

### Phase 4: 断点与微批次防衰减
1. **[BREAKPOINT]**: 全量正文前，挂起输出包含《五维心理雷达定调》与《骨架总览》的报告，索要人类审批。
2. 获批后落盘至包含 `<STYLE_INSTRUCTIONS>` 声明的 `spec_lock.md`，用于直连渲染引擎。

## 2. <Contracts> (输出与交付契约)
- **四维全息契约**：单页幻灯片须通过 Anchor, Content, Visual, Script 联合渲染。
- **干货排异契约**：拒绝平庸的说明书式展示。每一页必须“杀一个怪”或“立一个靶子”。
- **双轨解耦契约**：视觉呈现实质性证据，听觉（讲稿）负责情绪共振。

## 3. <Failure_Taxonomy> (失败分类学)
- **无效干货陷阱 (Dry-Goods Trap)**：幻灯片充斥着无情绪导向的参数与中立描述，未制造任何认知落差。
- **双轨同质化 (Dual-Track Homogenization)**：讲稿内容只是对 `[Key Content]` 的生硬复述，未能补充立场与情感穿透力。
- **外行黑话症**：使用“生态赋能”等非临床/非架构虚假术语。
