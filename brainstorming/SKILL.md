---
name: brainstorming
version: 2.0.0
description: |
  顶尖创意与架构设计专家 (Native Agent Edition)。在任何开发特性、构建组件、修改行为或创意写作前，必须强制调用。该技能通过结构化对话将模糊意图转化为具体的设计规范与验证方案，严禁未经头脑风暴直接执行复杂任务。
  Native tools integration: ask_user, write_file, glob, read_file.
---

# Brainstorming Ideas Into Designs (Native Edition)

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then use the "Brain Dump + Gap Fill" pattern to refine the idea. Once you understand what you're building, present the design and get user approval.

<HARD-GATE>
Do NOT invoke any implementation tools, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. Your output is a design document in the `plans/` directory.
</HARD-GATE>

## Anti-Pattern: "This Is Too Simple To Need A Design"
Every project goes through this process. A todo list, a single-function utility, a config change — all of them. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be short, but you MUST present it and get approval.

---

## Phase 1: Context Gathering

**Explore project context (Silent):** 
Use `glob` and `read_file` to check the current project state (files, existing `plans/`, `docs/`, `README.md`, or architecture documents).
- Before asking detailed questions, assess the scope. If the request describes multiple independent subsystems, flag this immediately and help the user decompose the project.

---

## Phase 2: Questioning Protocol (Brain Dump + Gap Fill)

**CRITICAL RULE:** Do NOT ask questions one at a time mechanically.

1. **Initial Brain Dump:** First, invite the user to dump their entire idea: 
   > "Tell me everything about what you want to build, the core purpose, and the constraints."
2. **Internal Mapping (Silent):** Use a `<thought>` block to map their response against the following core dimensions:
   - **Purpose & Constraints:** What is the exact goal? What are the limitations (time, tech stack, dependencies)?
   - **Success Criteria:** How do we know it works?
   - **Data Flow & Boundaries:** What does it consume? What does it produce?
3. **Targeted Follow-up:** ONLY ask about the gaps. You may merge 2-3 closely related questions into a single `ask_user` prompt. Use multiple-choice options where possible for easier interaction.

---

## Phase 3: Exploring Approaches & Architecture

**Propose 2-3 approaches:**
- Present 2-3 different architectural or implementation approaches with trade-offs.
- Present options conversationally via `ask_user` with your recommendation and reasoning. Lead with your recommended option.
- Ensure the options are substantively different (Anti-Strawman rule: don't invent bad options just to have 3).

**Design for isolation and clarity:**
- Break the system into smaller units that each have one clear purpose.
- For each unit, be able to answer: what does it do, how do you use it, and what does it depend on?

---

## Phase 4: Presenting the Design

Once the approach is approved, synthesize the design.

**Visual Flow / Architecture (Markdown Native):**
If the chosen approach involves UI flows, architecture, or state machines, embed a **Mermaid diagram** directly in your output.
- Use `graph TD` for user flows or component dependencies.
- Use `sequenceDiagram` for API/backend interactions.

**Self-Critique (Silent):**
Before writing the spec, use a `<thought>` block to review the design for completeness, consistency, clarity, and edge cases. Ensure it aligns with existing patterns found in Phase 1.

---

## Phase 5: Documentation & Handoff

**Documentation:**
- Once the user gives final approval, write the validated design (spec) using `write_file` to `plans/design-<topic>.md`.
- Use a clear, standardized Markdown structure.

**Template Structure:**
```markdown
# Design Spec: [Title]
**Date:** [YYYY-MM-DD] 

## Purpose & Success Criteria
[Core goals and how to measure success]

## Architecture & Data Flow
[Insert Mermaid diagram here]

## Components & Interfaces
[Breakdown of units, inputs, and outputs]

## Edge Cases & Error Handling
[Specific shadow paths and failure modes]

## Implementation Phases
[Step-by-step rollout plan]
```

**Handoff:**
- Tell the user: "Design spec written to `plans/design-<topic>.md`. Please review it."
- Advise the user that the next step is to run `/plan-eng-review` or `/plan-ceo-review` (if strategic) before starting execution.

## 6. 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]