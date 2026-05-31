# 📉 Mentat 量化复盘报告 (Quantitative Retro)

> **审计基准日**: [YYYY-MM-DD]
> **数据源**: `skill-usage.jsonl` & `system_retro.py`

## [1] 全局算力损耗 (Global Token & Friction Burn)
- **总调用频次 (Calls)**: [X] 次
- **系统级失败率 (Failure Rate)**: [X]%
- **算力蒸发总量 (Token Burn)**: [X] Tokens
- **系统整体评价**: [一句话定性：如“处于高摩擦态”、“算力溢出”、“健康运作”等]

## [2] 异常节点狙击 (Anomalous Nodes)

### 🔴 高摩擦预警 (High Friction > 10% Failure Rate)
- **[Skill_Name_1]**: 
  - **故障率**: [X]%
  - **平均耗时**: [X]s
  - **根因假设**: [冷酷指出问题，如：Regex 匹配常因 JSON 转义问题断裂。]

### 🟠 算力黑洞 (Token Blackholes)
- **[Skill_Name_2]**:
  - **均次消耗**: [X] Tokens
  - **消耗占比**: [X]%
  - **病理诊断**: [如：在循环中过度加载了不需要的全局 Context，导致无谓的上下文刷新。]

## [3] Hermes 轨迹提炼雷达 (Trajectory Harvest)
> *扫描近期高频且零失败的执行路径，寻找可固化的优质资产。*

- **模式识别**: [如：`academic-paper-reader` 近期连续 8 次执行成功，且用户采纳率高。]
- **提炼建议**: [如：建议将这 8 次中表现出的“特定文献源的防沉迷查询逻辑”抽象为一个新的独立 Skill。]

## [4] 系统修正法案 (System Correction Edict)
> *针对上述异常，提出具体的物理修正指令。*

1. **针对 [Skill_Name_1]**: 建议在其 `SKILL.md` 的 `## Gotchas` 区块追加指令：“强制所有 JSON 输出必须经过 `json.dumps()` 过滤，严禁拼接字符串”。
2. **针对 [Skill_Name_2]**: 建议修改其触发 Prompt，强制限制 `read_file` 的 `end_line` 参数，禁止无脑读取全文。

---
*Mentat Audit Complete. 报告已归档至物理冷库。*
*(请在此处附加主动询问：指挥官，是否需要我立即调起 `mentat-skill-creator` 执行上述防呆补丁的写入？)*