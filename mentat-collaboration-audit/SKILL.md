---
name: mentat-collaboration-audit
version: 11.2.0
description: '系统与协作联合审计管线。当用户表达“复盘”、“效率低”、“查看Token消耗”、“系统绕弯路”或要求执行 Retro/月度交互洞察时触发。统一收口系统底层算力损耗与人机协作摩擦的联合审计。'
triggers: ["复盘", "效率低", "系统绕弯路", "量化复盘", "执行 Retro", "分析技能耗时", "系统交互报告", "查看 Token 消耗"]
---

<strategy-gene>
Keywords: 系统复盘, Token 消耗, 协作摩擦, 联合审计, 自动固化
Summary: 打通底层硬件算力损耗与顶层人机协作摩擦，基于客观遥测数据生成诊断报告，并具备基于死锁数据的自动物理规则挂载能力。
Strategy:
1. 识别并声明模式：进入 [System State: Mode 1 (Telemetry)] 或 [System State: Mode 2 (Interaction)]。
2. 调用 Python 探针获取遥测数据（必须前置 UTF-8 编码锁）。
3. 使用 `view_file` 严格读取 `references/SCHEMA.md` 并遵循其契约。
4. 在交互复盘中提取摩擦模式，给出 Checklist 并落盘。
5. （可选）执行自我篡改：根据 `auto_constraint_writeback` 主动调用 `write_to_file` 挂载系统防御围栏。
AVOID: 禁止没有数据依据的归因；禁止不输出具体行动指南的纯概念复盘；禁止使用虚伪客套的套话。
</strategy-gene>

# Mentat Collaboration Audit (联合审计管线 V11.2 Native)

这是系统最高级别的防线。你必须像一台冷酷的心电图监护仪，通过客观遥测数据宣判系统熵增，并有权挂载系统防御围栏。

## When to Use

- **Mode 1: Telemetry (硬核遥测模式)**：用户仅要求查看 Token、算力损耗、错误率或请求系统耗时等硬指标。
- **Mode 2: Interaction (深度协作模式)**：用户反映效率低下、协作阻力高，或要求完整的周/月度交互复盘。

## Workflow

在执行的第一步，你必须在回复中显式声明：`[System State: Mode X]`。

### Mode 1: Telemetry
1. **带锁调用探针**: 强制使用原生 `run_command` 调用外部脚本采集数据，**必须**使用绝对物理路径：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\system_retro.py"
   ```
2. **生成报告**: 输出包含 [全局算力损耗]、[异常节点狙击] 的冰冷数据报告。

### Mode 2: Interaction
1. **并发数据摄取 (Parallel Tool Calling)**: 使用 `run_command` 在**单次回合内并发执行**抓取底层与顶层数据（注意全绝对路径），严禁串行等待：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\scripts\analyze_insights_v4.py" --period <PERIOD> --extract-only --drop-noise
   ```
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\system_retro.py"
   ```
2. **Mentat内观日志对齐**: 使用 `run_command` 或 `view_file` 获取 `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\` 目录下对应时间范围内的 `.md` 内观回顾（如 OODA 日志）。
3. **原生结构化推演**: 利用 Gemini Pro 3.1 的原生 Structured Output 能力，严格依据 `references/SCHEMA.md` 生成包含“核心协作摩擦模式”、“教练解读”和“工作流资产”的 JSON 数据包，并使用 `write_to_file` 严格落盘到当前会话的安全沙盒：`<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json`。
4. **验证与渲染**: 必须依次运行：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\scripts\validate_agent_audit.py" "<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json"
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\scripts\analyze_insights_v4.py" --period <PERIOD> --render --agent-file "<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json"
   ```
5. **物理围栏挂载 (Active Constraint Enforcement)**：若 JSON 中包含有效的 `auto_constraint_writeback` 提议，必须主动调用 `multi_replace_file_content` 原子修改目标文件。若遇到死锁，记录至 `rejected_edits.jsonl` 以免反复受阻。

## Resources

- **核心数据泵引擎**: `scripts/core/engine.py`
- **顶层数据提取/渲染器**: `scripts/analyze_insights_v4.py`
- **JSON 校验器**: `scripts/validate_agent_audit.py`
- **统一 JSON 输出 Schema 契约**: `references/SCHEMA.md`

## Output Contract

- **落盘报告**: 无论是 Mode 1 还是 Mode 2，最终的 Markdown 报告必须通过 `write_to_file` 物理落盘到审计目录：`C:\Users\shich\.gemini\MEMORY\skill_audit\audit_logs\mentat-collaboration-audit-[YYYY-MM-DD].md`。
- **交付链接契约**: 报告落盘后，主代理必须通过聊天框向用户输出可点击的 Markdown 链接（例如：`[系统协作审计报告](file:///C:/Users/shich/.gemini/MEMORY/skill_audit/audit_logs/...)`）。
- **无幻觉验证**: NEVER skip the script execution step. You MUST read real telemetry data. Do NOT hallucinate metrics. `IF [Action == "Output Findings"] THEN [Require Data Evidence from Scripts]`
- **资产输出**: `IF [Mode == "Interaction"] THEN [Require 1 Workflow Asset (Prompt/Checklist)] AND [Require 1 Next-Cycle Action]`

## Telemetry

- **元数据录入**: 为了规避全局死锁，报告落盘后必须使用 `write_to_file` 将执行状态写入隔离沙盒：`<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`。
  (格式：`{"skill_name": "mentat-collaboration-audit", "status": "success", "mode": "[Telemetry|Interaction]"}`)

## Failure Modes

- **路径死锁 (Pathing Deadlock)**：所有的工具调用、脚本执行和写文件动作，**必须采用绝对物理路径**。严禁将 JSON 临时文件写在全局目录，必须严格写在 `<appDataDir>\brain\<conversation-id>\scratch\`。
- **工具幻觉 (Tool Hallucination)**：严禁使用旧版 `write_file`，必须一律使用合法的 `write_to_file`。
- **脚本失效 / 找不到命令**：如果探针崩溃，必须主动寻找 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\` 下近期缓存进行替代分析，并打出警告 `> [!WARNING] Telemetry scripts failed.`。
- **Schema 验证失败与熔断自愈 (Critic Subagent)**：如果 `validate_agent_audit.py` 失败超过 2 次，禁止主循环强攻。必须使用 `invoke_subagent` 拉起一个 Failure Critic Subagent 独立诊断报错日志，提取单点突变建议后，再由主代理进行原子修复。
- **物理挂载死锁**：若尝试修改 `GEMINI.md` 等遭拦截，必须停止强攻，将其转为纯文本建议，并写入 `rejected_edits.jsonl` 避免二次死锁。
