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
3. 量化价值：所有“提效”必须附带量化口径、假设或 HEOR 公式。临床效率提升上限设定为 30-50%，超限必须提供真实案例。
4. 新闻体叙事：剥离形容词与代词，用冷冰冰的事实、具体名词和强动词驱动，确保方案任意段落支持无上下文跳读。
AVOID: 严禁将方案写成软件说明书；禁止在受众未知时起起草；架构章节禁止无表格或 Mermaid。
</strategy-gene>

# HIT Solution Architect (V9.2: Journalistic Prose Edition)

把“医院数字化升级”从抽象愿景压成可执行方案。交付目标不是产品介绍，而是基于医院痛点、迁移路径、信创约束、TCO/ROI 与实施节奏的正式方案文档。

## 0. Core Contract
1. **Start from hospital pain**: 先定义医院现状、评级压力、临床负担、预算边界，再谈能力与产品。
2. **Separate prose from structure**:
   - 背景、冲突、愿景、业务价值：新闻体专业散文。禁止宏大叙事与夹叙夹议，用冷冰冰的量化事实代替情绪修饰；全面清退代词（它/该系统），用具体的业务名词作为主语锚点，确保高管跳跃阅读时无认知门槛。
   - 架构、接口、数据流、迁移路线、Roadmap：表格或 Mermaid。
3. **Quantify every value claim**: 任何“提效、降本、提质、减负”都必须附带量化口径、假设或测算路径。
4. **Treat migration as first-class**: 方案必须覆盖旧城改造、平滑割接、双轨并行或灰度切换，不能只画未来蓝图。
5. **Keep the result gate hard**: 没有通过逻辑审计和文风审计的章节，不进入最终集成。
6. **Cross-Platform Hardening**: 所有 Python 审计脚本调用必须挂载 `$env:PYTHONIOENCODING="utf-8"` 并使用 `{SKILL_DIR}` 绝对寻址。

## 1. Modes
- `brief`: 1500-2500 字。高管汇报版，允许一次性完成。
- `proposal`: 3000-5000 字。标准概要方案，建议分 2-4 章。
- `blueprint`: 6000 字以上。完整架构蓝图，必须启用 Antigravity 原生并发引擎 (Subagent) 进行分发组装。

## 2. Inputs To Confirm
在开始写作前，先确认并复述以下边界：
- 目标模式：`brief` / `proposal` / `blueprint`
- 核心受众：院长 / CIO / 临床主任 / 卫健委 / CFO / 混合受众
- 医院背景：规模、信息化现状、主要系统、预算范围
- 主要痛点：临床减负、评级压力、医保控费、数据治理、信创改造、系统性能、迁移风险
- 主要目标：业务闭环、评级达标、平滑割接、TCO 优化、数据资产沉淀
- 核心矛盾：至少定义 1 个“不可能三角”

若受众、医院类型或目标不清楚，先问清楚，禁止直接起草正文。

## 3. References To Load
**强制图谱接入 (Hard Lock)**：在开始方案设计前，主代理**必须**调用挂载的原生工具 `mcp_vector-lake-mcp_query_logic_lake` 查询过往中标案例、信创名录与竞品防御策略。严禁依靠大模型内部幻觉盲写。
**容灾与降级策略 (Fallback)**：若 `mcp_query_logic_lake` 工具不可用，立刻挂起并询问用户是否允许调用常规 Web Search 获取最新中标案例，或降级使用本地 `winning-health-case-studies.md` 进行推演。

根据任务需要优先读取以下静态模板与标准：
- `references/医疗卫生政策要点.md`
- `references/卫宁健康典型案例.md`
- `references/卫宁健康核心产品.md`
- `references/xinchuang_ecosystem.md`
- `references/evaluation_standards.md`
- `templates/structure_standard.md`
- `templates/examples/good_titles_vs_bad_titles.md`
- `templates/examples/narrative_vs_matrix_sample.md`

## 4. Workflow

### Diagnose
1. 复述任务边界并确认模式。
2. 输出医院“不可能三角”或核心矛盾。
3. 将痛点拆成：管理层价值、CIO 价值、临床价值、CFO/监管价值。
4. 明确哪些结论需要政策、案例或 TCO 数据支撑。

