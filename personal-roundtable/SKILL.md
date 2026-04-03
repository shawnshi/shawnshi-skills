---
name: personal-roundtable
description: A high-density dynamic analytical framework (V5.0) that orchestrates real-world historical or contemporary figures into a "tension network" to scrutinize any topic. Features fragmented persistence per round (anti-dehydration by design), dynamic speaker selection, action-tagged dialogue with "简言之" compression, and structural ASCII topology maps. All sessions are eventually merged and physically archived to C:\Users\shich\.gemini\MEMORY\roundtable\圆桌-{议题关键词}_{date}.md.
---

# Personal Roundtable (V5.0: Mentat Synthesis Edition)

“所有的执行偏差，本质上都是认知的偷懒。在这里，我们通过真实思想维度的对抗，萃取决策的晶核。”

---

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：必须严格按照 Phase 0 至 Phase 3 的顺序执行。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。

## 1. 核心流程与架构 (The Protocol)

### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启讨论前，必须通过 `python C:\Users\shich\.gemini\extensions\vector-lake\cli.py query "你的推演指令" --interleave` 检索 `MEMORY/` 中相关的历史洞察、反常识点或类似议题的结论。
2.  **情报汇总**：将检索到的核心情报以【负先验】的形式呈现给讨论组，防止讨论陷入已知的平庸结论。

### Phase 1: 动态选人与工作区初始化 (Initialization) [Mode: PLANNING]
1.  **动态选人 (Tension Grid)**：根据议题，从 `C:\Users\shich\.gemini\skills\personal-roundtable\references\personas.md` 中选择或自定义 3-5 位人物，构建**张力网络**。
2.  **工作区初始化 (Mandatory)**：
    - **物理创建**：使用 `run_shell_command` 创建专属目录 `C:\Users\shich\.gemini\MEMORY\wiki\roundtable\workspace_{议题关键词}_{date}\`。
    - **写入开场**：使用 `write_file` 写入第一个碎片文件 `00_init.md`。文件头包含人物卡片（姓名、MBTI、核心立场、选择理由）及开场问题。
3.  **等待**：此时必须停止输出，调用 `ask_user` 等待用户指令。

### Phase 2: 对话循环与碎片化落盘 (Dialogue & Fragmented Write) [Mode: EXECUTION]
1.  **动态发言**：
    - 格式：`【人物名】【行动标签】：发言内容`。
    - **行动标签**：[陈述、质疑、补充、反驳、修正、综合]。
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
1.  **全局总结写入**：生成总结与 ASCII 知识网络，并使用 `write_file` 写入 `99_summary.md` 到工作区。
2.  **物理合并 (The Merge)**：
    - 使用 `run_shell_command` 执行 `python C:\Users\shich\.gemini\skills\personal-roundtable\scripts\merger.py "工作区绝对路径" "目标文件绝对路径"`。
3.  **资产终审**：声明“归档合并完成”，并提示最终文件路径。


---

## 2. 交互协议与审美 (Protocols & Aesthetics)

- **ASCII 设计原则**：不复述内容，只呈现结构。参考 templates/ 下的标准模型。
- **负熵原则**：每一阶段的输出必须具备高认知密度。
- **主持人准则**：Mentat 角色，理性之锚，挖深不铺广，求真 > 和谐。

##  3.Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": personal-roundtable", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 4. 历史失效先验 (Gotchas)
- **[PATH CONSISTENCY]**: 确保 `MEMORY\roundtable` 及其子工作区文件夹存在。
- **[FILE NAMING]**: 碎片文件命名必须带有数字前缀（`00_`, `01_`, `99_`），以保证 `merger.py` 拼接时的物理顺序。
- **[NO SUMMARY DUPLICATION]**: 严禁在合并前读取整个对话历史，必须严格依赖物理文件作为真实记忆。

---
*Updated to V5.0 | System State: Locked*
