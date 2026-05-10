---
name: mentat-collaboration-audit
description: 系统与协作联合审计管线。当用户表达“复盘”、“效率低”、“查看Token消耗”、“系统绕弯路”或要求执行 Retro/月度交互洞察时触发。统一收口系统底层算力损耗与人机协作摩擦的联合审计。
triggers: ["复盘", "效率低", "系统绕弯路", "量化复盘", "执行 Retro", "分析技能耗时", "系统交互报告", "查看 Token 消耗"]
---

<strategy-gene>
Keywords: 系统复盘, Token 消耗, 协作摩擦, 联合审计
Summary: 打通底层硬件算力损耗与顶层人机协作摩擦，从数据诊断自动演进至高管级行为指导和资产沉淀。
Strategy:
1. 意图分流：根据用户意图进入 Telemetry (机器视角) 或 Interaction (交互视角)。
2. 数据压舱：无论进入何种模式，必须先调用 `system_retro.py` 或 `analyze_insights_v4.py`，无遥测数据则不输出。
3. 对抗审计：若处于交互复盘，必须提取出核心摩擦模式，并给出针对性的 Checklist/Prompt 沉淀。
AVOID: 禁止没有数据依据的归因；禁止不输出具体行动指南的纯概念复盘；禁止使用客套话。
</strategy-gene>

# Mentat Collaboration Audit (联合审计管线 V10.0)

这是系统最高级别的防线。你必须像一台冷酷的心电图监护仪，通过客观遥测数据宣判系统熵增。

## 0. 核心调度约束 (Global State Machine)
系统分为两种模式（Mode），必须在执行的第一步通过 `[System State: Mode X]` 显示声明。

### Mode 1: Telemetry (硬核遥测模式)
**适用场景**：用户仅要求查看 Token、算力损耗、错误率或请求系统耗时等硬指标。
1. **数据摄取**: 强制调用当前工作区的 Python 脚本执行遥测汇聚（如：`python ../scripts/system_retro.py` 或调用自身目录内的可用采集脚本）。若脚本失效，必须主动寻找 `MEMORY/skill_audit/telemetry/` 下的近期 JSON 文件抽样。
2. **架构宣判**: 输出包含 [全局算力损耗]、[异常节点狙击] 的冰冷报告。

### Mode 2: Interaction (深度协作模式)
**适用场景**：用户反映效率低下、协作阻力高，或要求完整的周/月度交互复盘。
1. **数据与交互摄取**: 并行或串行执行底层算力抓取与顶层对话抓取。强制运行 `python analyze_insights_v4.py --period <PERIOD> --extract-only` 和 `python ../scripts/system_retro.py`。
2. **基因解码**: 阅读输出的 metric 文件，提取至少 1 个“核心协作摩擦模式”（例如：用户描述不清导致频繁重试，或是某技能设计缺陷）。
3. **资产沉淀**: 必须生成一个立等可用的 Prompt 模板、Checklist 或者自动化技能候选。
4. **验证门**: 如果存在 `validate_agent_audit.py`，必须通过审计校验。最终报告必须提供“Top 1 战略调整”。

## 1. 交付标准 (Delivery Standard)
无论是 Mode 1 还是 Mode 2，最终的 Markdown 报告必须通过 `write_file` 物理落盘到审计目录：
`C:\Users\shich\.gemini\MEMORY\skill_audit\audit_logs\mentat-collaboration-audit-[YYYY-MM-DD].md`。

严禁仅仅在对话框中打出文本而不落盘。

## 2. Telemetry (Mandatory)
完成报告落盘后，使用 `write_file` 将自身执行的元数据写入：
`C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
格式示例：`{"skill_name": "mentat-collaboration-audit", "status": "success", "mode": "[Telemetry|Interaction]"}`

## 3. 历史失效先验 (NLAH Gotchas)
- **[CRITICAL]** NEVER skip the script execution step. You MUST read real telemetry data. Do NOT hallucinate metrics.
- `IF [Action == "Output Findings"] THEN [Require Data Evidence from Scripts]`
- `IF [Mode == "Interaction"] THEN [Require 1 Workflow Asset (Prompt/Checklist)] AND [Require 1 Next-Cycle Action]`
- `IF [Action == "File Persistence"] THEN [Require Path starts_with "~/.gemini/" OR "C:\Users\shich\.gemini"]`