### Design
1. 做 `Pain -> Capability -> Product/Architecture -> Implementation -> Metric` 映射。
2. **命名空间隔离**: 产出 `Solution_Skeleton.md`，使用 `write_to_file` 保存至物理路径 `C:/Users/shich/.gemini/MEMORY/raw/solutions/`。**严禁**占用系统底层的 `implementation_plan.md`，以免造成 Artifact 冲突。
3. 标题必须是完整判断句，不允许名词堆砌。
4. 对长文档，在进入正文撰写前，必须阻塞挂起等待用户对大纲的确认。

### Forge (Antigravity Assembly)
1. 初始化项目目录与 `MANIFEST.json`。
2. **并发组装 (Native Delegation)**: 
   - `brief` 可由主代理一次性完成。
   - `proposal` / `blueprint` 模式下，主代理**必须**调用 `invoke_subagent` 工具，将不同章节的写作指令作为 Prompt 并发下发给多个子代理。主代理挂起，待所有子代理交稿后再进入合并流。
3. 每个架构章节至少包含 1 个表格或 Mermaid 图。
4. 每个章节完成后，由主代理接管，执行防乱码逻辑校验：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/logic_checker.py" ...`
5. **红队刺客逻辑审查 (Red Team Audit)**:
   在最终合并草稿后，主代理必须拉起 `cognitive-logic-adversary` 子代理，对全篇进行矛盾稽查（重点查杀：前后章节时间线冲突、TCO账目不平、实施承诺与信创风险互斥）。一旦发现逻辑 Bug，立即打回并强制要求重写。
6. 交付前运行文风审计与最终集成：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/buzzword_auditor.py" ...`
   *(若文风审计脚本执行失败，主代理需触发内置 Self-Correction 机制，启动纯文本的去形容词、去被动语态过滤)*
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/manifest_manager.py" ...`

## 5. Required Output Structure
方案最终至少应覆盖：
- 当前现状与核心冲突
- 受众分层价值
- 目标架构或能力矩阵
- 迁移与割接路径
- 信创/合规约束
- TCO / ROI 口径或测算框架
- 风险与缓释动作
- **实施边界与除外责任 (SOW Exclusions)**：明确声明不做什么，防御无止境的定制与烂账风险。
- **控标参数矩阵 (Bid-Control Matrix)**：提炼出排他性的核心底层技术参数。

`brief` 可以压缩，但不能删掉迁移、ROI、风险、除外责任四块。

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
- ❌ 在架构章节写大段散文而没有表格/Mermaid。绘制无结构、无边界的 Mermaid“意大利面条图”。
- ✅ **Mermaid 制图规范**：系统架构图必须使用 `subgraph` 按层级（接入层、中台层、数据层、信创基础设施层）划分；接口与割接流必须使用 `sequenceDiagram` 或 `stateDiagram` 并标明同步/异步调用状态及重试机制。
- ❌ 受众未知时继续写作。
- ❌ 滥用形容词和被动语态。禁止写“全面的、先进的、智能的”，必须用具体的动词动作说明系统“接管了什么、清洗了什么、拦截了什么”。
- ❌ 标题软弱。标题不仅要是判断句，且必须包含事实锚点，可被量化证伪（如“双轨并行将停机压缩至15分钟”，而非“有效保障平滑割接”）。

## 8. Telemetry
将执行元数据保存到 `C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。
至少包含：`skill_name`, `mode`, `project_name`, `status`, `audience`, `output_path`。

## 9. Gotchas
- `IF [Audience == Unknown] THEN [Halt Drafting]`
- `IF [Claim == "Efficiency"] THEN [Require Minutes, Cost, Throughput, or Clinical Quality Metric]`
- `IF [Hospital_Type == "State-owned"] THEN [Require Xinchuang Compatibility Check]`
- `IF [Section == "Architecture"] THEN [Require Table OR Mermaid]`
- `IF [Claim == "TCO Reduction"] THEN [Require standard formula: (Old CAPEX+OPEX) - (New CAPEX+OPEX+Migration Cost)] AND [List assumptions]`

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
