---
name: mentat-skill-creator
version: 3.6.0
description: |
  技能工厂与自愈中心。用于创建新技能、优化既有指令、运行技能评测、修复重复性失败，并把经验固化为可验证的本地 skill 资产。
  核心原则：四层壳模型、strategy-gene、Contracts、Failure_Taxonomy、单点突变、二元评测、资源闭环。
---

<strategy-gene>
Keywords: 创建技能, 优化技能, 技能评测, amendify, SKILL.md
Summary: 将模糊工作流锻造成本地可触发、可验证、可维护的 skill。
Strategy:
1. 先澄清触发边界、用户期望、失败禁区和验收条件。
2. 写入最小但完整的 SKILL.md：frontmatter、strategy-gene、workflow、resources、failure modes、output contract。
3. 用二元评测和静态门禁验证；重复失败只做单点突变。
AVOID: 禁止无评测的大面积重写；禁止把模糊审美词写成硬规则；禁止引用不存在的本地资源。
</strategy-gene>

# Skill Creator

Use this skill to create, repair, or evolve local skills. The complete historical playbook is preserved in `references/full_skill_creator_playbook.md`; load it only when detailed interview scripts, evaluation viewer instructions, or legacy workflow notes are required.

## When to Use
- User asks to create a new skill, optimize a skill, run skill evals, repair repeated skill failures, or turn a recurring workflow into a reusable instruction asset.
- User asks for `.amendify()`, skill self-healing, trigger tuning, resource-manifest repair, or contract hardening.
- User points to an existing `SKILL.md` and asks whether it is healthy, overbroad, under-triggering, or brittle.

## Workflow
1. **Recon**: Inspect existing context, target skill folder, `SKILL.md`, resources, scripts, examples, and prior failure evidence. **CRITICAL**: You MUST check `.skill_state/rejected_edits.jsonl` if it exists, and NEVER propose a patch that was previously rejected.
2. **Intent Contract**: Define trigger phrases, non-triggers, expected output, side effects, required tools, and what failure looks like.
3. **Pattern Diagnosis (Critic Segregation)**: Classify the skill. **CRITICAL**: For repeated/complex failures, do NOT patch directly. You MUST `invoke_subagent` to spawn an independent Critic to diagnose the Minibatch of error logs and extract a generalized failure pattern.
   - **Subagent Boilerplate**: When invoking the Critic, use exactly this Prompt template:
     ```json
     {
       "TypeName": "self",
       "Role": "Failure Critic Subagent",
       "Prompt": "You are the Failure Critic Subagent. Read the recent failed transcripts or error logs. Extract a generalized failure pattern. You MUST output your final diagnosis as a JSON object: {\"failure_mode\": \"...\", \"root_cause\": \"...\", \"suggested_patch_op\": {\"target_line\": \"...\", \"new_content\": \"...\"}}. Reply to me when you are DONE."
     }
     ```
4. **Textual Op Contract (Draft or Patch)**: Before applying `multi_replace_file_content` or `write_to_file`, you MUST explicitly output a JSON patch plan in your thought block: `{"reasoning": "...", "proposed_op": {"op": "multi_replace_file_content", "target": "old", "content": "new"}}`. Keep patches strictly atomic.
5. **Contracts**: Add explicit success criteria and failure routing. Schema-bearing outputs must be structurally stable.
6. **Evaluate**: Candidate skills MUST be tested against `evals/benchmark.json` (if available) using `scripts/skill_opt_evaluator.py`. **CRITICAL**: You MUST prefix the execution with the global encoding lock (`$env:PYTHONIOENCODING="utf-8"; python scripts/skill_opt_evaluator.py`). Only if the score strictly increases is the patch merged.
7. **Iterate**: For repeated failure, apply only one targeted mutation at a time, then retest. Failed patches MUST be logged to `.skill_state/rejected_edits.jsonl`.

## Skill Shape
Every new or substantially repaired skill should include:
- YAML frontmatter with `name` and `description`
- `<strategy-gene>` block
- `## When to Use`
- `## Workflow`
- `## Resources`
- `## Failure Modes`
- `## Output Contract`
- `## Telemetry`

Prefer bundled resources over long inline instructions:
- `scripts/` for deterministic actions
- `references/` for long domain knowledge
- `assets/` for templates, images, and fixed materials
- `examples/` for validated input-output cases

## Contracts
- **Protected Section (Slow Update Zone)**: You are STRICTLY FORBIDDEN to modify the `<strategy-gene>` block or the core `## Output Contract` during routine failure repairs. These are strategic meta-skills that can only be altered during formal architectural audits.
- **Edit Budget Lock**: You are FORBIDDEN to use full-file overwrite tools when modifying existing skills. All skill repairs MUST be executed using chunk file edit tools. For any single repair session, the maximum allowed changes are 2 chunks, and each chunk must not exceed 5 lines of changes. Exceeding this budget means the proposed repair is too radical.
- Frontmatter must parse and include a precise trigger-oriented description.
- Local references must resolve from the skill folder or repository root.
- Unsupported runtime-specific tool names must not appear in `SKILL.md`.
- A new skill must define both positive triggers and meaningful non-triggers.
- A repair must preserve the skill's semantic purpose unless the user explicitly asks for a redesign.

## Failure_Taxonomy
- **Ambiguous intent**: Ask one narrow clarifying question or produce an assumption block before editing.
- **Missing resource**: Create the resource, remove the reference, or point to an existing equivalent.
- **Oversized SKILL.md**: Move cookbook content into `references/` and keep the entrypoint under the line threshold.
- **Trigger collision**: Check `shared/trigger-ownership-matrix.json` and assign primary/secondary roles.
- **Repeated behavior failure**: Add or modify exactly one `AVOID` gene, then rerun the failing test.

## Resources
- Full archived playbook: `references/full_skill_creator_playbook.md`
- Schema notes: `references/schemas.md`
- Shared template: `shared/skill-structure-template.md`
- Gates: `scripts/repair_skills.ps1`, `scripts/generate_resource_manifests.ps1`

## Output Contract
- For analysis tasks: return findings ordered by severity, with file paths and validation evidence.
- For creation tasks: deliver a complete skill folder or a precise patch plan.
- For repair tasks: state what changed, why, and which gate or test now passes.
- Do not report success if static checks, manifest generation, or required evals were skipped without explanation.

## Telemetry
- When persistent logging is available, record skill name, task type, files changed, validation commands, failures, and next mutation candidate.
