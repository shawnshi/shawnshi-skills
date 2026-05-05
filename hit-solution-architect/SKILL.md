---
name: hit-solution-architect
description: Comprehensive healthcare solution architect for hospital digital-transformation plans, HIS/EMR modernization, smart-hospital top-level design, Xinchuang-compliant solution design, and medical data-asset planning. Use when Codex needs to produce a formal hospital IT solution document, roadmap, architecture blueprint, or executive proposal for hospital leaders, CIOs, clinical stakeholders, or regulators.
---

<strategy-gene>
Keywords: 医院数字化转型, 方案设计, 信创改造, TCO 测算, 平滑割接
Summary: 将抽象愿景压制为基于痛点映射与迁移路径的可执行方案文档。
Strategy:
1. 痛点驱动：先定义评级压力与预算边界，再进行能力对齐。
2. 迁移第一：方案必须包含旧城改造与灰度切换路径，禁止只画蓝图。
3. 量化价值：所有“提效”必须附带量化口径、假设或 HEOR 公式。
AVOID: 严禁将方案写成软件说明书；禁止在受众未知时起草；架构章节禁止无表格或 Mermaid。
</strategy-gene>

# HIT Solution Architect (V9.0)

把“医院数字化升级”从抽象愿景压成可执行方案。交付目标不是产品介绍，而是基于医院痛点、迁移路径、信创约束、TCO/ROI 与实施节奏的正式方案文档。

## 0. Core Contract
1. **Start from hospital pain**: 先定义医院现状、评级压力、临床负担、预算边界，再谈能力与产品。
2. **Separate prose from structure**:
   - 背景、冲突、愿景、业务价值：专业散文。
   - 架构、接口、数据流、迁移路线、Roadmap：表格或 Mermaid。
3. **Quantify every value claim**: 任何“提效、降本、提质、减负”都必须附带量化口径、假设或测算路径。
4. **Treat migration as first-class**: 方案必须覆盖旧城改造、平滑割接、双轨并行或灰度切换，不能只画未来蓝图。
5. **Keep the result gate hard**: 没有通过逻辑审计和文风审计的章节，不进入最终集成。

## 1. Modes
- `brief`: 1500-2500 字。高管汇报版，允许一次性完成。
- `proposal`: 3000-5000 字。标准概要方案，建议分 2-4 章。
- `blueprint`: 6000 字以上。完整架构蓝图，必须分章节推进。

## 2. Inputs To Confirm
在开始写作前，先确认并复述以下边界：
- 目标模式：`brief` / `proposal` / `blueprint`
- 核心受众：院长 / CIO / 临床主任 / 卫健委 / 混合受众
- 医院背景：规模、信息化现状、主要系统、预算范围
- 主要痛点：临床减负、评级压力、医保控费、数据治理、信创改造、系统性能、迁移风险
- 主要目标：业务闭环、评级达标、平滑割接、TCO 优化、数据资产沉淀
- 核心矛盾：至少定义 1 个“不可能三角”

若受众、医院类型或目标不清楚，先问清楚，禁止直接起草。

## 3. References To Load
根据任务需要优先读取：
- `references/医疗卫生政策要点.md`
- `references/卫宁健康典型案例.md`
- `references/卫宁健康核心产品.md`
- `references/xinchuang_ecosystem.md`
- `references/evaluation_standards.md`
- `templates/structure_standard.md`
- `templates/examples/good_titles_vs_bad_titles.md`
- `templates/examples/narrative_vs_matrix_sample.md`

如果 `vector-lake` 可用，使用当前 CLI 实际支持的参数执行检索；不要假设历史参数仍然有效。若不可用，显式列出“待核事实清单”并继续。

## 4. Workflow

### Diagnose
1. 复述任务边界并确认模式。
2. 输出医院“不可能三角”或核心矛盾。
3. 将痛点拆成：管理层价值、CIO 价值、临床价值。
4. 明确哪些结论需要政策、案例或 TCO 数据支撑。

### Design
1. 做 `Pain -> Capability -> Product/Architecture -> Implementation -> Metric` 映射。
2. 产出 `implementation_plan.md` 或同等大纲文件。
3. 标题必须是完整判断句，不允许名词堆砌。
4. 对长文档，在进入正文前等待用户确认大纲。

### Forge
1. 初始化项目目录、`plan.md` 和 `MANIFEST.json`。
2. `brief` 可一次性完成；`proposal` 建议 1-2 章一批；`blueprint` 每次只写 1-2 个相关章节。
3. 每个架构章节至少包含 1 个表格或 Mermaid 图。
4. 每个章节完成后运行 `scripts/logic_checker.py`。
5. 交付前运行 `scripts/buzzword_auditor.py`，再用 `scripts/manifest_manager.py` 合并终稿。

## 5. Required Output Structure
方案最终至少应覆盖：
- 当前现状与核心冲突
- 受众分层价值
- 目标架构或能力矩阵
- 迁移与割接路径
- 信创/合规约束
- TCO / ROI 口径或测算框架
- 风险与缓释动作

`brief` 可以压缩，但不能删掉迁移、ROI、风险三块。

## 6. Manifest Contract
`MANIFEST.json` 至少包含：
- `title`
- `mode`
- `audience`
- `chapters`
- `required_sections`
- `final_risks`

合并前确认 manifest 中的章节路径真实存在，且顺序正确。

## 7. Anti-Patterns
- ❌ 把方案写成软件说明书或产品手册。
- ❌ 只讲未来蓝图，不讲现网迁移和割接。
- ❌ 只说 ROI，不给成本口径、假设或数据指纹。
- ❌ 在架构章节写大段散文而没有表格/Mermaid。
- ❌ 受众未知时继续写作。

## 8. Telemetry
将执行元数据保存到 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
至少包含：`skill_name`, `mode`, `project_name`, `status`, `audience`, `output_path`。

## 9. Gotchas
- `IF [Audience == Unknown] THEN [Halt Drafting]`
- `IF [Claim == "Efficiency"] THEN [Require Minutes, Cost, Throughput, or Clinical Quality Metric]`
- `IF [Hospital_Type == "State-owned"] THEN [Require Xinchuang Compatibility Check]`
- `IF [Section == "Architecture"] THEN [Require Table OR Mermaid]`
- `IF [Claim == "TCO Reduction"] THEN [Require Cost Baseline, Assumption, or HEOR Formula]`

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
