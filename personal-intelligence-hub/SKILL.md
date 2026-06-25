---
name: personal-intelligence-hub
version: 12.0.0
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

# Personal Intelligence Hub (战略情报作战中枢 V12.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. run_command (底层脚本：物理爬取情报源)
2. invoke_subagent (唤醒子代理进行二阶推演)
3. write_to_file (写入 intelligence_current_refined.json)
4. run_command (依次执行校验、红队对抗、简报锻造脚本)
5. call_mcp_tool (启动异步入湖，交由 Vector Lake 原生解析)

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
### Phase 1 & 2: Fetch & Refine (物理爬取与去重)
1. 执行底层抓取脚本（务必挂载编码锁）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\run_phase1_2.py"`
2. 脚本将自动采集并生成候选池 intelligence_candidates.json。
3. 调用 invoke_subagent 启动独立精炼子代理（TypeName: self）进行二阶推演。

### Phase 3: Semantic Deduction (子代理推演)
1. 在调用 invoke_subagent 时，**必须**在 Prompt 中包含以下指令（绝对物理路径防止幻觉）：
   > "You are the Intelligence Refinement Subagent.
   > 1. Read C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\references\quality_standard.md to strictly understand the JSON Schema and Localization Contract.
   > 2. Read C:\Users\shich\.gemini\MEMORY\raw\news\_runtime\personal-intelligence-hub\intelligence_candidates.json.
   > 3. Perform semantic deduction. **You MUST output all analytical content in Chinese (zh-CN)** and generate title_zh and summary_zh for all items.
   > 4. Ensure you generate global fields like punchline, insights, digest, market, and correctly structure action_levers as an array of objects.
   > 5. Use [[ ]] around core entities/people/specific nouns for graph linking.
   > 6. Do NOT write to disk manually. You MUST output the final valid JSON directly using the send_message tool to reply to me."
2. 子代理依据 Schema 执行推演并通过 send_message 发送数据。
3. 主代理被唤醒后，提取 JSON Payload，使用 write_to_file 写入 C:\Users\shich\.gemini\MEMORY\raw\news\intelligence_current_refined.json。

### Phase 4: Pipeline Gate Orchestration (门控与锻造)
严禁要求子代理执行脚本，必须由主代理依次接管验证：
1. **JSON 校验**: 运行 `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\validate_refined_json.py"`。若报错自行修正。
2. **红队对抗**: 若存在 L4 候选，运行 `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\adversarial_audit.py"`。
3. **最终锻造**: 运行 `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-intelligence-hub\scripts\forge.py"` 生成最终简报。

### Phase 5: Async Vector Lake Ingestion (异步图谱入湖)
1. **异步同步**: 报告锻造完成后，直接调用 call_mcp_tool 执行 vector-lake-mcp 的 prepare_ingest_batch，利用 invoke_subagent 拉起异步代理。**注意：务必将子代理的 TypeName 覆写为 self**。严禁直接调用阻塞式同步。实体节点的提取与双链 wiki 的生成全权交由 Vector Lake 底层引擎原生自动完成。

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
