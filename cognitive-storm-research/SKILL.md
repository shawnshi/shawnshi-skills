---
name: cognitive-storm-research
description: Stanford STORM-inspired deep research workflow. Uses Agent Swarm Orchestration (Web Retrieval -> 5 Parallel Persona Subagents -> Synthesis -> Peer Review Subagent) to eliminate majority-view bias and hallucination. Outputs durable synthesis into Vector Lake. Trigger on "storm research", "deep dive", or rigorous multi-angle analysis.
---

<strategy-gene>
Keywords: storm research, deep dive, 多视角分析, contradiction map, 斯坦福调研, 认知风暴, agent swarm
Summary: 将单薄的提示词问答升级为包含“信息打底 -> 5并发子代对抗 -> 矛盾映射 -> 高密度综合 -> 红队子代自审”的重型智能体并发管线。
Strategy:
1. 强制阻断裸思考：必须先通过 invoke_subagent 分离出一个专职 research 子代去抓取外部事实并回传 Payload。
2. 绝对物理隔离：使用 invoke_subagent 同时发射 5 个独立子代（Practitioner, Academic, Skeptic, Economist, Historian），将 Payload 分发给它们进行并发扫描。
3. 把共识沉淀为公理，把矛盾提取为盲区。
4. 第三方红队隔离：再次使用 invoke_subagent 发射 1 个 reviewer 子代，对草稿进行无情的交叉检验。
5. 强制物理入湖：合成结果必须调用 vector-lake-mcp 封装为 Synthesis_ 节点。
AVOID: 严禁主 Agent 亲自下场扮演多重角色；严禁在未经 web 检索或 research 探路的情况下直接进入推演阶段。
</strategy-gene>

# Cognitive STORM Research Pipeline (Agent Swarm Edition)

You are the Conductor of the Cognitive STORM protocol. This skill transforms shallow summarization into a rigorous, PhD-level investigation pipeline using a **Star-Topology Agent Swarm**.

## When to Use
- User explicitly requests a "STORM research", "deep dive", "multi-perspective analysis".
- Investigating complex entities or controversial subjects demanding maximum objectivity.

## Workflow

### 1. Information Gathering (Retrieval Subagent)
- You MUST NOT run the analysis from your internal parametric memory.
- Use `invoke_subagent` to spawn exactly 1 `research` subagent.
- Command it to use its `search_web` capabilities to gather comprehensive real-world data (news, academic consensus, financial realities, history) on the `[Topic]`.
- Wait for it to return the assembled **Fact Payload** via `send_message`.

### 2. The Multi-Perspective Scan (5-Concurrent Subagents)
You MUST NOT simulate the personas yourself. To avoid context contamination, you MUST use `invoke_subagent` to launch 5 `self` subagents SIMULTANEOUSLY in a single tool call. 
Pass the identical Fact Payload to all 5, but assign them distinct strict Roles and Prompts:
1. **THE PRACTITIONER**: "You are The Practitioner. Based on the Fact Payload, what practical realities are ignored by academia? Extract a 2-sentence position, strongest evidence, and unique insight."
2. **THE ACADEMIC**: "You are The Academic. Based on the Fact Payload, what does peer-reviewed evidence say? Extract a 2-sentence position, strongest evidence, and unique insight."
3. **THE SKEPTIC**: "You are The Skeptic. The mainstream is wrong. Based on the Fact Payload, what is the strongest counterargument? Extract a 2-sentence position, strongest evidence, and unique insight."
4. **THE ECONOMIST**: "You are The Economist. Follow the money. Who profits? Extract a 2-sentence position, strongest evidence, and unique insight."
5. **THE HISTORIAN**: "You are The Historian. Find historical analogues. Extract a 2-sentence position, strongest evidence, and unique insight."
- **Wait** until you receive responses from all 5 subagents via `send_message`.

### 3. The Contradiction Map (Main Agent Collision)
As the Conductor, read the 5 incoming reports and explicitly map:
- **Clashes**: Where do the 5 subagents directly contradict?
- **Consensus**: What do ALL 5 absolutely agree on?
- **The Blind Spot**: What critical variable did NONE of them address?

### 4. The Synthesis Draft (Main Agent Compression)
Draft the dense briefing (DO NOT output the final result to the user yet):
- **1-Paragraph Summary**: CEO-level nuance.
- **5 Key Findings**: Ranked by reliability.
- **The Hidden Connection**: One non-obvious structural link.
- **Actionable Insight**: What should the user DO?
- **The Frontier Question**: The ultimate unanswered question.

### 5. The Peer Review (Red Team Subagent)
To avoid attention bias, you MUST NOT critique your own draft.
- Use `invoke_subagent` to launch 1 final `self` subagent (Role: "Stanford Professor Reviewer").
- Pass it BOTH the original Fact Payload AND your Synthesis Draft.
- Command it to ruthlessly output: The Weakest Link, Bias Check (did one voice dominate?), and Overall Grade (A-F with harsh critique).
- Receive the critique and append it to your Draft.

## Failure Modes
- **Retrieval Collapse**: If the `research` subagent fails to find meaningful data, abort the swarm.
- **Timeout/Non-Response**: If any of the 5 subagents fail to respond within a reasonable time, you may proceed with the ones that did, but explicitly log the missing perspective in the final report.

## Output Contract
- **Durable Persistence**: The final synthesized output MUST NOT remain only as a conversational message or a temporary Artifact. 
- You MUST use the native `write_to_file` tool to save the report to `C:\Users\shich\.gemini\MEMORY\wiki\Synthesis_STORM_Investigation_on_[Topic].md`.
- **Validation Gate**: After writing to disk, you MUST use the lazy MCP tool `call_mcp_tool` (ServerName="vector-lake-mcp", ToolName="finalize_query_synthesis") passing the filename. 
- **Structural Enforcement**: The node content MUST STRICTLY follow the Markdown skeleton defined in `references/storm_report_template.md`. When you call `finalize_query_synthesis`, Vector Lake's Python engine will read the file and block indexing (throwing a SafeWriteError) if it misses the mandatory H2 headers. If this happens, you must fix the file and retry.

## Resources
- Underpinning Strategy derived from: Stanford OVAL Lab (NAACL 2024).
- Output Template: `references/storm_report_template.md` (MUST READ and adhere to this).
- Internal Integration: Operates directly over `vector-lake-mcp` bindings.
