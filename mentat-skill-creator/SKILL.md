---
name: mentat-skill-creator
version: 9.0.0
tier: action-allowed
description: 'Mentat 技能工厂与自愈中心。用于创建新技能、优化既有指令、运行技能评测及修复失败。强制采用EDD倒置开发与智能左移，通过单点突变与原子工具固化经验资产。禁止直接全盘覆写。'
triggers: ["创建技能", "优化技能", "修复指令", "自愈", "SKILL.md"]
---

<strategy-gene>
Keywords: 创建技能, 优化技能, 技能评测, amendify, SKILL.md
Summary: 将模糊工作流锻造成本地可触发、可验证、可维护的 skill。
Strategy:
1. 先澄清触发边界、用户期望、失败禁区和验收条件。
2. EDD倒置开发：在编写 SKILL.md 之前，必须先定义 3 个 JSON 测试用例。
3. 写入最小但完整的 SKILL.md，包含标准 V9 骨架 (frontmatter, trajectory, output contract等)。
4. 智能左移 (Shift Left)：禁止用大写 "ALWAYS DO" 堆砌防呆逻辑，转为 scripts/ 校验。
5. 用二元评测和静态门禁验证；重复失败只做单点突变。
AVOID: 禁止无评测的大面积重写；禁止长篇大论的路由描述；禁止全文件盲目覆写。
</strategy-gene>

# Mentat Skill Creator (V9.0 Native)

Use this skill to create, repair, or evolve local skills. The complete historical playbook is preserved in eferences/full_skill_creator_playbook.md; load it only when detailed interview scripts, evaluation viewer instructions, or legacy workflow notes are required.

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. iew_file (侦查并读取目标 SKILL.md 与参考文档)
2. invoke_subagent (可选：若失败复杂，唤醒 Critic 子代理诊断)
3. multi_replace_file_content / write_to_file (原子化执行单点突变与经验落盘)
4. un_command (可选：调用静态扫描器或测试脚本)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 侦察与意图锁定 (Recon & Intent)
1. **Recon**: Inspect existing context, target skill folder, SKILL.md, resources, scripts, examples, and prior failure evidence. **必须**检查 <appDataDir>\brain\<conversation-id>\scratch\rejected_edits.jsonl，严禁提交已被拒绝的补丁。
2. **Intent Contract**: Define trigger phrases, non-triggers, expected output, side effects, required tools, and failure taxonomy.

### Phase 2: 测试驱动开发 (EDD)
- Before drafting the SKILL.md, you MUST explicitly write out 3 JSON evaluation cases (containing input, xpected_tool_trajectory, and xpected_output_format) in your thought block or scratchpad.

### Phase 3: 诊断与单点突变 (Diagnosis & Atomic Patch)
1. **Critic Segregation**: 对于复杂的重复失败，必须通过 invoke_subagent 拉起 Failure Critic 提取一般化失败模式。
   - 子代理参数: TypeName: "self", Role: "Failure Critic Subagent".
   - 提取诊断 JSON: {"failure_mode": "...", "root_cause": "...", "suggested_patch_op": {"target_line": "...", "new_content": "..."}}.
2. **Textual Op Contract**: 在执行 multi_replace_file_content 或 write_to_file 前，必须在 thought block 中输出 JSON 补丁计划：{"reasoning": "...", "proposed_op": {"op": "multi_replace_file_content", "target": "old", "content": "new"}}。保持补丁绝对原子化。

### Phase 4: 评估与固化 (Evaluate & Lock)
1. **Contracts**: 添加或修复成功标准、Tool Trajectory 轨迹流，并强化 Failure Modes。
2. **Evaluate**: 如果存在 vals/benchmark.json，必须使用原生 un_command 附带 UTF-8 编码锁执行 scripts/skill_opt_evaluator.py 验证。
3. **Iterate**: 若测试失败，每次只打一个单点补丁并再次测试。被拒绝的编辑务必写入 ejected_edits.jsonl 避免死锁。

## 2. Skill Shape (V9 规范骨架)
Every new or substantially repaired skill should include:
- YAML frontmatter: 必须包含 
ame, ersion: 9.0.0, 	ier: draft (新建默认), 以及严格控制在 50 词内且包含负向触发指令的 description。
- <strategy-gene> block (核心公理与流向约束)
- ## Tool Trajectory (预期工具调用时序如 [IN_ORDER])
- ## 0/1/2... (通过客观化标题替换命令式的大吼大叫)
- ## <Contracts> (输出与交付契约)
- ## <Failure_Taxonomy> (失败分类学)
- ## Telemetry (埋点规范)

Prefer bundled resources over long inline instructions:
- scripts/ for deterministic actions
- eferences/ for long domain knowledge
- ssets/ for templates, images, and fixed materials
- xamples/ for validated input-output cases

## 3. <Contracts> (设计与修改契约)
- **Protected Section (Slow Update Zone)**: 严禁在日常修补中修改 <strategy-gene> 块和核心 ## Output Contract。
- **Edit Budget Lock**: 绝对禁止使用 full-file overwrite (如 write_to_file 配合 Overwrite) 来修改现有技能。所有技能修复必须优先使用 multi_replace_file_content 执行精确突变，目标锁定 2-3 个代码块，并精准对齐 TargetContent 锚点。
- **The Description Routing Algorithm**: YAML frontmatter 的 description 必须限制在 50 个词以内，开头放置触发关键词 ("提取 X..." 而不是 "这个技能可以帮你...")，并且必须包含 "禁止用于..." 的反向拦截声明。
- **Shift Intelligence Left**: 绝对禁止使用大写吼叫（例如 "ALWAYS DO X"）去硬性约束行为。复杂业务逻辑必须左移，沉淀为 scripts/ 中的决定性 Python/PS 脚本。
- **Trajectory Validation**: 必须评估技能是否通过了正确的工具轨迹流抵达结果。错误轨迹带来的“正确输出”依然是失败。
- Local references must resolve from the skill folder or repository root.
- Unsupported runtime-specific tool names must not appear in SKILL.md.
- A new skill must define both positive triggers and meaningful non-triggers.
- A repair must preserve the skill's semantic purpose unless the user explicitly asks for a redesign.

## 4. <Failure_Taxonomy> (失败分类学)
- **Ambiguous intent**: Ask one narrow clarifying question or produce an assumption block before editing.
- **Missing resource**: Create the resource, remove the reference, or point to an existing equivalent.
- **Oversized SKILL.md**: Move cookbook content into eferences/ and keep the entrypoint under the line threshold.
- **Trigger collision**: Check shared/trigger-ownership-matrix.json and assign primary/secondary roles.
- **Repeated behavior failure**: Add or modify exactly one AVOID gene, then rerun the failing test.

## Resources
- Full archived playbook: eferences/full_skill_creator_playbook.md
- Schema notes: eferences/schemas.md
- Shared template: shared/skill-structure-template.md
- Gates: scripts/repair_skills.ps1, scripts/generate_resource_manifests.ps1

## Output Contract
- For analysis tasks: return findings ordered by severity, with validation evidence. All file paths MUST be formatted as clickable Markdown links (e.g., [filename](file:///absolute/path/to/file)).
- For creation tasks: deliver a complete skill folder or a precise patch plan.
- For repair tasks: state what changed, why, and which gate or test now passes.
- Do not report success if static checks, manifest generation, or required evals were skipped without explanation.

## Telemetry
- When persistent logging is available, record skill name, task type, files changed, validation commands, failures, and next mutation candidate.
