---
name: tool-slide-architect
version: 9.0.0
description: 'Strategic presentation blueprint architect (V9.0). Use when the user needs a high-rigor PPT narrative blueprint, ghost deck, speaker-script-ready outline, or decision-oriented slide architecture for executives, CTOs, hospital leaders, or consulting-style reviews. This skill features Narrative Arc structures, Minibatch Chunking for long presentations, and DESIGN.md constraints.'
triggers: ["写个PPT", "做个幻灯片大纲", "Ghost Deck", "幻灯片蓝图", "生成PPT骨架"]
---

<strategy-gene>
Keywords: 幻灯片蓝图, 叙事链条, Ghost Deck, 决策型 PPT, Design-System 约束, 叙事弧, 微批次防衰减
Summary: 生产高精度的 PPT 叙事蓝图包，将散乱信息压制为判词驱动的逻辑骨架。通过 7 问澄清、叙事弧编排与沙盒微批次装配，确保长篇大纲不衰减且符合设计约束。
Strategy:
1. 需求澄清：执行 4-7 问清单，对齐受众、目的与约束。
2. 设计资产前置读取：动笔前必须强制读取本地 `DESIGN.md`。
3. 判词与叙事弧：所有页面必须打上 `[Arc: *]` 标签，且标题必须是完整的判断句。
4. 断点审批：生成 Ghost Deck 后挂起，索要人类审批。
5. 微批次防衰减 (Minibatch Chunking)：如果大于 8-10 页，强制将内容分成多个 `chunk_*.md` 写入。
6. 事实探针：动笔前必须利用图谱获取真实数据。
AVOID: 严禁未经 Clarification 就直接写正文；严禁一次性输出超过 10 页的全量 HTML/MD；禁止使用“谢谢聆听”。
</strategy-gene>

# Tool Slide Architect (高管幻灯片蓝图引擎 V9.0 Native)

> **Vision**: Narrative is the asset. Action-title chains carry the deck. 本技能锻造无可挑剔的逻辑推演蓝图包（Blueprint Package），并严格对接 `DESIGN.md` 系统指令。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Clarification, Logic Lake & Design Probe [Mode: PLANNING]
1. **Clarification Gate (前置澄清)**：接到请求后，不要立刻查资料。先向用户抛出问题对齐：
   - 目标听众是谁？汇报场景是什么？
   - 核心的商业或技术诉求（Action Call）是什么？
   - 大致的篇幅（几页）和时长？
2. **[DESIGN LOCK]**: 强制调用 `view_file` 读取 `C:\Users\shich\.gemini\pai\DESIGN.md`，理解色彩、字体和图表限制。
3. **[HARD LOCK]**: 动笔前，必须调用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `query_logic_lake`) 查询真实指标数据。
4. **Subagent Fact-Gathering**: 若需外部数据，调用 `invoke_subagent`。**硬锁要求**：必须指示子代理通过 `send_message` 以 JSON Payload 回传数据，主代理维持 Reactive Wakeup 状态，严禁子代理乱写磁盘。

### Phase 2: Ghost Deck, Narrative Arc & Breakpoint [Mode: PLANNING]
1. 起草逻辑骨架：生成由连续判词组成的 Title Chain（标题链）。
2. **[NARRATIVE ARC]**: 每页骨架必须挂载叙事弧标签：
   - `[Arc: Hook]` (钩子)：抛反差 / 扔数据
   - `[Arc: Context]` (定调)：为什么讲这个
   - `[Arc: Core]` (主体)：核心论点结构展开
   - `[Arc: Shift]` (转折)：打破预期 / 新视角
   - `[Arc: Takeaway]` (收束)：金句或行动号召
3. **[STYLE INJECTION]**: 每页必须标注视觉节奏（如 `[Bg: Primary #005EB8]`, `[Bg: Surface #FFFFFF]`）。
4. **[BREAKPOINT]**: 输出完整的 Ghost Deck 后，**必须**挂起并索要“大纲审批”。

### Phase 3: Blueprint Chunking Generation [Mode: EXECUTION]
1. 获批后，开始撰写蓝图。物理草稿必须落盘至当前隔离区：`<appDataDir>\brain\<conversation-id>\scratch\slides\{Topic}\`
2. **[MINIBATCH ENFORCEMENT] (微批次防衰减)**：
   - 若总页数 ≤ 8 页，可直接写入单文件 `outline.md`。
   - 若总页数 > 8 页，**必须**将大纲拆分为多个物理片段，例如 `chunk_1_hook.md`, `chunk_2_core.md`, `chunk_3_takeaway.md`。每个 chunk 不超过 5 页。使用原生的 `write_to_file` 分批写入上述隔离沙盒的 `{Topic}\` 目录，杜绝并发污染。
3. **[STYLE_INSTRUCTIONS 元数据]**: 首页或每个 Chunk 的顶部必须包含受制于 `DESIGN.md` 的 Style 元数据块。
4. 结构强制：包含 `Type: Cover`, `Type: Content`, `Type: SectionBreak`, `Type: Closing`。

### Phase 4: Validation Gate (门检与沙盒组装) [Mode: VERIFICATION]
1. 强制执行防爆验证引擎（会验证 `[Arc: *]` 标签）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-slide-architect\scripts\validator.py" "<appDataDir>\brain\<conversation-id>\scratch\slides\{Topic}"`
2. 若报错，退回 Phase 3 修正。
3. 验证通过后，调用打包组装工具将分块缝合并输出最终资产（脚本会自动将其导出至 MEMORY/raw/ 等长期目录）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-slide-architect\scripts\build-deck.py" "<appDataDir>\brain\<conversation-id>\scratch\slides\{Topic}"`
4. 将遥测数据通过 `write_to_file` 保存至隔离沙盒：`<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`，防止发生写入死锁。

## 2. <Contracts> (输出与交付契约)
- **视觉约束契约**：必须 100% 符合 `DESIGN.md`，严禁发明新颜色或要求渲染卡通。
- **标题即判词契约**：Headline 必须包含动词、陈述明确结论。
- **结语行动契约**：必须有一句明确的 Action Call。严禁“谢谢聆听”。
- **交付链接契约**: 缝合完毕并成功落盘后，主代理必须通过聊天向用户输出最终物理路径的可点击 Markdown 链接（例如：`[幻灯片蓝图最终版](file:///C:/Users/shich/.gemini/MEMORY/raw/slides/...)`）。

## 3. <Failure_Taxonomy> (失败分类学)
- **沙盒宏塌陷**：严禁调用脚本时使用相对路径。
- **全量直写熔断**：在长篇大纲中，如果未使用 `chunk_*.md` 策略全量堆砌，导致后半段质量衰减或超时，直接判定任务失败。
- **黑盒越界综合征**：未征得用户对 Ghost Deck 审批前，私自写正文。
- **叙事弧缺失**：未按 Hook->...->Takeaway 结构组织。
