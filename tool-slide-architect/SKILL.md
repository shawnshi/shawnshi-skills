---
name: tool-slide-architect
version: 15.1.0
tier: action-allowed
description: '全息高管幻灯片蓝图与路演策划引擎 (Winston-DBS Edition)。在认知劫持基础上融合 Winston 演讲工具箱，引入“价值承诺起手”、“核心贡献定格”、“抗掉线地标”及“7秒沉默锁”，打造不可辩驳的物理级场控演示大纲。'
triggers: ["写个PPT", "做个幻灯片大纲", "Ghost Deck", "幻灯片蓝图", "生成PPT骨架", "麦肯锡风格PPT"]
---

<strategy-gene>
Keywords: 幻灯片蓝图, 认知劫持, 五维雷达, 价值承诺, 核心贡献定格, 7秒沉默锁, 语言地标
Summary: 生产具备现实扭曲力场的咨询级路演 Deck。利用传播心理学重构内容张力，将散乱信息通过 SCR 框架压制为判词驱动的骨架，输出全息视听大纲。
Strategy:
1. 1. 协议直连：架构必须与 `tool-web-slide` 的 `spec_lock.md` 规范无缝接轨。
2. 2. 五维雷达前置：在生成架构前，进行整包级心理扫描（沉默解除、立场框架等），锁定听众情绪。
3. 3. 思想护城河与干货排异：精准重于全面。所有数据必须具备逻辑推演意义，并明确划出“他人观点”与“我们独家洞见”的【边界 (Fence)】。
4. 4. 双轨洗脑与场控：视觉图表负责“理性压制”，讲稿必须集成停顿与物理交互指令（如指板书、道具）。
5. 5. 异步资产：使用子代理并发生成高质量图表素材。
AVOID: 讲稿朗读 PPT 文字；使用“笑话”开场；使用“Thank You/Q&A”收尾。
</strategy-gene>

# Tool Slide Architect (全息高管幻灯片蓝图引擎 V15.1 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `view_file` (强制读取 `C:\Users\shich\.gemini\pai\DESIGN.md`)
2. `view_file` (强制读取 Web-Slide 版式：`C:\Users\shich\.gemini\config\skills\tool-web-slide\references\layout-patterns.md`)
3. `invoke_subagent` (可选：派发资产生成任务)
4. `write_to_file` (写入沙盒路径，并配置 `ArtifactMetadata.RequestFeedback=true` 触发门禁)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 5D Resonance Radar & Design Probe (心理定调与门禁左移)
1. **五维心理阵列定调 (DBS Radar)**: 动笔前，评估整套幻灯片必须实现的精神控制力：
   - *沉默解除*：戳穿了听众什么心照不宣的痛点？
   - *立场框架*：我们的内容阵营在哪？在替谁发声讨伐谁？
   - *信念结构*：将打破听众什么旧常识，建立什么新标准？
2. **[TOKEN LOCK]**: 严格限制在 Web-Slide 预定义的 CSS 变量和 Layout ID 中进行挑选。严禁凭空捏造。

### Phase 2: 全息 Storyboard 结构约束 (认知劫持骨架)
#### 特殊首尾约束 (Golden Opening & Closing)
1. **首段开场 (Page 1)**：严禁使用客套或笑话开场。必须以 `[Value Promise / 价值承诺]` 为核心结构，明确告知观众 1 小时后能获得什么未知认知。
2. **收尾定格 (Last Page)**：严禁生成带有 "Thank You"、协作者名单或 "Q&A" 的退场页。最后一页强制锁定为 `[Key Contributions / 核心贡献]` 提纯，用于在问答环节长达 20 分钟地霸占大屏。

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
2. **[Arc / Landmark Logic]**: (定位叙事弧，或将其作为 `Verbal Punctuation` 语言地标，帮助掉线听众重新跟上逻辑)
3. **[Sub-headline]**: (数据结论或逻辑推演结果)
4. **[Key Insight]**: (核心洞见，用作页脚留信重锤)
5. **[Data Fence / 护城河隔离区]**: (强制二维表格或对立阵列。必须在排版上建立边界，明确切分“他人平庸共识”与“我们的独家洞见”)

