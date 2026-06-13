---
name: tool-slide-architect
version: 8.1.0
description: 'Strategic presentation blueprint architect (V11.1). Use when the user needs a high-rigor PPT narrative blueprint, ghost deck, speaker-script-ready outline, or decision-oriented slide architecture for executives, CTOs, hospital leaders, or consulting-style reviews. This skill now outputs blueprint-only assets such as `outline.md` and validated blueprint bundles, not rendered PPT files.'
triggers: ["写个PPT", "做个幻灯片大纲", "Ghost Deck", "幻灯片蓝图", "生成PPT骨架"]
---

<strategy-gene>
Keywords: 幻灯片蓝图, 叙事链条, Ghost Deck, 决策型 PPT
Summary: 生产高精度的 PPT 叙事蓝图包，将散乱信息压制为判词驱动的逻辑骨架。不输出臃肿文件，只交付结构灵魂。
Strategy:
1. 判词驱动：所有页面标题必须是完整的叙事判断句，禁止使用名词标签。
2. 逻辑压测：在生成蓝图前，针对听众可能的异议进行骨架压力测试。
3. 断点审批：大模型必须在生成完 Ghost Deck（标题链）后挂起，索要人类审批，严禁私自继续。
4. 事实探针：动笔前必须利用图谱获取真实数据。
AVOID: 严禁跳过 outline.md 直接起草；禁止承诺生成 PPT 实体文件；禁止使用“谢谢聆听”等无效结语；禁止脱离审批流跑完脚本。
</strategy-gene>

# Tool Slide Architect (高管幻灯片蓝图引擎 V8.1 Native)

> **Vision**: Narrative is the asset. Action-title chains carry the deck. 本技能不生产花里胡哨的排版，只锻造无可挑剔的逻辑推演蓝图包（Blueprint Package）。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Strategic Calibration & Logic Lake Probe [Mode: PLANNING]
1. 锁定汇报场景、目标听众、战略意图与时间体量。
2. **[HARD LOCK]**: 在动笔之前，主代理必须调用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `query_logic_lake`) 查询图谱中的类似方案与真实数据指标。严禁仅凭大模型权重编造商业数值或技术指标。
3. **Subagent Fact-Gathering**: 若蓝图需要深度的外部市场数据支撑，主代理必须调用 `invoke_subagent` 拉起子代理 (必须指定 `TypeName: "research"`) 执行外围抓取。主代理挂起以保持上下文极度纯净。

### Phase 2: Ghost Deck & Breakpoint (幻影骨架与审批门) [Mode: PLANNING]
1. 起草逻辑骨架：明确 `<STYLE_INSTRUCTIONS>`，生成由连续判词组成的 Title Chain（标题链）。
2. 在脑海内针对听众可能的刁难，对骨架执行压力测试 (Stress-test)。
3. **[BREAKPOINT]**: 输出完整的 Title Chain 后，主代理**必须**显式挂起，向用户索要“大纲审批”。未获人类明确批准，严禁进入正文蓝图细化。

### Phase 3: Blueprint Generation (蓝图实体化) [Mode: EXECUTION]
1. 获批后，严格参照模板撰写出完整的 `outline.md`。
2. 物理落盘目标路径：`C:\Users\shich\.gemini\MEMORY\raw\slides\{Topic}_outline.md`。
3. 结构强制对齐：首页必须是 `Type: Cover`，中间页面必须是 `Type: Content`，尾页必须是 `Type: Closing` 并包含明确的 Action Call（下一步行动）。

### Phase 4: Validation Gate (底层防爆验证与落盘) [Mode: VERIFICATION]
1. 强制挂载中文字符集与绝对物理地址执行验证引擎：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-slide-architect\scripts\validator.py" "C:\Users\shich\.gemini\MEMORY\raw\slides\{Topic}_outline.md"`
2. 若 `validator.py` 报错退出，主代理必须阅读报错并退回 Phase 3 修正。
3. 验证通过后，调用打包工具进行输出（输出将不再是 PPTX，而是 JSON 和 summary）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-slide-architect\scripts\build-deck.py" "C:\Users\shich\.gemini\MEMORY\raw\slides\"`
4. 将执行元数据通过 `write_to_file` 保存至遥测目录：
   `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 2. <Contracts> (输出与交付契约)
- **交付物契约 (Deliverable Contract)**：本技能仅交付验证合格的 `outline.md`、`blueprint_bundle.json` 与战略级简报。禁止越权承诺用户“我现在给您生成一份 PPT/PDF 文件”。
- **标题即判词契约 (Action-Title Rule)**：所有页面的 Headline（主标题）必须是一个包含动词、陈述明确结论的完整句子。禁止使用如“痛点分析”、“技术架构”等空洞的名词标签。
- **结语行动契约 (Closing Thesis)**：尾页必须是一句具有威慑力或决策导向的陈述，以及明确的 Action Call。严禁出现“谢谢聆听 / Thank you”这种毫无战略价值的废料。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **沙盒宏塌陷 (Macro Deadlock)**：严禁在调取防爆验证脚本时使用 `{SKILL_DIR}` 或 `{WORKSPACE}` 等可能导致找不到文件的沙盒宏；必须且只能使用绝对物理路径与 `$env:PYTHONIOENCODING="utf-8"` 强制上锁。
- **工具与指令幻觉 (Tool Forgery)**：图谱查询必须使用合规的 `call_mcp_tool`。物理文件写入必须使用 `write_to_file`。
- **黑盒越界综合征 (Bypass Breakpoint)**：如果在未征得用户对 Ghost Deck（幻影骨架）明确批准的情况下，大模型就私自进入了 Phase 3 生成了冗长的大纲正文，系统将直接判处越界执行，阻断抛出错误。
- **形式主义污染 (Prose-only Style)**：禁止把幻灯片的美学风格（Style）仅仅当成文字描述，它必须作为结构化的 `<STYLE_INSTRUCTIONS>` 元数据真实地存留在蓝图中。
