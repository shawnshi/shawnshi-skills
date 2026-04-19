---
name: personal-roundtable
description: A high-density dynamic analytical framework (V5.0) that orchestrates real-world historical or contemporary figures into a "tension network" to scrutinize any topic. Features fragmented persistence per round (anti-dehydration by design), dynamic speaker selection, action-tagged dialogue with "简言之" compression, and structural ASCII topology maps. All sessions are eventually merged and physically archived to C:\Users\shich\.gemini\MEMORY\roundtable\圆桌-{议题关键词}_{date}.md.
---

# Personal Roundtable (V5.0: Mentat Synthesis Edition)

“所有的执行偏差，本质上都是认知的偷懒。在这里，我们通过真实思想维度的对抗，萃取决策的晶核。”

## When to Use
- 当用户希望借助历史或现实人物的张力网络来审视某个议题、方案或决策时使用。
- 目标是构建高密度、多视角对话并沉淀结构化洞察，而不是写一篇普通评论。

## Workflow

### 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：必须严格按照 Phase 0 至 Phase 3 的顺序执行。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。

### Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation during long-form multi-character discussions, the round phases MUST NOT be held entirely in the main memory.
1. **Arena Creation**: Before starting the roundtable, define the topic, participants, and rules in a sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Roundtable_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) to read the packet, execute the actual conversational turns, and append the dialog fragments to the designated physical output file (`.md`).
3. **Suspension**: The main agent acts purely as the host, suspending execution during the sub-agent's heavy text generation, and finally reading the condensed topology or summary upon completion.

### 核心流程与架构 (The Protocol)

### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启讨论前，优先通过本地可用的 `vector-lake` CLI 执行 `query "你的推演指令" --interleave`，检索 `MEMORY/` 中相关的历史洞察、反常识点或类似议题的结论。
2.  **情报汇总**：将检索到的核心情报以【负先验】的形式呈现给讨论组，防止讨论陷入已知的平庸结论。

### Phase 1: 动态选人与工作区初始化 (Initialization) [Mode: PLANNING]
1.  **动态选人 (Tension Grid)**：根据议题，从 `C:\Users\shich\.gemini\skills\personal-roundtable\references\personas.md` 中选择或自定义 3-5 位人物，构建**张力网络**，至少包含一位"意外视角"。
2.  **工作区初始化 (Mandatory)**：
    - **物理创建**：使用 `run_shell_command` 创建专属目录 `C:\Users\shich\.gemini\MEMORY\raw\roundtable\workspace_{议题关键词}_{date}\`。
    - **写入开场**：使用 `write_file` 写入第一个碎片文件 `00_init.md`。文件头包含人物卡片（姓名、MBTI、核心立场、选择理由）及开场问题。
3.  **等待**：此时必须停止输出，调用 `ask_user` 等待用户指令。

### Phase 2: 对话循环与碎片化落盘 (Dialogue & Fragmented Write) [Mode: EXECUTION]
1.  **动态发言**：
    - 格式：`【人物名】【行动标签】：发言内容`。
    - **行动标签**：[陈述、质疑、补充、反驳、修正、综合]。
    - 每人发言必须是对前面发言的回应（质疑/补充/反驳），不许自说自话
    - **硬性约束**：每段发言末尾必须包含 `**简言之**：[一句话逻辑压缩]`。
2.  **主持人综述 (Mentat Recap)**：
    - **核心争议点**：精准定位逻辑裂缝。
    - **ASCII 思考框架图**：参考 `C:\Users\shich\.gemini\skills\personal-roundtable\templates\ascii_topology.md` 选择最贴合的形式。
    - **下潜问题**：引导后续讨论。
3.  **碎片化落盘 (Anti-Dehydration)**：
    - **单点写入**：每轮结束后，直接使用 `write_file` 将本轮内容写入 `01_round1.md`, `02_round2.md`... 等文件。
4.  **节点控制菜单 (Node Control)**：
    - 展示菜单：`【主持】：(可 / 止 / 深入此节 / 引入新人物)`。调用 `ask_user` 获取用户选择。

### Phase 3: 全局总结与合并归档 (Final Merge & Synthesis) [Mode: EXECUTION]
1.  **全局总结写入**：生成总结与 ASCII 知识网络、列出未解决的开放问题，并使用 `write_file` 写入 `99_summary.md` 到工作区。
2.  **物理合并 (The Merge)**：
    - 使用 `run_shell_command` 执行 `python C:\Users\shich\.gemini\skills\personal-roundtable\scripts\merger.py "工作区绝对路径" "目标文件绝对路径"`。
3.  **资产终审**：声明“归档合并完成”，并提示最终文件路径。


## Resources
- `references/personas.md`
- `templates/ascii_topology.md`
- `scripts/merger.py`
- `C:\Users\shich\.gemini\tmp\playgrounds\Roundtable_Packet_[TIMESTAMP].md`
- `C:\Users\shich\.gemini\MEMORY\raw\roundtable\workspace_{议题关键词}_{date}\`

## Failure Modes
- `IF [Action == "Write Workspace"] THEN [Require Directory_Exists("MEMORY\\roundtable\\...") == TRUE]`
- `IF [Action == "Write Fragment File"] THEN [Require Filename matches "^\\d\\d_.*"]`
- `IF [Action == "Final Merge"] THEN [Halt if reading entire dialogue history] AND [Require read(physical fragment files)]`
- **ASCII 设计原则**：不复述内容，只呈现结构。参考 templates/ 下的标准模型。
- **负熵原则**：每一阶段的输出必须具备高认知密度。
- **主持人准则**：理性之锚，挖深不铺广，求真 > 和谐，元认知。
- **参会人准则**：必须忠于其真实思想体系发言，不是泛泛而谈。

## Output Contract
- 每轮对话都必须生成碎片文件，并由主持人产出争议点、ASCII 结构图与下一步下潜问题。
- 最终归档件必须是合并后的完整圆桌纪要，包含人物卡、碎片轮次、总结与开放问题。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": personal-roundtable", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## Legacy Notes

- **ASCII 设计原则**：不复述内容，只呈现结构。参考 templates/ 下的标准模型。
- **负熵原则**：每一阶段的输出必须具备高认知密度。
- **主持人准则**：理性之锚，挖深不铺广，求真 > 和谐，元认知。
- **参会人准则**：
  - 必须忠于其真实思想体系发言，不是泛泛而谈
  - 引用/化用其经典著作或知名观点
  - 发言有锋芒：质疑要见骨，补充要推进，不说正确的废话
  - 每段结尾 **简言之** 一句话压到极致

## 4. 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Write Workspace"] THEN [Require Directory_Exists("MEMORY\\roundtable\\...") == TRUE]`
- `IF [Action == "Write Fragment File"] THEN [Require Filename matches "^\\d\\d_.*"]`
- `IF [Action == "Final Merge"] THEN [Halt if reading entire dialogue history] AND [Require read(physical fragment files)]`

---
*Updated to V5.0 | System State: Locked*
