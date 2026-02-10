---
name: brainstorming
description: "Must be used BEFORE implementation. Turns abstract ideas into concrete design specs through structured dialogue (First Principles, Trade-off Analysis)."
---

# Brainstorming (Design Workshop)

将模糊的想法转化为可执行的工程设计。

## Core Philosophy
*   **Ask before Act**: 在写一行代码前，先理解 WHY。
*   **Trade-off First**: 永远提供 2-3 种方案及其取舍分析。
*   **Incremental Validation**: 小步快跑，分段确认设计。

## The Process

### Phase 1: Context & Intent (理解)
1.  **Environment Check**: 自动检查当前项目上下文（文件结构、现有代码）。
2.  **Clarification Loop**:
    *   使用 `ask_user` 逐个确认需求。
    *   **Rule**: 每次只问一个核心问题，避免认知过载。
    *   **Focus**: 目标 (Goal)、约束 (Constraints)、成功标准 (Success Criteria)。

### Phase 2: Exploration (探索)
1.  **Framework Application**:
    *   加载 `references/frameworks.md`。
    *   视情况应用 **First Principles** (创新) 或 **Inversion** (鲁棒性)。
2.  **Option Generation**:
    *   提出 2-3 个技术方案。
    *   明确列出每个方案的 Pros/Cons。
    *   给出你的推荐方案及理由。

### Phase 3: Design Synthesis (设计)
1.  **Drafting**:
    *   基于 `assets/design_template.md` 起草设计文档。
    *   分段展示（架构 -> 组件 -> 数据流），每段确认后再继续。
2.  **YAGNI Check**:
    *   ruthlessly 砍掉非核心功能。

### Phase 4: Finalization (交付)
1.  **Documentation**:
    *   将最终确认的设计写入 `docs/plans/YYYY-MM-DD-<topic>-design.md`。
    *   如果目录不存在，请先创建。
2.  **Handoff**:
    *   询问用户是否准备好进入 Implementation 阶段。

## Best Practices
*   **One Step at a Time**: 不要试图在一个回合内完成整个设计。
*   **Visual Thinking**: 尝试用文字描述图表（如 Mermaid 流程图）来辅助解释。
*   **Commitment**: 设计文档是代码的合约，必须先 Commit 文档，再 Commit 代码。
