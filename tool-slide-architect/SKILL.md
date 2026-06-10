---
name: tool-slide-architect
description: Strategic presentation blueprint architect (V11.1). Use when the user needs a high-rigor PPT narrative blueprint, ghost deck, speaker-script-ready outline, or decision-oriented slide architecture for executives, CTOs, hospital leaders, or consulting-style reviews. This skill now outputs blueprint-only assets such as `outline.md` and validated blueprint bundles, not rendered PPT files.
---

<strategy-gene>
Keywords: 幻灯片蓝图, 叙事链条, Ghost Deck, 决策型 PPT
Summary: 生产高精度的 PPT 叙事蓝图包，将散乱信息压制为判词驱动的逻辑骨架。
Strategy:
1. 判词驱动：所有页面标题必须是完整的叙事判断句，禁止使用名词标签。
2. 逻辑压测：在生成蓝图前，针对听众可能的异议进行骨架压力测试。
3. 结构对齐：强制执行 Cover -> Content -> Closing 闭环，结语必须包含 Action Call。
4. 事实探针：动笔前必须利用 Vector Lake 进行图谱穿透，获取真实数据。
AVOID: 严禁跳过 outline.md 直接起草；禁止承诺生成 PPT 实体文件；禁止使用“谢谢聆听”等无效结语；禁止脱离审批流直接跑完代码。
</strategy-gene>

# Tool Slide Architect V11.1 (Blueprint x Antigravity Edition)

This skill produces presentation blueprints, not final slide binaries.

## Core Philosophy

- Narrative is the asset.
- Action-title chains carry the deck.
- Style must be explicit and reusable.
- The deliverable is a validated blueprint package, not a rendered PPTX.

## Blueprint Workflow

### Phase 1: Strategic Calibration & Logic Lake Probe
- Lock the scenario, audience, objective, timing, and style direction.
- Use concise clarification when critical inputs are missing.
- Gather only enough context to define a defensible deck spine.
- **[HARD LOCK]**: 在动笔之前，必须调用原生工具 `mcp_vector-lake-mcp_query_logic_lake` 查询过往的类似方案、真实数据与竞品背景。严禁仅凭大模型内部权重编造商业数值或技术指标。

### Phase 2: Ghost Deck, Subagents & Breakpoint
- Produce the title chain and deck logic.
- Define `<STYLE_INSTRUCTIONS>` as structured deck-level style truth.
- **单通道事实探针 (No Subagent Spawning)**: 若蓝图需要深度的市场数据支撑，主代理必须自行调用搜索引擎或 Vector Lake。**严禁调用 `invoke_subagent`**，禁止物理文件传阅以防写盘死锁。所有收集工作在主代理内存中脱水完成。
- Stress-test the chain against audience objections before moving on.
- **[BREAKPOINT]**: 输出完整的 Title Chain (标题链) 后，主代理**必须**显式挂起，向用户索要“大纲审批”。严禁在未获人类批准前私自进入 Phase 3。

### Phase 3: Slide Blueprinting
- Write the full `outline.md` to `C:/Users/shich/.gemini/MEMORY/raw/slides/{Topic}_outline.md`.
- Every slide must use the schema in `references/outline-template.md`.
- First slide must be `Type: Cover`.
- Last slide must be `Type: Closing`.
- All middle slides must be `Type: Content`.

### Phase 4: Validation & Packaging (Encoding Shield)
- 使用绝对物理寻址与 UTF-8 编码锁，执行底层验证引擎，确保无惧跨平台乱码：
- Run: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/validator.py" "C:/Users/shich/.gemini/MEMORY/raw/slides/{Topic}_outline.md"`
- If validation passes, run: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/build-deck.py" "C:/Users/shich/.gemini/MEMORY/raw/slides/"`
- `build-deck.py` now emits a blueprint package JSON and summary, not a PPTX.

## Deliverable Contract

The skill only delivers:

- `outline.md` (物理落盘至安全区)
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
- 必须严格执行脚本执行前的 `$env:PYTHONIOENCODING="utf-8"` 挂载。

## Runtime Telemetry Notes

After successful completion, write metadata to:
`C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`

JSON format:
`{"skill_name": "tool-slide-architect", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

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
