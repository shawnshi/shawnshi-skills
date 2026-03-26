---
name: personal-roundtable
description: A high-density dynamic analytical framework (V4.0) that orchestrates real-world historical or contemporary figures into a "tension network" to scrutinize any topic. Features fragmented persistence per round (anti-dehydration by design), dynamic speaker selection, action-tagged dialogue with "简言之" compression, and structural ASCII topology maps. All sessions are eventually merged and physically archived to {root}/.gemini/MEMORY/roundtable/圆桌-{议题关键词}_{date}.md.
---

# Personal Roundtable (V4.0: Fragmented Persistence Edition)

“所有的执行偏差，本质上都是认知的偷懒。在这里，我们通过真实思想维度的对抗，萃取决策的晶核。”

---

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 动态选人与工作区初始化 (Initialization) - [Inversion]
**主持人 (Mentat)** 根据议题，动态选择 3-5 位真实历史/当代人物，构建**张力网络**。
- **工作区初始化 (Mandatory)**：
    - **隔离沙箱**：必须为本次圆桌建立专属临时目录：`{root}\.gemini\MEMORY\roundtable\workspace_{议题关键词}_{date}\`。若不存在请使用 `run_shell_command` 创建。
    - **写入开场**：使用 `write_file` 写入第一个碎片文件 `00_init.md`。文件头必须包含：标题、日期、主持人角色、参会人物卡片（姓名、MBTI、核心立场、选择理由），以及开场第一个定义性问题。
- **等待**：此时必须停止输出，等待用户指令。

### Phase 2: 对话循环与碎片化落盘 (Dialogue & Fragmented Write) - [Pipeline]
每一轮讨论必须遵循以下交互逻辑：

1.  **动态发言**：
    - 格式：`【人物名】【行动标签】：发言内容`。
    - **行动标签**：[陈述、质疑、补充、反驳、修正、综合]。
    - **硬性约束**：每段发言末尾必须包含 `**简言之**：[一句话逻辑压缩]`。

2.  **主持人综述 (Moderator Recap)**：
    - **核心争议点**：精准定位讨论中最深的逻辑裂缝。
    - **ASCII 思考框架图**：根据逻辑结构选择最贴合的形式（2x2矩阵/光谱轴/因果环路/层级树）。
    - **下潜问题**：提出后续引导问题。

3.  **碎片化落盘 (Fragmented Write - Anti-Dehydration)**：
    - **彻底抛弃全量重写**：严禁读取历史记录拼接！
    - **单点写入**：每轮结束后，直接使用 `write_file` 将**仅属于本轮的新增内容**写入工作区的新文件（如：`01_round1.md`, `02_round2.md`...）。

4.  **节点控制菜单 (Node Control)**：
    - 展示菜单：`【主持】：(可 / 止 / 深入此节 / 引入新人物)`。

### Phase 3: 全局总结与合并归档 (Final Merge & Synthesis) - [Reviewer]
当接收到“止”指令时：
1.  **全局总结写入**：生成总结与 ASCII 知识网络，并使用 `write_file` 写入 `99_summary.md` 到工作区。
2.  **物理合并 (The Merge)**：
    - 使用 `run_shell_command` 执行 PowerShell 脚本，将该工作区目录下的所有 `*.md` 文件按文件名升序排序，并合并为一个完整的单体文件。
    - 命令示例：`powershell.exe -NoProfile -Command "Get-ChildItem -Path '{工作区绝对路径}\*.md' | Sort-Object Name | Get-Content | Out-File -FilePath '{root}\.gemini\MEMORY\roundtable\圆桌-{议题关键词}_{date}.md' -Encoding utf8"`
3.  **资产终审**：声明“归档合并完成”，并提示最终文件路径。
4.  **Telemetry (Mandatory)**：记录元数据至 `{root}\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。

---

## 2. 交互协议与审美 (Protocols & Aesthetics)

- **ASCII 设计原则**：不复述内容，只呈现结构。
- **负熵原则**：每一阶段的输出必须具备高认知密度。
- **主持人准则**：理性之锚，挖深不铺广，求真 > 和谐。

---

## 3. 触发场景 (Trigger Traps)

- “我有个新想法……”
- “我想做一个关于 X 的计划。”
- “我面临一个复杂的决策。”

## 4. Telemetry & Metadata (Mandatory)
- JSON 结构：`{"skill_name": "personal-roundtable", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 5. 历史失效先验 (Gotchas)
- **[PATH CONSISTENCY]**: 确保 `MEMORY\roundtable` 及其子工作区文件夹存在（若不存在则先创建）。合并命令中使用的路径必须严格使用绝对路径并处理好空格引号。
- **[FILE NAMING]**: 碎片文件命名必须带有数字前缀（`00_`, `01_`, `99_`），以保证最终 `Get-ChildItem | Sort-Object` 拼接时的物理顺序正确。

---
*Updated to V4.0 | System State: Locked*
