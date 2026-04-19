---
name: personal-brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
---

# Personal Brainstorming (V5.0: Logic Stress-Testing Edition)

“不经审计的设计，是技术债的温床。在这里，我们通过深挖意图与压力测试方案，构建高鲁棒性的系统底座。”

---

## When to Use
- 当任务涉及新功能、组件、行为修改或方案设计时使用。
- 目标是先固化设计边界，再进入实现，而不是在模糊需求上直接编码。

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：必须严格按照 Phase 0 至 Phase 6 的顺序执行。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。

## Workflow

### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启头脑风暴前，优先使用当前运行时可用的本地记忆检索或工作区搜索能力，检索 `MEMORY/` 中相关的历史设计文档、类似功能的逻辑实现或历史遗留的架构约束点。若无记忆检索工具，则退化为仅扫描当前工作区与现有文档。
2.  **情报汇总**：将检索到的核心情报（如：已有的类似组件、曾经失败的设计、特定的库版本限制）同步给用户，作为讨论的【负先验】背景。

### Phase 1: Context & Intent (意图对齐) [Mode: PLANNING]
1.  **环境探索**：通过目录浏览、全文搜索等当前运行时可用的工作区工具，快速扫描相关文件状态、近期提交及现有文档。
2.  **视觉伴侣预告**：如果议题涉及 UI/UX，单独发送一条消息询问是否开启 Visual Companion。
3.  **核心提问**：必要时直接向用户询问议题的核心目的、边界约束及成功指标。一次只问一个问题。

### Phase 2: Dialectical Exploration (辩证探索) [Mode: PLANNING]
1.  **单点深入**：围绕核心意图，一次提出一个问题（推荐多选）。重点探查：
    - **隔离性**：组件间如何解耦？
    - **演进性**：如果未来需求变动，现有设计是否容易扩展？
    - **容错性**：异常情况（如网络超时、数据损坏）如何处理？
2.  **分解大型项目**：若议题过大，强制在此阶段执行“分解（Decomposition）”，拆分为独立的子项目，按顺序进行。

### Phase 3: Stress-Tested Approaches (压力测试方案) [Mode: PLANNING]
1.  **方案对决**：提出 2-3 个具备差异性的备选方案，并附带权衡分析（Trade-offs）。
2.  **逻辑对抗 (Internal Adversary)**：对推荐方案执行“内审”。模仿 `personal-logic-adversary` 的逻辑，主动寻找方案中的单点故障（SPOF）或假设漏洞。
3.  **呈现**：推荐一个最能达成目标的方案，并给出详尽的推荐理由。

### Phase 4: Structural Design (架构铸造) [Mode: PLANNING]
1.  **分章节呈现**：详细描述架构、组件、数据流、测试策略等。
2.  **结构化输出**：强制使用 ASCII 图表或 Mermaid 展示架构，确保“所见即结构”。
3.  **用户签收**：每完成一个章节的描述，询问用户是否认同，未经认可严禁跨入 EXECUTION 阶段。

### Phase 5: Specification & Review (定稿与审计) [Mode: EXECUTION]
1.  **物理落盘**：将经过验证的设计写入 `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` 或同级规划文档，并按当前运行时支持的方式保存。
2.  **自愈审计 (Self-Review)**：检查是否有占位符（TODO）、逻辑矛盾、边界模糊等。发现问题直接在文档中修复。
3.  **用户终审**：提示用户路径，请求对最终 Spec 文档的签字确认。

### Phase 6: Transition (动员准备) [Mode: EXECUTION]
1.  **执行衔接**：基于已签字的 Spec 生成详细的实施计划；若 `writing-plans` 或同类规划技能存在，可作为可选加速器，而不是硬依赖。
2.  ** telemetry (Mandatory)**：记录元数据至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。

---

## Resources
- `MEMORY/`
- 当前工作区代码与文档
- `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- `personal-logic-adversary`（可选逻辑对抗器）

## Failure Modes
- ❌ **严禁跳步**：即使是再小的功能（TODO List、Config 修改），也必须走完流程。
- ❌ **严禁实施**：在此技能期间严禁编写任何业务代码或创建项目脚手架。
- ✅ **一次一问**：不通过长篇累牍的信息轰炸干扰用户决策。
- ✅ **结构判词**：设计文档中严禁空泛的形容词（“高效、灵活”），必须是具体的物理约束。

---

## Output Contract
- 至少产出一份可落盘的设计说明或同级规划文档。
- 设计必须包含目标、边界、主要方案、关键约束与后续实施计划。
- 未形成具体实现计划前，不应直接进入编码。

## Telemetry
- 记录元数据至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。

## 3. 历史失效先验 (NLAH Gotchas)
- `IF [Phase == 6] THEN [Halt if Action == "Write Code"] AND [Require a concrete implementation plan before coding]`
- `IF [Task contains ("和" OR "且" OR "以及")] THEN [Require execute("Phase 2 Decomposition")]`
- `IF [Topic == "Architecture Design"] THEN [Halt if Format == "Plain Text"] AND [Require Format IN ("ASCII", "Mermaid")]`

---
*Updated to V5.0 | System State: Locked*
