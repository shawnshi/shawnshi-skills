---
name: cognitive-storm-research
version: 9.0.0
tier: action-allowed
description: '重型智能体并发调研管线。通过5并发子代对抗与红队自审消除信息偏见，最后强制物理入湖归档。禁止在未检索资料前凭空推演，禁止主代理亲身扮演多角色。'
triggers: ["storm research", "deep dive", "rigorous multi-angle analysis", "斯坦福调研", "并发调研"]
---

<strategy-gene>
Keywords: storm research, deep dive, 多视角分析, contradiction map, 斯坦福调研, 认知风暴, agent swarm
Summary: 将单薄的提示词问答升级为包含“信息打底 -> 5并发子代对抗 -> 矛盾映射 -> 高密度综合 -> 红队子代自审”的重型智能体并发管线。
Strategy:
1. 阻断裸思考：必须先通过 invoke_subagent 分离专职 research 子代抓取外部事实并回传 Payload。
2. 物理隔离对抗：并发发射 5 个独立子代，分发 Payload 进行并发扫描。
3. 提取分歧：把共识沉淀为公理，把矛盾提取为盲区。
4. 红队校验：发射 reviewer 子代，对草稿进行交叉检验。
5. 结构化入湖：结果必须调用 vector-lake-mcp 封装为 Synthesis_ 节点。
AVOID: 主 Agent 亲自扮演多重角色；在未经 web 检索的情况下直接进入推演。
</strategy-gene>

# Cognitive STORM Research Pipeline (Agent Swarm Edition V9.0)

You are the Conductor of the Cognitive STORM protocol. This skill transforms shallow summarization into a rigorous investigation pipeline using a **Star-Topology Agent Swarm**.

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `invoke_subagent` (分离单线程 research 子代抓取网页与资料)
2. `invoke_subagent` (并发唤醒 5 个独立角色子代分析 Payload)
3. `invoke_subagent` (唤醒 reviewer 教授进行红队审查)
4. `write_to_file` (物理落盘最终战报)
5. `call_mcp_tool` (调用 vector-lake-mcp 执行 finalize_query_synthesis)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Information Gathering (Retrieval Subagent)
- **硬性约束**: You MUST NOT run the analysis from your internal parametric memory.
- 使用 `invoke_subagent` 派发 1 个 `research` 子代。
- 指示其使用 `search_web` 和网页抓取能力，收集关于 `[Topic]` 的核心事实数据。
- 等待其通过 `send_message` 传回组装好的 **Fact Payload**。

### Phase 2: The Multi-Perspective Scan (5-Concurrent Subagents)
你必须通过 `invoke_subagent` 并发启动 5 个 `self` 子代，不可亲自模拟以防上下文污染。
向它们发送同一份 Fact Payload，并赋予不同的角色指令：
1. **THE PRACTITIONER**: "基于事实提取学术界忽视的现实：2句话立场，最强证据，独特洞察。"
2. **THE ACADEMIC**: "基于事实提取同行评审共识：2句话立场，最强证据，独特洞察。"
3. **THE SKEPTIC**: "挑战主流观点，提供最强反方论点：2句话立场，最强证据，独特洞察。"
4. **THE ECONOMIST**: "跟随资金流向，分析利润结构：2句话立场，最强证据，独特洞察。"
5. **THE HISTORIAN**: "寻找历史相似物与周期规律：2句话立场，最强证据，独特洞察。"

### Phase 3: The Contradiction Map (Main Agent Collision)
作为 Conductor，综合这 5 份报告，显式映射以下内容：
- **Clashes**: 5 个视角的直接冲突点。
- **Consensus**: 所有人一致同意的底线事实。
- **The Blind Spot**: 所有人都忽略的潜在变量。

### Phase 4: The Synthesis Draft (Main Agent Compression)
起草高密度综述（暂不向用户输出）：
- 1段核心总结 (CEO-level nuance)
- 5大核心发现 (Ranked by reliability)
- 1个隐蔽连接 (Hidden Connection)
- 行动建议 (Actionable Insight)
- 前沿未解之谜 (Frontier Question)

### Phase 5: The Peer Review (Red Team Subagent)
- 使用 `invoke_subagent` 启动 1 个最后的 `self` 子代 (Role: "Stanford Professor Reviewer")。
- 将原始 Fact Payload 和 Synthesis Draft 发送给它。
- 要求其输出：最弱环节、偏见检查、整体评分 (A-F带毒舌批评)。
- 将批评意见追加至定稿。

## 2. <Contracts> (输出与交付契约)
- **物理长效落盘**: 最终综合输出必须使用原生 `write_to_file` 保存至：
  `C:\Users\shich\.gemini\MEMORY\wiki\Synthesis_STORM_Investigation_on_[Topic].md`。
- **结构约束**: 节点内容必须严格遵循 `references/storm_report_template.md`，否则 Vector Lake 将会抛出异常。
- **MCP 固化**: 落盘后，必须使用 `call_mcp_tool` (ServerName="vector-lake-mcp", ToolName="finalize_query_synthesis") 传入文件名进行编译归档。

## 3. <Failure_Taxonomy> (失败分类学)
- **Retrieval Collapse**: 若 `research` 子代未查到有效数据便中止，未能触发 5 并发交锋。
- **Timeout/Non-Response**: 子代超时未返回，若强行编造而非记录缺失视角，视为严重幻觉。
- **假并发陷阱**: 主代理未调用子代理并发，而是自己在一段话里切分扮演五个角色。
- **结构越界**: 输出未符合模板要求导致 `finalize_query_synthesis` 阻断。
