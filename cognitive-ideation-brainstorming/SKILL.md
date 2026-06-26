---
name: cognitive-ideation-brainstorming
version: 10.0.0
tier: action-allowed
description: '高压想法脱水机。在编码或创意工作前进行需求验证与架构内审。强制进行巨型需求拆解、单步收敛提问与方案对抗，并输出严谨的设计文档。禁止在想法验证期间编写代码，禁止绕过方案对决直接定论。'
triggers: ["brainstorm this", "I have an idea", "help me think through this", "office hours", "is this worth building", "怎么设计这个功能", "脑暴一下", "评估想法", "架构设计"]
---

<strategy-gene>
Keywords: office hours, 创业想法, 需求验证, 架构内审, 方案对决, 范围拆解
Summary: 在创意实施前执行逻辑压力测试，强制范围拆解，统一收敛从宏观想法到微观架构的需求脱水，形成可执行的设计契约。
Strategy:
1. 巨型探测：判定任务边界。若包含多系统则强制物理拆解子项目，拒绝一口气深挖全盘。
2. 降维提问：坚守“每次只问一个问题”原则，优先多选题，杜绝信息倾泻。
3. 压力脱水：提出 2-3 个具备差异性的权衡方案并执行单点故障内审。
4. 视觉沙盒：对于布局/原型等视觉向问题，JIT（Just-In-Time）主动提议启动视觉伴侣进行渲染。
5. 自审落盘：生成设计文档后先执行强制自我清洗（去 TODO、消歧义），通过人类审批后移交 planning 技能。
AVOID: 编写业务逻辑代码；一揽子抛出 3 个以上问题引发用户认知过载；未拆解就设计庞然大物。
</strategy-gene>

# Cognitive Ideation Brainstorming (高压想法脱水机 V10.0)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `grep_search` (扫描本地知识库获取负先验或历史设计)
2. `ask_question` (判定颗粒度，执行单步收敛式提问，请求方案抉择)
3. `write_to_file` (脱水完毕，落盘最终设计文档，并在自审后移交执行)

## 1. 核心调度与工作流 (Global State Machine)
禁止调用任何实现工具（不编写代码，不使用 shell 构建脚手架）。唯一的输出应是诊断性问题、权衡分析和 Markdown 设计文档。在跨越任何 Phase 之前，使用 `[System State: Moving to Phase X]` 显式声明。

### Phase 1: Intent, Sizing & Decomposition (意图探测与范围拆解)
1. **环境探索**: 使用 `grep_search` 快速检索 `MEMORY/` 中的历史设计文档或失败案例，作为背景同步给用户。
2. **巨型范围拆解 (Scope Decomposition)**:
   - 评估当前需求是否过大（例如：“开发一个带有聊天、文件存储、计费和数据分析的平台”）。
   - **如果需求过大**：立刻踩刹车！不要在此阶段深挖任何细节。引导用户识别出最核心的第一个子项目，然后仅针对该子项目跑后续的设计循环。