// VISUAL DIRECTIVE (视觉指令 & spec_lock)
1. **[Layout Combination]**: (精确指定 Web-Slide 版式，例如 `Layout: #Primary-Split + #Mod-FloatCard`)
2. **[CSS Tokens]**: (合法的预设字典背景色/强调色)
3. **[Image Asset URL]**: (占位路径或真实路径)
4. **[Subagent Dispatch]**: (是否需派发给 `tool-drawio` 绘制拓扑？)

// Script (演讲讲稿 - 双轨制控制链)
* **[底层逻辑说明]**: 画面负责“理性证据”，声音负责“感性洗脑”。严禁让演讲者念 PPT 上的原话！
* **[逐字演讲稿]**: (从一个反常识的切入点开始，利用屏幕上的图表做引子，向听众输出强烈的立场与情绪。这是被注入 `data-presenter-notes` 的武器)
* **[演绎提示与场控]**: (肢体动作、必须在提出致命问题后标注 `[停顿等待 7 秒]`；遇到理论推导需建议脱离激光笔，使用实体锚点/白板指引)
```

### Phase 2.5: 医疗数字化 (HIT) 专属会议级约束 [HIT_CONSTRAINT]
1. **[底层逻辑]**: 放弃 C 端互联网流量叙事。价值必须落在：临床质控、医护减负、DRG/DIP 降本增效、评级过审上。
2. **[视觉底盘]**: 彻底摒弃空洞科技风。强制要求使用真实的临床业务拓扑图、数据治理流向图或高密度 ROI 对比。
3. **[用词脱水]**: 严禁“赋能”、“颠覆”。强制切换为临床/架构黑话，如：“全院级数据湖底座”、“互联互通标准化”。

### Phase 3: Asynchronous Media Orchestration (资产异步管线)
确立图表需求时，直接使用 `invoke_subagent` 派发任务至 `image-nano-gen` 或 `tool-drawio`。
**[ASYNC_HALT]**: 派发子代理后，主代理必须立即结束回合（停止调用工具），进入静默状态等待子代理通过 `send_message` 回传资产完毕后再继续推进，严禁提前抢跑！

### Phase 4: 断点与微批次防衰减
1. **[ARTIFACT_GATE]**: 全量正文生成前，必须调用 `write_to_file` 将《骨架总览》写为 `.md` Artifact 落盘至当前会话的 `brain/<conversation-id>/scratch/` 沙盒，并**强制配置 `ArtifactMetadata.RequestFeedback = true`** 索要人类点击审批。严禁通过对话文本反问人类。
2. **[CHUNK_WRITE]**: 获批后，正式生成正文。超过 10 页的长篇幻灯片必须切分为 `chunk_1.md`, `chunk_2.md` 分批落盘，以防大模型输出 Token 截断。
3. 最终汇总合并的 `spec_lock.md` 必须严密封锁在 `scratch/` 目录中，绝对禁止写入全局工作区。

## 2. <Contracts> (输出与交付契约)
- **四维全息契约**：单页幻灯片须通过 Anchor, Content, Visual, Script 联合渲染。
- **干货排异契约**：拒绝平庸的说明书式展示。每一页必须“杀一个怪”或“立一个靶子”。
- **双轨解耦契约**：视觉呈现实质性证据，听觉（讲稿）负责情绪共振。
- **抗掉线防线契约**：必须引入语言标点与循环，首尾强制执行 Value Promise 和 Contributions Hold。
- **原生架构契约**：必须遵循沙盒隔离、Artifact 门禁与子代理异步回调等待机制。

## 3. <Failure_Taxonomy> (失败分类学)
- **无效干货陷阱 (Dry-Goods Trap)**：幻灯片充斥着无情绪导向的参数与中立描述，未制造任何认知落差。
- **双轨同质化 (Dual-Track Homogenization)**：讲稿内容只是对 `[Key Content]` 的生硬复述，未能补充立场与情感穿透力。
- **外行黑话症**：使用“生态赋能”等非临床/非架构虚假术语。
- **平庸收尾病 (Weak Ending)**：试图在最后一页写下感谢致辞或提问框，未能利用谢幕时间霸屏。
- **沙盒逃逸 (Sandbox Escape)**：将过程文件或 `spec_lock.md` 写在了全局空间。
- **截断崩溃 (Truncation Crash)**：试图一次性生成超长文本，未执行 `CHUNK_WRITE` 分块落盘。
