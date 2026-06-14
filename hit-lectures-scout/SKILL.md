---
name: hit-lectures-scout
version: 8.2.0
description: '医疗数字化前沿科研侦察兵。Primary owner for medical AI paper scouting, clinical literature scanning, RWE filtering, and frontier academic breakthrough watch. Use for Nature/JAMA-level paper scouting and research-to-commercial-defense translation. Prefer hit-industry-radar for news/event scans and hit-weekly-brief for think-tank or whitepaper briefs.'
triggers: ["医疗AI论文", "学术扫描", "临床文献", "最新数字医疗突破"]
---

<strategy-gene>
Keywords: 医疗 AI 论文, 医学信息化, 数字化转型, 科研侦察, RWE 校验
Summary: 捕捉医疗数字化非共识信号，将学术突破深度映射至核心架构，并转化为研发杠杆与销售防御资产。
Strategy:
1. 弹性侦察：默认 7 天视窗，不足时自动回溯至 14 天。
2. 提纯脱水：强制执行 RWE (真实世界证据) 校验，过滤无临床对照的噪声。
3. 强资产映射：强制将外部学术信号翻译并挂载至专有架构词典。
4. 双轨杠杆转换：外部展示层输出宏观行业建议；内部执行层输出 1 个研发任务与 1 条销售防御话术。
AVOID: 严禁在报告中保留假 [URL] 占位符；禁止发布无临床场景适配的情报；严禁使用干瘪的学术翻译，必须加入商业战略推演。
</strategy-gene>

# HIT Intel Scout (医疗数字化战略侦察兵 V8.2 Native)

> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除"学术灌水"，将突破转化为研发部的具体任务与销售线的防御武器。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 混合调度与弹性视窗 (Map-Reduce Delegation) [Mode: PLANNING]
1. **Preprints 管线直控**: 主代理调用 `run_command` 执行原生 Python 爬网，必须挂载 UTF-8 安全锁：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-lectures-scout\assets\deepxiv_preprints_scout.py"`
   - *降级预案*：若脚本失败，必须立即通过 `invoke_subagent` 拉起 `research` 子代理手动抓取。
2. **Journals 管线并发**: 必须使用 `invoke_subagent` 工具，并发拉起 2 个子代理 (必须指定 `TypeName: "research"`)，下发 `assets/task_journals_en.md` 和 `assets/task_journals_cn.md` 的目标。并在 Prompt 中明确指示子代理：“抓取完成后，将数据整合为 JSON 对象，使用 `send_message` 工具直接发送回主代理”。子代理回调后会触发主代理的 Reactive Wakeup。
3. **弹性视窗**: 若最终抓取结果 < 5 篇，强制将时间窗口扩大至 14 天重新扫描。

### Phase 2: Arbiter 提纯与 TRL 脱水 [Mode: EXECUTION]
1. **RWE 校验**: 无临床对照实验、无真实场景适配的论文，强制标记为 L1/Noise 并丢弃。
2. **专有资产强映射 (Proprietary Asset Mapping)**: 强制将学术突破对齐至卫宁健康底层战略架构（如：将“智能体”映射至“ACE引擎”，将“知识图谱”映射至“Logic Lake”）。

### Phase 3: 范式跃迁与杠杆锻造 (Activate) [Mode: EXECUTION]
1. 为每篇核心论文总结一句话的代际跃迁公式（如 `From [旧有共识] To [前沿理念]`）。
2. **双轨杠杆转换**:
   - **内部**：输出 1 个具体预研任务（含建议技术栈）与 1 条销售防御话术。
   - **外部**：输出行业数字化转型路线规划或系统顶层架构建议。

### Phase 4: 物理层跨平台代码审计与入湖 (The Hard Gate) [Mode: VERIFICATION]
1. **写草稿**: 根据 `assets/report_template.md` 渲染草稿，强制使用原生 `write_to_file` 工具写入隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md`。
2. **执行审计**: 调用 shell 强制过检（必须使用绝对物理路径）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md" --mode scout`
   - *注：若脚本报错（如查出假链接），最多允许重试 2 次。*
3. **物理落盘**: 脚本返回 Exit Code 0 后，使用 `write_to_file` 归档至：
   `C:\Users\shich\.gemini\MEMORY\raw\DigitalHealthLecturesScout\DHLS-YYYYMMDD.md`
4. **异步图谱沉淀**: 提取高价值概念，严禁主代理自行编辑底层 Wiki 文件。必须独占使用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `prepare_ingest_batch` 或 `memory_update`) 将新概念抛入后台引擎以维护图谱治理的完整性。

## 2. <Contracts> (输出与交付契约)
- **RWE 纪律**: 最终战报必须包含 Top 10-15 文献，并且每一篇必须展示其真实世界证据（RWE）或技术成熟度（TRL）脱水结果。
- **验证链接契约**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]` 或幻觉编造的 `[URL]`。必须显式调用工具检索确认论文地址无误后，方可写入真实的 DOI 链接。
- **落地契约**: 每个高价值信号必须被硬性转换为：“预研技术栈”和“销售话术”。严禁输出干瘪的学术翻译。
- **Telemetry**: 使用 `write_to_file` 记录 `duration_sec`, `input_tokens` 至当前会话工作区 `<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`，防止发生全局死锁。
- **交付链接契约**: 最终落盘的战报必须通过聊天向用户输出包含绝对物理路径的可点击 Markdown 链接（例如：`[前沿侦察报告](file:///C:/Users/shich/.gemini/MEMORY/raw/...)`）。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **幻觉链接污染 (Fake URL)**：输出包含无法访问的占位符 URL，将被直接判定为造假死锁。
- **架构剥离症 (Unmapped Translation)**：如果完全按字面翻译论文，却没有将技术（如多模态、大模型）与我们自己的核心架构（MSL / ACE引擎 / WiNGPT）进行概念映射与融合碰撞，战报将按质量不合格拦截。
- **路径与工具幻觉 (Path/Tool Deadlock)**：严禁写入 `{SKILL_DIR}` 等导致沙盒挂掉的宏路径。所有的图谱调度必须使用合规的 `call_mcp_tool`，所有的文件落盘必须使用 `write_to_file`。
