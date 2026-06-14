---
name: hit-weekly-brief
version: 8.2.0
description: '医疗行业战区研报中枢 (V5.2)。Primary owner for weekly think-tank, consulting, and whitepaper briefs in healthcare or digital health. Use for McKinsey/BCG/Gartner-style report digestion and weekly strategic brief generation. Prefer hit-industry-radar for market-news/event scans and hit-lectures-scout for academic or clinical paper scouting.'
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

<strategy-gene>
Keywords: 数字健康周报, 智库研报, 二跳推理, 跨界注入
Summary: 聚合顶级智库研报并执行 Contrarian (逆向) 对抗分析，识别被主流忽略的破坏性信号。
Strategy:
1. 四维度扫描：并行调度策略、技术、政策、跨界（FinTech/军工）四条管线。
2. 织者关联：将零散预测串联为系统级规律，执行与卫宁技术的结合点推理。
3. 非共识对抗：强制寻找与主流研报相反的证据，识别“共识幻觉”。
4. 强制双链图谱与双轨落盘：对核心企业、人物或专有名词必须使用 `[[ ]]` 进行硬链接；若是长效落盘，必须遵守 Compiled Truth | Timeline 上下分割规范。
AVOID: 严禁重复 14 天内的旧报；禁止包含无 ROI 支撑的营销废话；禁止漏掉跨界启发模块；严禁越界将原始抓取数据写入核心图谱。
</strategy-gene>

# HIT Weekly Brief (行业战区周报 V8.2 Native)

> **Vision**: 消除智库研报中的“共识幻觉”与“信息茧房”。系统不仅聚合顶级咨询结论，更通过“二跳推理”与“跨界注入”识别被主流忽略的破坏性信号。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 四路并发原生沙盒扫描 (Concurrent Map-Reduce) [Mode: PLANNING]
1. **初始化调度**: 主代理必须调用原生 `invoke_subagent` 工具，并发拉起 4 个 `TypeName: research` 类型的子代理。分别下发本技能 `assets/` 目录下的四份指令包作为 Prompt：
   - 顶级智库战略 (`Task_strategy.md`)
   - 公卫与合规政策 (`Task_policy.md`)
   - 医疗技术与架构 (`Task_tech.md`)
   - **[硬锁]** 跨界技术架构注入 (`Task_serendipity.md`，从金融/物流/军工等非医疗行业寻找同构启发)。
   并在拉起子代理的 Prompt 中明确指示：“抓取完成后，必须将你的数据整合为 JSON 对象，使用 `send_message` 工具直接发送回主代理”。主代理等待子代理的 Reactive Wakeup 通知。绝对禁止主代理在此阶段直接在主线程执行广域搜索。
2. **图谱语义去重**: 回收子代理数据后，强制调用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `search_vector_lake`) 扫描过往 14 天的历史报告，剔除旧闻。

### Phase 2: 概念化用与图谱回溯 (Semantic Translation & Weaver) [Mode: EXECUTION]
1. **概念降维**: 解读非医疗行业的跨界报告时，必须将其核心概念 1:1 翻译为医疗 IT 实景（如将“边缘计算”翻译为“床旁监护终端流式分析”）。
2. **多跳关联**: 强制调用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `query_logic_lake`) 查询过往 HIS/EMR 重构记录，确认跨界逻辑在现实医疗 IT 产品（如 WiNEX）中的可落地性。

### Phase 3: Contrarian 对抗审计 [Mode: VERIFICATION]
强制要求寻找一份与本周主推共识（如 McKinsey / Gartner）**完全相反**的数据报告或专家评论，识别出当前的“共识幻觉”。

### Phase 4: 全局缝合与跨平台防爆审计 [Mode: EXECUTION]
1. 根据 `resources/template.md` 模板渲染极高压迫感的简报草稿，强制使用原生 `write_to_file` 工具写入当前会话的隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\draft_hit_brief.md`。
2. **防爆代码审查**: 强制调用跨平台红队脚本，挂载 UTF-8 数据流安全锁（必须执行绝对物理寻址）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_brief.md" --mode brief`
3. 审计拦截不过时（如查出假链接、缺失非共识观点），强制退回修正。

### Phase 5: 物理落盘与异步入湖 (Activate & Ingestion) [Mode: EXECUTION]
1. 审计通过后，使用 `write_to_file` 正式落盘：
   `C:\Users\shich\.gemini\MEMORY\raw\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`
2. **高价值实体入湖**:
   - 提取报告中的“非共识观点”等战略突变实体。严禁主代理自行修改底层 Wiki 文件。
   - 必须独占使用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `prepare_ingest_batch` 或 `memory_update`) 将突变实体安全抛入后台引擎处理，以维护图谱数据结构一致性。

## 2. <Contracts> (输出与交付契约)
- **S-I-A 框架契约**: 所有的情报推演必须严格按照 Signal(信号) -> Insight(洞察) -> Action(动作/行动杠杆) 的框架闭环输出。
- **跨界强制契约**: 终稿中必须有至少 1 个“非医疗行业”的跨界启发（Serendipity），否则视为残次品。
- **真实元数据契约**: 所有引用链接必须经过真实的浏览工具验证，严禁留下 `[URL]` 或 `[Link]` 这种 AI 假链接占位符。
- **Telemetry 落盘契约**: 任务结束时，使用 `write_to_file` 将包含 `skill_name`, `status`, `input_tokens` 等元数据的 JSON 保存至隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`，防止死锁。
- **交付链接契约**: 最终战报生成完毕后，必须向用户输出包含绝对物理路径的可点击 Markdown 链接（例如：`[本周战略简报](file:///C:/Users/shich/.gemini/MEMORY/raw/...)`）。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **幻觉与链接造假 (Hallucination Lock)**：若终稿包含类似 `[Link]` 或未能真实打开的占位符 URL，将被直接判定为造假死锁并阻断交付。必须执行真实网页连通性校验。
- **共识狂热 (Consensus Echo-Chamber)**：如果全篇报告都在顺着顶级智库的话说，而没有找到哪怕 1 处相反或对抗性的证据（Contrarian），该战报将被系统直接毙掉。
- **路径与工具崩塌 (Tool/Path Deadlock)**：严禁写入漏层级的执行路径（如 `{SKILL_DIR}` 宏），强制执行绝对物理寻址。落盘与图谱调用必须且只能使用 `write_to_file` 与合法的 `call_mcp_tool` 组合，严禁编造旧版指令名字。
- **营销水词泛滥 (PR Water-Army)**：内容中一旦检测到公关废话、主观吹捧且无 ROI 支撑的文字，视为清洗彻底失败，强制阻断交付。
