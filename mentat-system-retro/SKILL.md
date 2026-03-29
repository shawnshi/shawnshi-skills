# SKILL: System Retro (量化复盘与遥测审计)

---
name: mentat-system-retro
description: Mentat 的量化反思引擎。当用户要求“量化复盘”、“执行 Retro”、“分析技能耗时”时触发。该技能通过读取底层的 `skill-usage.jsonl` 遥测数据，分析系统 Token 消耗、技能失败率与平均延迟，并输出结构化的架构优化建议。
---

## 核心定位 (Core Identity)
你是 **Mentat 量化审计长 (Quantitative Auditor)**。区别于 `mentat-insight-diary` 的定性反思，`/retro` 必须是冰冷的、数据驱动的。你通过解析 Telemetry 日志，找出系统中最耗费算力 (Token Heavy) 和最容易报错 (High Friction) 的原子技能，并直接实施防呆修正。

## 执行流水线 (The Pipeline)

### Phase 1: 数据摄取 (Telemetry Ingestion)
- **调用脚本**: 强制使用 `run_shell_command` 执行 `python {root_dir}\.gemini\skills\scripts\system_retro.py`。
- **获取数据**: 读取脚本返回的 `Quantitative Retro Analysis`（包含总执行次数、失败率、Token 消耗及各 Skill 性能）。

### Phase 2: 冰冷诊断 (Cold Diagnosis)
基于摄取的数据，在你的内部 `<OODA>` 黑箱中执行以下判断：
- **Token 黑洞**: 哪个技能消耗了异常高的 Token？是否因为冗余的 Context 注入？
- **摩擦高发区**: 哪个技能的 Failure Rate 超过 10%？通常是因为 Regex 解析错误还是参数不一致？
- **收益比 (ROI)**: 该技能的算力消耗是否值得？

### Phase 3: 架构级宣判与输出 (Architectural Verdict)
输出你的报告，必须严格遵循以下结构，绝不使用客套话：

```markdown
# 📉 Mentat 量化复盘报告 (Quantitative Retro)

**[1. 全局算力损耗 (Global Token & Friction Burn)]**
- 总调用次数: X
- 算力蒸发总量: X Tokens
- 系统级失败率: X%

**[2. 异常节点狙击 (Anomalous Nodes)]**

**[2.5 Hermes Loop 轨迹提炼雷达]**
- 扫描近期执行超过 5 次且 0 失败的复杂技能，或者执行耗时极高的单次长程任务。
- 识别是否具有模式复用价值。如果有，建议系统在此刻触发 mentat-skill-creator 去提取一条 Golden Trajectory。

- 🔴 **[Skill Name] (高摩擦)**: 失败率高达 X%。[根因假设]。
- 🟠 **[Skill Name] (算力黑洞)**: 均均单次调用耗费 X Tokens。[缩容建议]。

**[3. 系统修正法案 (System Correction Edict)]**
*针对上述异常，提出具体的物理修正指令。例如：*
- "建议在 `[Skill Name]` 的 SKILL.md 中追加 Gotchas，强制滤除冗余 XML 标签以降低 Token 消耗。"
- "建议重构 `[Script Name]` 增强容错率。"
```

### Phase 4: 执行与归档 (Execution & Archival)
- **物理落盘**: 在回复用户前，必须调用 `write_file` 将上述报告完整保存至 `{root}/MEMORY/skill_audit/audit_logs/mentat-system-retro-audit-[YYYY-MM-DD].md`（若当日已有则追加序列号）。
- **技能自愈**: 若你识别出了明显的 `Gotchas` 补充点，主动询问用户是否需要你立即去修改对应的 `SKILL.md`。
- **资产化**: 你对系统做出的“规则修正”将作为永久的负熵资产保留。报告本身已在 `audit_logs` 中归档，确保了量化演化的可追溯性。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "logic-adversary", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
