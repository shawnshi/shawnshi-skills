---
name: presentation-architect
description: Strategic presentation blueprint architect. Use when the user needs a high-rigor PPT narrative blueprint, ghost deck, speaker-script-ready outline, or decision-oriented slide architecture for executives, CTOs, hospital leaders, or consulting-style reviews. This skill now outputs blueprint-only assets such as `outline.md` and validated blueprint bundles, not rendered PPT files.
---

<strategy-gene>
Keywords: 幻灯片蓝图, 叙事链条, Ghost Deck, 决策型 PPT
Summary: 生产高精度的 PPT 叙事蓝图包，将散乱信息压制为判词驱动的逻辑骨架。
Strategy:
1. 判词驱动：所有页面标题必须是完整的叙事判断句，禁止使用名词标签。
2. 逻辑压测：在生成蓝图前，针对听众可能的异议进行骨架压力测试。
3. 结构对齐：强制执行 Cover -> Content -> Closing 闭环，结语必须包含 Action Call。
AVOID: 严禁跳过 outline.md 直接起草；禁止承诺生成 PPT 实体文件；禁止使用“谢谢聆听”等无效结语。
</strategy-gene>

# Presentation Architect V11.0 (Blueprint-Only Edition)

This skill produces presentation blueprints, not final slide binaries.

## Core Philosophy

- Narrative is the asset.
- Action-title chains carry the deck.
- Style must be explicit and reusable.
- The deliverable is a validated blueprint package, not a rendered PPTX.

## Blueprint Workflow

### Phase 1: Strategic Calibration
- Lock the scenario, audience, objective, timing, and style direction.
- Use concise clarification when critical inputs are missing.
- Gather only enough context to define a defensible deck spine.

### Phase 2: Ghost Deck & Style System
- Produce the title chain and deck logic.
- Define `<STYLE_INSTRUCTIONS>` as structured deck-level style truth.
- Stress-test the chain against audience objections before moving on.

### Phase 3: Slide Blueprinting
- Write the full `outline.md`.
- Every slide must use the schema in `references/outline-template.md`.
- First slide must be `Type: Cover`.
- Last slide must be `Type: Closing`.
- All middle slides must be `Type: Content`.

### Phase 4: Validation & Packaging
- Run `scripts/validator.py` against `outline.md`.
- If validation passes, run `scripts/build-deck.py <deck-dir>`.
- `build-deck.py` now emits a blueprint package JSON and summary, not a PPTX.

## Deliverable Contract

The skill only delivers:

- `outline.md`
- `blueprint_bundle.json`
- concise strategic wrap-up

No PPTX, PDF, prompt batch, or image generation is part of the default output anymore.

## Result Gate

A deck is valid only if:

1. Deck-level `<STYLE_INSTRUCTIONS>` exists and is structurally complete.
2. Cover, content, and closing slide archetypes are explicitly marked.
3. Every slide contains all mandatory blocks.
4. Headlines are narrative statements, not labels.
5. Closing slide contains a real call to action or closing thesis, not “谢谢聆听” / “Thank you”.

## Core Constraints

- Do not skip `outline.md`.
- Do not claim a deck is ready if validation fails.
- Do not promise rendered PPT output.
- Do not treat style as prose only; it must exist as structured blueprint metadata.

## Runtime Telemetry Notes

After successful completion, write metadata to:
`C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

JSON format:
`{"skill_name": "presentation-architect", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## When to Use
- Use this skill according to the frontmatter trigger description and the domain-specific rules already defined above.

## Workflow
- Follow the existing phases, scripts, and handoff rules in this skill. Do not skip validation or approval gates already defined above.

## Resources
- Use this skill directory's bundled scripts, references, assets, examples, prompts, and agents as needed. Load only the specific resource needed for the current request.

## Failure Modes
- If required inputs, local files, evidence, permissions, or validation steps are missing, stop the risky action, state the blocker, and choose the narrowest recovery path.

## Output Contract
- Final output must match the user request, preserve the skill's domain contract, and include validation evidence or an explicit reason validation could not run.

## Telemetry
- When persistent logging is available, record task type, inputs, outputs, validation status, failures, and follow-up risks in the local skill-audit path.