3. **判定颗粒度 (Ask: What's the scale and goal of this?)**:
   调用 `ask_question` 判定当前（子）项目的颗粒度：
   - **Startup Mode**: 全新商业点子 / 独立项目 (进入 Phase 2A)
   - **Builder Mode**: 黑客松 / 快速原型 (进入 Phase 2B)
   - **Feature Mode**: 现有系统的特定功能 / 架构 (进入 Phase 2C)

### Phase 2: Stress-Testing & Dialectical Exploration (单步脱水与方案对决) [Mode: PLANNING]
**CRITICAL RULE:** 废除“倾泻式脑暴”。必须遵守 **One question at a time (每次只问一个问题)** 原则，且尽可能提供多选题供用户选择，降低用户的认知摩擦力。

#### Phase 2.0: JIT 视觉伴侣判定 (Visual Companion)
如果在任何阶段，你发现问题属于**视觉形态、UI 布局或极其复杂的空间拓扑**（如“这个向导流选哪种界面排版更好？”），而不是纯粹的文字/逻辑选择，你必须**单独发送一条信息**主动提议：
> *"这个问题可能用图表或原型看着更直观。需要我启动浏览器视觉伴侣（Visual Companion）为您渲染对比吗？"*
- 如果用户同意，则利用工具生成视觉原型。如果拒绝，则继续纯文本推进。

#### Phase 2A: Startup Mode (YC Product Diagnostic)
以单步提问的方式探查以下 6 大强力问题：
1. **Demand Reality:** 证明有人真的需要这个的最强证据是什么？
2. **Status Quo:** 用户现在正在用什么极其糟糕的方法解决这个问题？
3. **Desperate Specificity:** 极其具体地描绘最需要这个东西的那个人。
4. **Narrowest Wedge:** 下周就能让人掏钱买单的“最小切口”是什么？
5. **Observation & Surprise:** 观察用户时，有什么事让你感到惊讶？
6. **Future-Fit:** 3年后，它如何变得不可或缺？

#### Phase 2B: Builder Mode (Design Partner)
以单步提问探查：
1. **Delight:** 最酷的版本长什么样？
2. **Audience:** 你会把这个展示给谁看？
3. **Speed:** 到达可用状态的最快路径？
4. **Differentiation:** 和现有东西相比，差异性在哪？
5. **10x Version:** 如果时间无限，你会加什么？

#### Phase 2C: Feature Mode (Architecture Stress-Testing)
1. **Dialectical Exploration**: 探查隔离性（解耦）、演进性（扩展）和容错性（异常处理）。每次只提一个核点。
2. **Alternatives Generation**: 提出 2-3 个具备实质差异的实现方案。附带权衡分析（Trade-offs），并给出**你的明确推荐**。
   - **Anti-Strawman**: 若有压倒性的行业标准，只提 1 个并解释原因，禁止编造垃圾方案凑数。
3. **Internal Adversary**: 对推荐方案执行“内审”，无情寻找单点故障（SPOF）。

### Phase 3: Specification, Self-Review & Approval (定稿、自审与审批)
1. 使用 `write_to_file` 将验证后的设计写入工作区或对应项目 `plans/design-<topic>.md`。
2. **Spec Self-Review (强制自审清洗)**: 在文档落盘后，不要马上请用户审核，你必须先自己审一遍：
   - *Placeholder scan*: 全局扫描并清除任何 "TBD", "TODO" 或模糊的要求。
   - *Internal consistency*: 检查各个章节是否有矛盾？架构图是否匹配了功能描述？
   - *Ambiguity check*: 是否存在可以被理解为两种不同意思的需求？如果有，立刻在线修改明确。
3. **User Review Gate**: 清洗完毕后，明确告知用户文档已生成至路径，要求人类进行最终审阅（*“文档已就绪，请审核是否可以进入开发计划拆解阶段”*）。

### Phase 4: Downstream Handoff (交接至开发流水线)
一旦人类审核通过，**禁止将系统悬空结束**。必须执行明确的交接：
提示用户或主动准备调用 `writing-plans` (计划编写) 或对应的编码切分技能，将高维 Design Spec 降维拆解为可被一线 Agent 领取的 Task List。该技能的绝对终态是进入“实现计划”阶段。

**Template Structure (`plans/design-<topic>.md`):**
```markdown
# Design: [Title]
**Date:** [YYYY-MM-DD] | **Mode:** [Startup/Builder/Feature]

## 1. Problem Statement & Context
[Synthesized clearly]

## 2. Core Insights & Scope Boundaries
[Answers to forcing questions or structural trade-offs. Explicit boundaries on what we are NOT building.]

## 3. Recommended Approach & Architecture
[The approved architecture or product wedge. Clear boundaries, decoupled modules.]

## 4. Visual Flow & Data Pipeline
[Mermaid diagram if applicable]

## 5. Next Steps
[Transition to writing-plans for concrete implementation tasks]
```

## 2. <Contracts> (输出与交付契约)
- **文档产出**: 最终态必须使用 `write_to_file` 产生一份物理文档。
- **架构表达**: 架构设计必须包含 ASCII 或 Mermaid 图表，禁止长篇累牍的纯文本。
- **Telemetry 记录**: 落盘设计文档后，将元数据保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 3. <Failure_Taxonomy> (失败分类学)
- **逾越边界 (Write Code Violation)**：在脑暴阶段直接编写业务逻辑代码。
- **倾泻式提问 (Cognitive Overload)**：一次性抛出 3 个以上问题要求用户作答。
- **流程跳跃**：未做范围切分直接设计超大系统；或跳过“方案对决”直接给出一个结论。
- **文档缺陷 (Self-Review Failure)**：交付给用户的最终设计文档中存在未清理的 `TODO` 或自相矛盾的逻辑。
