---
name: personal-intelligence-hub
version: 12.2.0
tier: action-allowed
description: '战略情报作战中枢。调度子代理执行多源情报扫描、二阶推演与红队审计。强制读取标准配置并通过沙盒与门控脚本保障交付质量。禁止捏造洞察或越权写入。'
triggers: ["情报扫描", "战略简报", "信息去重", "红队审计"]
---

<strategy-gene>
Keywords: 战略情报扫描, 去重精炼, 二阶推演, 红队审计
Summary: 调度多源情报源执行 7 日闭环扫描，将新闻噪音转化为高价值行动杠杆。
Strategy:
1. 配置先行：严格依据 strategic_focus.json 锁定扫描主题与排除词。
2. 语义去重：执行 7 日 URL 与指纹对齐，确保 100% 信息增量。
3. 结构化提纯：每条情报必须满足 Fact -> Connection -> Deduction -> Actionability 结构。
4. 强制双链图谱与双轨落盘：核心实体必须链接；长效落盘遵守 Compiled Truth | Timeline 规范。
5. 异步入湖：提纯出的核心实体必须推送至向量湖图谱。
AVOID: 把“摘要”伪装成“洞察”；缺乏证据时输出 L4 级判断；重复推送同一信号；遗漏双链图谱标记；将原始抓取数据直接写入核心图谱。
</strategy-gene>

# Personal Intelligence Hub (战略情报作战中枢 V12.2 Native)

## 核心里程碑 (Milestone Protocol)
**[MILESTONES]** 抛弃僵化的顺序链，通过以下独立舱室推进，确保局部失败不导致全局宕机：
- **M1: 猎群游荡 (Swarm Fetch)**：唤醒 3 个兵种的 `research` 子代理并发探索，并将其捕获的情报直接写入当前会话的沙盒候选池。
- **M2: 二阶推演**：唤醒带系统时间戳的子代理进行语义提纯。
- **M3: 门控与红队对抗**：在隔离沙盒内完成对抗博弈（允许优雅降级）。
- **M4: 制品交付**：将最终情报锻造为当前会话的 Artifact。
- **M5: 异步入湖**：派发纯净载荷由子代理推向 Vector Lake。

## 0. 核心约束
- **配置优先**: 扫描范围、优先源、排除词以 references/strategic_focus.json 为准。
- **质量合同**: 必须满足 references/quality_standard.md 的四层结构。
- **状态显式化**: 状态写入 blackboard，去重走 history_manager，交付前通过 briefing_gate。
- **跨平台与安全寻址**: 所有 Python 脚本调用必须使用绝对物理寻址并挂载 UTF-8 环境锁，严禁依赖相对路径。

## 1. 运行资产
- **Feeds**: references/karpathy_feeds.json
- **Strategy Config**: references/strategic_focus.json
- **Quality Contract**: references/quality_standard.md
- **Briefing Template**: references/briefing_template.md
- **State Scripts**: scripts/blackboard.py, scripts/history_manager.py, scripts/briefing_gate.py

