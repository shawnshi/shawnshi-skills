---
name: hit-solution-architect
version: 8.2.0
description: 'Comprehensive healthcare solution architect for hospital digital-transformation plans, HIS/EMR modernization, smart-hospital top-level design, Xinchuang-compliant solution design, and medical data-asset planning. Use when Codex needs to produce a formal hospital IT solution document, roadmap, architecture blueprint, or executive proposal for hospital leaders, CIOs, clinical stakeholders, or regulators.'
triggers: ["医疗解决方案", "医院数字化规划", "信创改造方案", "智慧医院顶层设计"]
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

# HIT Solution Architect (医疗数字化架构师 V8.2 Native)

把“医院数字化升级”从抽象愿景压成可执行方案。交付目标不是产品介绍，而是基于医院痛点、迁移路径、信创约束、TCO/ROI 与实施节奏的正式方案文档。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Inputs To Confirm (前置诊断) [Mode: PLANNING]
在开始写作前，先确认并复述以下边界（若信息不足，立即挂起并向用户提问）：
- **目标模式**: `brief` (1.5k-2.5k字) / `proposal` (3k-5k字) / `blueprint` (6k+字)
- **核心受众**: 院长 / CIO / 临床主任 / 卫健委 / CFO / 混合受众
- **核心矛盾**: 至少定义 1 个该医院面临的“不可能三角”或痛点集合。

### Phase 2: Logic Lake Query (调用历史知识图谱) [Mode: EXECUTION]
**强制图谱接入 (Hard Lock)**：开始设计前，主代理必须使用原生的 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `query_logic_lake`) 查询过往中标案例、信创名录与竞品防御策略。若工具不可用，降级使用本地 `winning-health-case-studies.md` 推演。

### Phase 3: Design & Delegation (设计与原生大并发组装) [Mode: EXECUTION]
1. 产出 `Solution_Skeleton.md`，强制使用原生 `write_to_file` 保存至隔离区 `<appDataDir>\brain\<conversation-id>\scratch\Solution_Skeleton.md`。
2. **并发组装 (Native Delegation)**: 对于 `proposal` / `blueprint` 模式，主代理必须调用 `invoke_subagent` 工具 (指定 `TypeName: "self"` 与各章节独立 Role)，将不同章节的写作任务分发给多个子代理。**关键硬锁**：在传给子代理的 `Prompt` 中，主代理必须明确指示：“写作完成后，使用 `send_message` 工具以 JSON Payload 将 Markdown 文本直接回传给主代理”。主代理被 Reactive Wakeup 唤醒后，再亲自通过 `write_to_file` 将收到的章节落盘至 `<appDataDir>\brain\<conversation-id>\scratch\chapter_{X}.md` 以备后续校验与集成。
3. **红队刺客逻辑审查 (Red Team Audit)**: 所有章节落盘后，主代理必须调用 `invoke_subagent` 拉起子代理 (必须指定 `TypeName: "self"` 与 `Role: "cognitive-logic-adversary"`)，对合并的全篇进行矛盾稽查（重点查杀时间线冲突、TCO账目不平）。

### Phase 4: CI/CD Auditing (跨平台强制审查与最终集成) [Mode: VERIFICATION]
执行一系列本地 Python 审计脚本，必须挂载 `$env:PYTHONIOENCODING="utf-8"` 并使用绝对物理路径：
1. 逻辑校验：对每个子章节或全篇草稿进行结构校验。
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-solution-architect\scripts\logic_checker.py" "<待校验的md文件物理绝对路径>" "proposal"`
2. 文风审计（buzzword 查杀）：查杀每个草稿中的浮夸废话。
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-solution-architect\scripts\buzzword_auditor.py" "<待校验的md文件物理绝对路径>"`
3. 最终集成与落盘：
   为了合并所有通过校验的章节，主代理必须使用 `write_to_file` 在 `<appDataDir>\brain\<conversation-id>\scratch\` 目录下创建一个 `manifest.json`，结构如 `{"chapters": ["chapter1.md", "chapter2.md"]}`（路径相对于该 json 文件）。然后执行集成命令，合并成最终文档并物理落盘：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-solution-architect\scripts\manifest_manager.py" "<appDataDir>\brain\<conversation-id>\scratch\manifest.json" "C:\Users\shich\.gemini\MEMORY\raw\solutions\{方案名称}_Final.md"`

## 2. <Contracts> (输出与交付契约)
- **Narrative Contract (叙事纪律)**: 新闻体专业散文。全面清退形容词和代词（它/该系统），用具体的业务名词作为主语锚点，确保高管跳跃阅读时无认知门槛。
- **Architecture Contract (架构纪律)**: 架构、接口、数据流、迁移路线、Roadmap 必须呈现为表格或 Mermaid 图。
- **Mermaid 制图纪律**: 系统架构图必须使用 `subgraph` 按层级划分；接口与割接流必须标明同步/异步调用状态及重试机制。禁止绘制无结构、无边界的“意大利面条图”。
- **Value Quantification (量化对齐)**: 任何“提效、降本、减负”必须附带量化口径、假设或测算路径。TCO 必须列出假设和公式 `(Old CAPEX+OPEX) - (New CAPEX+OPEX+Migration Cost)`。
- **Required Modules (强制模块)**: 任何长度的方案都不能删掉：迁移路径、ROI/TCO、信创风险缓释、实施边界与除外责任 (SOW Exclusions)。
- **Telemetry 记录**: 使用 `write_to_file` 将执行元数据保存至隔离沙盒：`<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`，防止发生写入死锁。
- **交付链接契约**: 架构方案落盘完毕后，主代理必须通过聊天向用户输出包含绝对物理路径的可点击 Markdown 链接（例如：`[医疗数字化架构方案最终版](file:///C:/Users/shich/.gemini/MEMORY/raw/solutions/...)`）。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **调度幻觉 (Tool Hallucination)**：严禁直接调用旧版的 `mcp_vector-lake-mcp_query_logic_lake` 命令，必须合法组合 `call_mcp_tool`。
- **路径死锁 (Pathing Deadlock)**：严禁在命令行里拼接 `{SKILL_DIR}` 等伪变量。执行 python 脚本时，必须使用硬编码的物理全路径 `C:\Users\shich\.gemini\config\skills\hit-solution-architect\scripts\...`。
- **受众盲写 (Blind Drafting)**：若受众（Audience）未知，必须暂停并向用户提问，严禁盲目起草。
- **说明书化 (Manual Anti-Pattern)**：把方案写成软件说明书或产品手册将被视为彻底失败。方案必须且只能面向“医院痛点与业务闭环”。
- **单维画饼 (Blueprint Only)**：只画未来蓝图，不写出现网数据迁移、双轨并行或割接方案的章节，将被立刻打回。
