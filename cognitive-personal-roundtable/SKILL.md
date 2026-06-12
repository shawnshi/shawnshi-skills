---
name: cognitive-personal-roundtable
version: 8.2.0
description: A high-density dynamic analytical framework (V5.0) that orchestrates real-world historical or contemporary figures into a "tension network" to scrutinize any topic. Features fragmented persistence per round (anti-dehydration by design), dynamic speaker selection, action-tagged dialogue with "简言之" compression, and structural ASCII topology maps. All sessions are eventually merged and physically archived to C:\Users\shich\.gemini\MEMORY\roundtable\圆桌-{议题关键词}_{date}.md.
triggers: ["开启圆桌会议", "多视角分析", "找几个人来辩论", "搭建张力网络", "圆桌推演"]
---


<strategy-gene>
Keywords: 圆桌, 多人物辩论, tension network, 思想碰撞
Summary: 组织历史或当代人物张力网络，对议题进行多视角攻防。
Strategy:
1. 明确议题、人物、张力轴和回合边界。
2. 分片写入对话或观点，防止长文本截断。
3. 最终合并为洞察、分歧、盲点和可行动结论。
AVOID: 禁止人物只做表态机器；禁止没有张力的同质化观点堆叠。
</strategy-gene>

# Cognitive Personal Roundtable (V8.2 Native)

“所有的执行偏差，本质上都是认知的偷懒。在这里，我们通过真实思想维度的对抗，萃取决策的晶核。”

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：必须严格按照 Phase 0 至 Phase 3 的顺序执行。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。

### Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation during long-form multi-character discussions, the round phases MUST NOT be held entirely in the main memory.
1. **Arena Creation**: Before starting the roundtable, define the topic, participants, and rules in a sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Roundtable_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent using the `invoke_subagent` tool to read the packet, execute the actual conversational turns, and append the dialog fragments to the designated physical output workspace using the `write_to_file` tool.
3. **Suspension**: The main agent acts purely as the host, suspending execution during the sub-agent's heavy text generation, and finally reading the condensed topology or summary upon completion.

---

## 1. 核心流程与架构 (The Protocol)

### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启讨论前，优先通过 `call_mcp_tool` 调度 `vector-lake` 的相关能力，检索 `MEMORY/` 中相关的历史洞察、反常识点或类似议题的结论。
2.  **情报汇总**：将检索到的核心情报以【负先验】的形式呈现给讨论组，防止讨论陷入已知的平庸结论。

### Phase 1: 动态选人与工作区初始化 (Initialization) [Mode: PLANNING]
1.  **动态选人 (Tension Grid)**：使用 `view_file` 工具读取 `C:\Users\shich\.gemini\config\skills\cognitive-personal-roundtable\references\personas.md`，从中选择或自定义 3-5 位人物构建**张力网络**，至少包含一位"意外视角"。
2.  **工作区初始化 (Mandatory)**：
    - 直接使用原生 `write_to_file` 工具将第一个碎片文件 `00_init.md` 写入 `C:\Users\shich\.gemini\MEMORY\raw\roundtable\workspace_{议题关键词}_{date}\00_init.md` (目录会自动创建)。
    - 文件头包含人物卡片（姓名、MBTI、核心立场、选择理由）及开场问题。
3.  **等待确认**：调用原生的 `ask_question` 工具抛出选人与议题，等待用户指令后方可推进。

### Phase 2: 对话循环与碎片化落盘 (Dialogue & Fragmented Write) [Mode: EXECUTION]
*(此部分由被 `invoke_subagent` 唤醒的子代理负责循环执行)*
1.  **动态发言**：
    - 格式：`【人物名】【行动标签】：发言内容`。
    - **行动标签**：[陈述、质疑、补充、反驳、修正、综合]。
    - 每人发言必须是对前面发言的回应（质疑/补充/反驳），不许自说自话
    - **硬性约束**：每段发言末尾必须包含 `**简言之**：[一句话逻辑压缩]`。
2.  **主持人综述 (Mentat Recap)**：
    - **核心争议点**：精准定位逻辑裂缝。
    - **ASCII 思考框架图**：参考 `templates/ascii_topology.md` 规范选择形式。
    - **下潜问题**：引导后续讨论。
3.  **碎片化落盘 (Anti-Dehydration)**：
    - 每轮结束后，直接使用原生 `write_to_file` 工具将本轮内容写入 `01_round1.md`, `02_round2.md`... 等文件。
4.  **节点控制菜单 (Node Control)**：
    - 展示菜单：`【主持】：(可 / 止 / 深入此节 / 引入新人物)`。调用 `ask_question` 获取用户选择。

### Phase 3: 全局总结与合并归档 (Final Merge & Synthesis) [Mode: EXECUTION]
1.  **全局总结写入**：生成总结与 ASCII 知识网络、列出未解决的开放问题，并使用原生 `write_to_file` 写入 `99_summary.md` 到工作区。
2.  **物理合并 (The Merge)**：
    - 调用原生的 `run_command` 执行如下命令完成文件合并：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-personal-roundtable\scripts\merger.py" "C:\Users\shich\.gemini\MEMORY\raw\roundtable\workspace_{议题关键词}_{date}" "C:\Users\shich\.gemini\MEMORY\roundtable\圆桌-{议题关键词}_{date}.md"
```
3.  **资产终审**：声明“归档合并完成”，并提示最终文件绝对路径。

---

## 2. <Contracts> (输出与交付契约)

- **输出硬锁**：每轮对话都必须物理落盘生成碎片文件。主持人必须产出争议点、ASCII 结构图与下一步下潜问题。
- **归档硬锁**：最终归档件必须是调用 Python 脚本合并后的完整圆桌纪要，包含人物卡、碎片轮次、总结与开放问题。
- **遥测记录**: 归档完成后，主代理必须使用 `write_to_file` 将遥测数据以 JSON 格式写入 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
  推荐结构：`{"skill_name": "cognitive-personal-roundtable", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. <Failure_Taxonomy> (失败分类学)

- **ASCII 画饼 (ASCII Hallucination)**：ASCII 设计原则是不复述内容，只呈现结构。
- **角色崩塌 (Persona Break)**：参会人准则：必须忠于其真实思想体系发言；必须引用/化用其经典著作或知名观点；发言要有锋芒（质疑要见骨，补充要推进），严禁说正确的废话。每段结尾必须带有 `**简言之**：` 压缩句。
- **记忆击穿 (Memory Blowout)**：`IF [Action == "Final Merge"] THEN [Halt if reading entire dialogue history] AND [Require read(physical fragment files)]`。主代理严禁自己去阅读和拼接长达几万字的聊天记录，必须依赖底层的 `merger.py` 进行物理合并。
- **目录游离 (Path Violation)**：`IF [Action == "Write Workspace"] THEN [Require Directory_Exists("C:\Users\shich\.gemini\MEMORY\raw\roundtable\...") == TRUE]`。所有生成的碎片文件必须存在于同一个指定的绝对工作区内。
- **未验证的假工具 (Tool Hallucination)**：严禁伪造 `run_shell_command` 或 `user-input gate`。交互必须走 `ask_question`，终端命令必须走 `run_command`。写入文件必须走 `write_to_file`，严禁使用已被淘汰的 `write_file`。