## 2. 执行协议 (Execution Pipeline)
### Phase 1 & 2: 猎群部署与广域网捕获 (Agentic Swarm Fetch)
1. **动态沙盒寻址**: 主代理解析当前会话的沙盒路径：`<appDataDir>\brain\<conversation-id>\scratch\`。
2. **猎群集群拉起**: 废弃脆弱的 Python 爬虫！主代理必须使用 `invoke_subagent` 并发拉起 3 个 `TypeName: research` 的高级搜索子代理，套用以下集装箱 Prompt：

> **[猎群子代理通用 Prompt 注入模板]**
> "你是一个高级战略情报 `research` 子代理。当前系统日期是 `[动态填入今天绝对日期]`。
> 你的专属任务是：`[填入以下 A/B/C 三大兵种任务之一]`。
> 
> **硬性约束：**
> 1. **自主深潜**：你拥有网络访问与文件读取能力。遇到反爬或无法访问的链接，必须自主寻找其他来源替代，不可抛出异常中断。
> 2. **事实纪律**：过滤 7 天前的旧闻。获取新闻后必须交叉验证真实性。
> 3. **统一汇流协议**：你必须通过 `send_message` 将收集到的有效情报以 JSON 数组格式回传。字段包括：`title`, `url`, `publish_date`, `raw_fact_summary`。

3. **猎群专属指令 (Task Payloads)**：
   - **[A] 阵地哨兵 (Core Feeds)**：读取 `C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\references\karpathy_feeds.json`，自主调用网页读取工具扫描这些顶级智库和信源的最新文章并提取核心要点。
   - **[B] 主题雷达 (Strategic Focus)**：读取 `strategic_focus.json` 中的关键词，使用搜索引擎 (`search_web`) 在全网大范围捕获匹配该战略主题的最新动向。
   - **[C] 盲区游侠 (Serendipity Scout)**：抛弃所有名单限制！去搜寻那些“未进入大众视野，但具备底层破坏力”的极客科技突破或跨界资本动作，打破系统的信息茧房。

4. **汇流与落盘**: 主代理静默等待，收到 3 个子代理的 JSON Payload 后，将其合并去重，并使用 `write_to_file` 统一写入 `scratch/intelligence_candidates.json` 中。

### Phase 3: 附带时间锚点的二阶推演
1. **跨界核实特权**: 主代理在启动推演代理时，必须将其也升级为 `TypeName: research`，赋予其全网搜索验证的权限。在 Prompt 中注入当前系统日期和动态物理路径：

   > "You are the Strategic Intelligence Refinement Subagent (Research-Empowered).
   > **当前系统基准日期为: [动态填入今天日期]**
   > 1. Read C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\references\quality_standard.md to strictly understand the JSON Schema and Localization Contract.
   > 2. Read [填入刚刚解析出的沙盒候选池绝对路径 intelligence_candidates.json]。
   > 3. **交叉核实红线 (Cross-Validation)**: 在阅读候选池数据时，如果发现任何逻辑断层、金额模糊或来源可疑的情报，**你必须立刻使用 `search_web` 去广域网搜索核实！** 绝不允许闭门造车式地轻信候选池的原始数据。
   > 3. Perform semantic deduction. **You MUST output all analytical content in Chinese (zh-CN)** and generate title_zh and summary_zh for all items.
   > 4. Ensure you generate global fields like punchline, insights, digest, market, and correctly structure action_levers as an array of objects.
   > 5. Use [[ ]] around core entities/people/specific nouns for graph linking.
   > 6. Do NOT write to disk manually. You MUST output the final valid JSON directly using the send_message tool to reply to me."
2. 子代理依据 Schema 执行推演并通过 send_message 发送数据。
3. 主代理被唤醒后，提取 JSON Payload，**严禁写出沙盒**，使用 `write_to_file` 将其写入当前会话的 `scratch/intelligence_current_refined.json` 中。

### Phase 4: Pipeline Gate Orchestration (门控与锻造)
严禁要求子代理执行脚本，必须由主代理依次接管验证：
1. **JSON 校验**: 运行 `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\validate_refined_json.py" "[Absolute_Sandbox_Path]\intelligence_current_refined.json"`。若报错自行修正。
2. **红队对抗 (L4 门控)**: 
   - 检查 `intelligence_current_refined.json` 中是否有 `"intelligence_level": "L4"`。
   - 若存在，必须先使用 `invoke_subagent` (TypeName: self, Role: cognitive-logic-adversary) 发起对抗，并由主代理将报告落盘至**当前会话沙盒** `scratch/redteam_report.json` 中。
   - 随后执行验证脚本并挂载沙盒审批单：`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\adversarial_audit.py" "[Absolute_Sandbox_Path]\redteam_report.json"`。
   - ⚠️ 若不存在 L4，或因宕机未能提供人工/活体子代理红队报告，直接**不带参数**运行该审计命令。此时门控系统将触发安全保护机制，把所有未经验证的 L4 强制降级为 L3。
3. **最终 Artifact 锻造**: 运行锻造脚本，必须将最终生成的简报以 **Artifact 制品格式 (UserFacing: true)** 保存在当前 `brain/<conversation-id>/` 会话可见区，绝对禁止写入后台无主目录。

### Phase 5: Async Vector Lake Ingestion (异步图谱入湖)
1. **异步同步 (STQM & Payload MCP)**: 报告锻造完成后，使用 `write_to_file` 将清洗后的最终情报和 `tension_edges` 写入**当前会话的** `scratch/ingest_payload.json` 载荷文件。
2. 然后调用 `invoke_subagent` (TypeName: self) 唤醒入湖代理，指示它读取该 JSON 载荷，并直接调用 `vector-lake-mcp:prepare_ingest_batch` 执行物理入湖。严禁直接把长篇幅内容塞入 CLI 参数或工具调用层。实体节点的提取与双链 wiki 的生成全权交由 Vector Lake 底层引擎自动完成。

## 3. <Contracts> (输出与交付契约)
- punchline 不得为空；action_levers 至少 3 条；top_10 最多 10 条且 URL 不重复。
- 若存在 L4 级别评估，必须有 adversarial_audit 记录证明其经过压力测试。
- **遥测记录**: 系统脚本自动写入 telemetry.json，主代理无需干预。
- **交付链接契约**: 简报落盘后，主代理必须向用户输出包含绝对路径的可点击 Markdown 链接（如：[战略情报简报](file:///C:/Users/shich/...)）。

## 4. <Failure_Taxonomy> (失败分类学)
- **路径幻觉 (Pathing Hallucination)**：严禁使用相对路径，必须严格使用绝对路径。
- **违规实体越权**：主代理严禁自己提取实体节点并生成空的 wiki 文件，双链解析与生成必须全权交由 Vector Lake 异步入湖管道原生处理。
- **内容注水**：禁止把摘要伪装成洞察，情报必须包含行动杠杆。
- **证据不足 (Evidence Gap)**：禁止在缺乏强力支撑时输出 L4 高等级战略判断。
- **越界写入 (Boundary Violation)**：禁止把 skill 目录当作运行时数据库。临时文件必须存于沙盒。
- **优雅降级 (Degraded Mode)**: 若子代理宕机或报错，主代理必须跳过推演环节，直接读取粗筛池 intelligence_candidates.json 打上 [Degraded Mode] 标签过检并生成事实简报，确保情报网“绝不静默”。
