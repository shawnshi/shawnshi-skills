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

## 1. 核心调度与工作流 (Mode Dispatch & Workflow)

在执行的第一步，你必须在回复中显式声明：`[System State: Mode X]`。

### Mode 1: Telemetry (硬核遥测模式)
**适用场景**：用户仅要求查看 Token、算力损耗、错误率或请求系统耗时等硬指标。
1. **带锁调用探针**: 强制使用原生 `run_command` 调用外部脚本采集数据，**必须**使用绝对物理路径：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\system_retro.py"
   ```
2. **生成报告**: 输出包含 [全局算力损耗]、[异常节点狙击] 的冰冷数据报告。

### Mode 2: Interaction (深度协作模式)
**适用场景**：用户反映效率低下、协作阻力高，或要求完整的周/月度交互复盘。
1. **并行数据摄取**: 使用 `run_command` 并发或串行抓取底层与顶层数据（注意全绝对路径）：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\analyze_insights_v4.py" --period <PERIOD> --extract-only --drop-noise
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\system_retro.py"
   ```
2. **Schema 注入**: 必须使用原生 `view_file` 读取 `C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\references\SCHEMA.md` 获取完整输出 JSON 格式模板。
3. **基因解码**: 根据输出数据（含 Friction_Type 判定），生成“核心协作摩擦模式”、“教练解读”和“工作流资产”的 JSON 数据包，并使用 `write_to_file` 严格落盘到当前会话的安全沙盒：`<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json`，防止多会话并发污染。
4. **验证与渲染**: 必须依次运行：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\validate_agent_audit.py" "<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json"
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-collaboration-audit\analyze_insights_v4.py" --period <PERIOD> --render --agent-file "<appDataDir>\brain\<conversation-id>\scratch\mentat_audit_draft.json"
   ```
5. **物理围栏挂载 (Active Constraint Enforcement)**：若 JSON 中包含有效的 `auto_constraint_writeback` 提议，你必须主动调用 `multi_replace_file_content` 工具进行原子修改，将建议的规则安全地写入指定的 `target_file`（如 `GEMINI.md` 或 `pai/` 文件），禁止使用 `write_to_file` 盲目全量覆盖系统核心文件，并在最终回复中宣告挂载成功。

## 2. <Contracts> (输出与交付契约)

- **落盘报告**: 无论是 Mode 1 还是 Mode 2，最终的 Markdown 报告必须通过 `write_to_file` 物理落盘到审计目录：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\audit_logs\mentat-collaboration-audit-[YYYY-MM-DD].md`。严禁仅仅在对话框中打出文本而不落盘。
- **交付链接契约**: 报告落盘后，主代理必须通过聊天框向用户输出可点击的 Markdown 链接（例如：`[系统协作审计报告](file:///C:/Users/shich/.gemini/MEMORY/skill_audit/audit_logs/...)`）。
- **Telemetry 元数据录入**: 为了规避全局死锁，报告落盘后必须使用 `write_to_file` 将执行状态写入隔离沙盒：`<appDataDir>\brain\<conversation-id>\scratch\telemetry.json`。
  (格式：`{"skill_name": "mentat-collaboration-audit", "status": "success", "mode": "[Telemetry|Interaction]"}`)
- **无幻觉验证**: NEVER skip the script execution step. You MUST read real telemetry data. Do NOT hallucinate metrics. `IF [Action == "Output Findings"] THEN [Require Data Evidence from Scripts]`
- **资产输出**: `IF [Mode == "Interaction"] THEN [Require 1 Workflow Asset (Prompt/Checklist)] AND [Require 1 Next-Cycle Action]`

## 3. <Failure_Taxonomy> (失败分类学)

- **路径死锁 (Pathing Deadlock)**：严禁使用相对路径 `../` 或缺少 `config\` 层级的错误路径。所有的工具调用、脚本执行和写文件动作，**必须采用绝对物理路径**。严禁将 JSON 临时文件写在技能目录或全局目录，必须严格写在会话隔离区 `<appDataDir>\brain\<conversation-id>\scratch\`。
- **工具幻觉 (Tool Hallucination)**：严禁使用旧版 `write_file`，必须一律使用合法的 `write_to_file`。
- **脚本失效 / 找不到命令**：如果探针脚本崩溃或不可用，禁止中断流程。必须主动寻找 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\` 目录下的近期 JSON 抽样替代分析，并在报告首行打出高危警报 `> [!WARNING] Telemetry scripts failed. Used historical cache.`
- **Schema 验证失败**：如果 `validate_agent_audit.py` 返回失败，大模型必须根据报错信息立即修正落盘的 JSON 文件，重新执行验证直至通过。
- **物理挂载死锁**：若尝试修改 `GEMINI.md` 等核心系统文件遭到拦截或权限拒绝，必须停止强攻，将规则转换为纯文本建议告知用户，由用户手动决定。
