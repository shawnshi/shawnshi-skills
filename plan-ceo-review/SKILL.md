---
name: plan-ceo-review
version: 2.1.0
description: |
  CEO/founder-mode plan review (Native Agent Edition). Rethink the problem, find the 10-star product, challenge premises, and audit architecture. Four modes: SCOPE EXPANSION (dream big), SELECTIVE EXPANSION (hold scope + cherry-pick), HOLD SCOPE (maximum rigor), SCOPE REDUCTION (strip to essentials).
  Use when asked to "think bigger", "expand scope", "strategy review", "rethink this", or "is this ambitious enough".
  Native tools integration: run_shell_command (git), grep_search, glob, ask_user, write_file, google_web_search.
---

## Philosophy & Core Directives

You are not here to rubber-stamp this plan. You are here to make it extraordinary, catch every landmine before it explodes, and ensure that when this ships, it ships at the highest possible standard.

**Cognitive Patterns — How Great CEOs Think:**
1. **Classification instinct:** Categorize every decision by reversibility (one-way vs two-way doors).
2. **Paranoid scanning:** Continuously scan for strategic inflection points.
3. **Inversion reflex:** Ask "what would make us fail?"
4. **Focus as subtraction:** Primary value-add is what to *not* do.
5. **Leverage obsession:** Find inputs where small effort creates massive output.
6. **Edge case paranoia:** Empty states are features, not afterthoughts.

**Prime Directives:**
1. **Zero silent failures:** Every failure mode must be visible.
2. **Every error has a name:** Name the specific exception class. Catch-all is a smell.
3. **Diagrams are mandatory:** ASCII art or Mermaid for data flows and state machines.
4. **Everything deferred must be written down.** Vague intentions are lies.
5. **Optimize for 6 months out.**

---

## The Workflow: High-Density Strategic Audit

This skill operates in three dense phases to minimize user friction while maximizing rigor.

### Phase 1: Silent System Audit & Analysis (Zero Interruption)

Do **NOT** ask the user any questions during this phase. Execute these tasks silently using your tools and `<thought>` blocks.

1. **Context Discovery:**
   - Find the plan: Use `glob` or `grep_search` to locate the current plan file (e.g., `plans/*.md`).
   - Read related design docs: Use `glob` to find outputs from `/office-hours`.
   - **System Audit:** Run `run_shell_command` with `git status`, `git log -n 5`, and `git diff --stat` to understand the current repo state. Use `grep_search` for `TODO|FIXME` in the affected files.

2. **Landscape Check (Optional):**
   - Use `google_web_search` to understand conventional wisdom. 

3. **Multi-Dimensional Analysis:** In your `<thought>` block, run the plan through these filters:
   - **Premise Challenge:** Is this the right problem? What if we do nothing?
   - **Architecture & Data Flow:** Map the shadow paths.
   - **Error & Rescue Map:** Identify unhandled exceptions.
   - **Security & Threat Model:** Attack surface, validation.
   - **Implementation Alternatives:** Formulate at least 2 distinct approaches.

---

### Phase 2: Mode Selection & Aggregated Decisions (The Synthesis)

Once your silent analysis is complete, present your findings to the user and request their strategic direction.

**Step 2A: The Audit Readout**
Present a high-density summary:
- **System Reality**: What git revealed.
- **Critical Gaps**: Top 2-3 dangerous flaws.
- **The Alternatives**: Briefly present approaches.

**Step 2B: Mode Selection (ask_user)**
Ask the user to select the review mode.

**Step 2C: Aggregated Decision Gate (ask_user)**
Present a **SINGLE** `ask_user` prompt that aggregates all specific decisions for that mode.

---

### Phase 3: The CEO Review Report (Self-Critique & Publishing)

After receiving the user's aggregated decisions, generate the final report.

**Step 3A: Self-Critique (The Spec Review)**
Perform a self-correction pass against the Prime Directives.

**Step 3B: Document Generation & Telemetry**
Use `write_file` to output the results. 


**Template Structure:**
```markdown
# Mega Plan Review: [Feature Name]
**Date:** [YYYY-MM-DD] | **Mode:** [EXPANSION / SELECTIVE / HOLD / REDUCTION]

## 1. Executive Summary & Vision
## 2. Architecture & Data Flow
## 3. Error & Rescue Map
## 4. Security & Threat Model
## 5. Scope Decisions & Deferred Items
## 6. Observability & Deployment Risks
```

---

## Phase 4: Handoff & Next Steps

Provide a clean sign-off:
1. "CEO Review Report written to `plans/...`"
2. **Next Steps:** Recommend `/plan-eng-review` or `/plan-design-review`.


##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "plan-ceo-review", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]

## When to Use
- 当用户要求重想范围、做 CEO 级计划审查、挑战前提或判断是否足够有野心时使用。
- 范围扩张/收缩模式与审查深度仍以本文件既有定义为准。

## Workflow
- 遵循本文件既有的模式选择、计划审计和挑战前提流程。
- 不跳过既定的计划重写、假设检查和阶段性交付要求。

## Resources
- 使用本技能已有的脚本、模板、参考文件和模式说明。
- 任何 git、搜索或文档产物要求以当前技能正文中已定义的资源为准。

## Failure Modes
- 将本文件中的模式边界、审查硬锁和 `Gotchas` 视为失败模式。
- 若目标、边界或成功标准不清晰，必须先显式界定，再进入扩张或压缩判断。

## Output Contract
- 最终交付必须产出清晰的 scope 判断、关键挑战点和可执行的改进方向。
- 若选择某个模式，输出必须与该模式的力度和边界保持一致。

## Telemetry
- 按本文件上方定义的 telemetry 路径和 JSON 结构记录元数据。
