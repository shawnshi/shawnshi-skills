---
name: multi-agent-writer
description: A high-density collaborative writing workflow using specialized agents (concept-analyzer, thinker-roundtable, writing-assistant). Features V6.2 "Deep Defense" architecture with mandatory Red-Teaming, Outline Confirmation, and Logic Auditing. Use for strategic reports, white papers, and battle-hardened articles.
---

# Multi-Agent Writer (V6.2: Deep Defense & Progressive Disclosure)

## Overview
A "Cognitive Assembly Line" for strategic content. V6.2 moves detailed prompts to `references/` for token efficiency and introduces mandatory **Cognitive Friction** (Devil's Advocate) and **Deep Logic Auditing**.

## Workflow

### Phase 0: Initiation & Tracker
- **Action**: Use `google_web_search` and `ask_user` for "Ground Truth."
- **Persistence**: Create `tmp/writing_progress_[Topic].md` to track state.

### Phase 1: Structural Analysis & Red Teaming
1. **Analyze**: Invoke `concept-analyzer` (See `references/agents.md`). Focus on **Second-Order Effects**.
2. **Attack**: Execute "Red Teaming". Search for failures and contradictions. 
   - *Constraint*: Use `apify-ultimate-scraper` or `markdown-converter` for deep sampling of critical sources.
   - *Output*: `tmp/red_team_report_[Topic].md` (See `references/templates.md`).

### Phase 2: The "Devil's Advocate" Debate
- **Action**: Invoke `thinker-roundtable`. 
- **Mandatory Role**: One thinker MUST be the **Devil's Advocate**, weaponizing the Red Team Report.
- **Output**: Unresolved tensions and defensive lines.

### Phase 2.5: Semantic Persistence
- **Action**: Consolidate insights into `tmp/research_context_[Topic].md` (See `references/templates.md`). This is the **Source of Truth**.

### Phase 3: Parameter Lock-in (HITL)
- **Interaction**: `ask_user` for Audience, Tone, and prioritized tensions.

### Phase 4: Outline & Confirmation
- **4.1 Design**: Read `tmp/research_context_[Topic].md`. Generate outline (See `references/templates.md`).
- **4.2 Confirmation**: **STOP**. Present outline to user. Wait for approval.

### Phase 5: Synthesis & Logic Audit
- **5.1 Drafting**: Invoke `writing-assistant` (See `references/agents.md`).
- **5.2 Auditing**: Use the **3D Logic Metric** (Fidelity, Defensibility, Entropy) to self-correct. See `references/agents.md` for definitions.

### Phase 6: Final Delivery
- **Persistence**: Save final article to `article/[Title]_[YYYY-MM-DD].md`.
- **Constraint**: Add a "Conflict Appendix" documenting discarded alternatives.

## Resources
- **Personas**: `references/agents.md`
- **Output Schemas**: `references/templates.md`

!!! **Protocol**: If you need more depth for an agent's role, read `references/agents.md` before execution.
