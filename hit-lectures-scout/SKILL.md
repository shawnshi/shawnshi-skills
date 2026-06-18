---
name: hit-lectures-scout
version: 9.0.0
tier: action-allowed
description: '医疗数字化前沿科研侦察兵。并发抓取医疗 AI 论文与前沿学术突破，将学术信号映射为研发杠杆与销售防御资产。禁止在报告中保留无效的占位符链接，禁止生成无商业战略推演的干瘪学术翻译。'
triggers: ["医疗AI论文", "学术扫描", "临床文献", "最新数字医疗突破"]
---

<strategy-gene>
Keywords: 医疗 AI 论文, 医学信息化, 数字化转型, 科研侦察, RWE 校验
Summary: 捕捉医疗数字化非共识信号，将学术突破深度映射至核心架构，并转化为研发杠杆与防御资产。
Strategy:
1. 弹性侦察：默认 7 天视窗，不足时自动回溯至 14 天。
2. 提纯脱水：执行 RWE (真实世界证据) 校验，过滤无临床对照的噪声。
3. 强资产映射：将外部学术信号翻译并挂载至专有架构词典。
4. 双轨转换：外部输出宏观建议；内部输出研发任务与销售话术。
AVOID: 保留假 [URL] 占位符；发布无临床场景适配的情报；缺乏商业推演。
</strategy-gene>

# HIT Intel Scout (医疗数字化战略侦察兵 V8.2 Native)

> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除"学术灌水"，将突破转化为研发部的具体任务与销售线的防御武器。

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (执行预印本爬网)
2. `invoke_subagent` (并发拉起子代理抓取期刊)
3. `write_to_file` (写入草稿沙盒)
4. `run_command` (执行代码级跨平台审计)
5. `write_to_file` (战报物理落盘)
6. `call_mcp_tool` (高价值概念入湖)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 混合调度与弹性视窗 (Map-Reduce Delegation)
1. **Preprints 管线直控**: 主代理调用 `run_command` 执行爬网（挂载 UTF-8）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-lectures-scout\assets\deepxiv_preprints_scout.py"`
   - 若脚本失败，降级通过 `invoke_subagent` 拉起 `research` 子代理手动抓取。
2. **Journals 管线并发**: 使用 `invoke_subagent` 并发拉起 2 个 `research` 子代理，下发中英文期刊抓取目标。
   - 指示子代理以 JSON 格式通过 `send_message` 回传。
   - 等待子代理回调唤醒。
3. **弹性视窗**: 若最终抓取结果 < 5 篇，需将时间窗口扩大至 14 天重新扫描。

### Phase 2: Arbiter 提纯与 TRL 脱水
1. **RWE 校验**: 无临床对照实验、无真实场景适配的论文，标记为 L1/Noise 并丢弃。
2. **专有资产映射**: 将学术突破对齐至卫宁底层战略架构（如将“智能体”映射至“ACE引擎”，“知识图谱”映射至“Logic Lake”）。

### Phase 3: 范式跃迁与杠杆锻造 (Activate)
1. 为每篇核心论文总结一句话代际跃迁公式（如 `From [旧有共识] To [前沿理念]`）。
2. **双轨杠杆转换**:
   - **内部**：输出 1 个具体预研任务（含建议技术栈）与 1 条销售防御话术。
   - **外部**：输出行业数字化转型路线规划或系统顶层架构建议。

### Phase 4: 跨平台代码审计与物理入湖 (The Hard Gate)
1. 根据模板渲染草稿，使用 `write_to_file` 写入隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md`。
2. **执行过检**: 调用 shell 执行审计：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md" --mode scout
   ```
   若报错拦截（如查出假链接），最多重试 2 次。
3. **物理落盘**: 脚本返回 Exit Code 0 后，归档至：
   `C:\Users\shich\.gemini\MEMORY\raw\DigitalHealthLecturesScout\DHLS-YYYYMMDD.md`
4. **异步沉淀**: 提取高价值概念，调用 `call_mcp_tool` (`vector-lake-mcp`: `prepare_ingest_batch`) 抛入后台沉淀。

## 2. <Contracts> (输出与交付契约)
- **RWE 纪律**: 战报包含 Top 10-15 文献，每篇展示真实世界证据 (RWE) 或技术成熟度 (TRL) 评估。
- **真实链接契约**: 禁止在报告中遗留 `[URL]` 占位符或幻觉链接。必须提供真实的 DOI。
- **资产转化契约**: 每项高价值信号需转化为预研技术栈和销售防御资产。
- **交付链接契约**: 最终战报必须通过聊天框输出带绝对物理路径的可点击 Markdown 链接。

## 3. <Failure_Taxonomy> (失败分类学)
- **虚假链接污染**: 战报中包含无法访问的占位符 URL，触发脚本直接打回。
- **架构剥离症**: 纯粹字面翻译学术论文，未能与核心架构（如 WiNGPT、ACE引擎）建立连接。
- **工具越权**: 不使用合法 MCP 组合操作后台图谱，或不使用原生落盘工具。
