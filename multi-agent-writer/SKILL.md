---
name: multi-agent-writer
description: A consulting-grade collaborative writing workflow (Pyramid Principle). Features Storylining, Action Titles, and Visual Logic Orchestration. Version 7.0 "The Partner's Desk" Edition.
---

# Multi-Agent Writer (V7.0: The Partner's Desk Edition)

## Core Philosophy: Answer First & Action Driven
The primary objective is not just "content production," but **Strategic Clarity**. V7.0 enforces the **Pyramid Principle** and **Action Titles** to ensure that headers alone tell a complete story.

## Workflow

### Phase 0: Initiation & Ground Truth
- **定位**: 使用`ask_user`确认文章的篇幅，深度4000字|博客文章2000字|口头报告800字
- **Action**: Use `google_web_search` and `ask_user` to align on "Success Criteria."
- **Output**: `tmp/writing_progress_[Topic].md`.

### Phase 1: Strategic Synthesis (Storylining)
1. **Analyze**: Invoke `concept-analyzer`. Focus on **Root Causes** and **Structural Tensions**.
2. **Storylining (NEW)**: Generate a pure title-only sequence.
   - *Constraint*: Every header MUST be an **Action Title** (a complete conclusion, not a topic description).
   - *Audit*: If reading only the headers provides a logical decision path, proceed.
3. **Attack**: Red Team testing of the storyline logic.

### Phase 2: The "Devil's Advocate" Roundtable
- **Action**: Invoke `thinker-roundtable`.
- **Mandatory Role**: One thinker MUST act as the **Strategic Partner**, questioning the "So What?" of every claim.
- **Output**: `tmp/research_context_[Topic].md` (Source of Truth).

### Phase 3: Visual Logic & Exhibit Design (NEW)
- **Constraint**: Before drafting text, design the **Exhibits**.
- **Action**: For each chapter, define 1-2 core visual components (Mermaid, ASCII, or DALL-E prompts).
- **Requirement**: The text must support and explain the visual logic, not vice versa.

### Phase 4: Parameter Lock-in (HITL)
- **Interaction**: `ask_user` for Audience, Tone, and "Non-Consensus" Priorities.

### Phase 5: Drafting under Pyramid Constraint
- **Drafting**: Invoke `writing-assistant`.
- **"So What?" Filter**: Every paragraph must either provide evidence for an Action Title or提炼 (extract) a decision-relevant insight.
- **Style**: No fluff. Max signal-to-noise ratio.

### Phase 6: Logic & Impact Audit
- **Audit**: Use the **MBB Logic Metric**:
  - **MECE**: Are the sections mutually exclusive and collectively exhaustive?
  - **Pyramid Flow**: Do sub-points logically support the main conclusion?
  - **Impact**: Is the "So What?" explicitly clear for the target audience?

### Phase 7: Final Forging & Delivery
- **Persistence**: Save final report to `article/[Title]_[YYYY-MM-DD].md` or `research_projects/[Topic]/`.
- **Appendix**: Include the "Red-Team Residuals" (risks that remain but are acknowledged).

## Resources
- **Personas**: `references/agents.md` (See *Strategic Partner* & *Exhibit Architect*).
- **Output Schemas**: `references/templates.md`.

!!! **Protocol**: Every response from the Writer must begin with the core strategic conclusion (Answer First).
