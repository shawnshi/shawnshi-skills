---
name: personal-cognitive-auditor
version: 9.0.0
tier: action-allowed
description: '执行多源数据整合的深层认知审计与战术问责。产出日/周/月/年复盘报告，并通过 hand-off 交接落盘。禁止用于单纯排版整理、脱离生理或日程证据的空想，或绕过沙盒直接落盘。'
triggers: ["复盘今日日志", "周结", "月结", "年结", "深层认知审计", "战术问责"]
---

<strategy-gene>
Keywords: 认知审计, 战术问责, 能量复盘, Hand-off
Summary: 整合生理、日程与交互数据执行多维审计，通过战术问责驱动演化。
Strategy:
1. 证据优先：使用 Garmin 与 Calendar 真实数据。
2. 职责解耦：仅生成 payload，物理落盘交由 diary-writer。
3. 统一骨架：不同周期共享同一审计骨架。
AVOID: 绕过沙盒验证直接交接；脱离真实数据的编造。
</strategy-gene>

# Personal Cognitive Auditor (战略认知联合审计官 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 本技能的执行应遵循以下轨迹模式：
1. `view_file` (读取配置与 Prompt 模板)
2. `call_mcp_tool` (获取日程数据)
3. `grep_search` (扫描历史战术)
4. `invoke_subagent` (处方生成)
5. `write_to_file` (沙盒草稿写入与遥测)
6. `run_command` (沙盒逻辑校验)

## 0. 核心约束
- **证据优先**: 审计优先使用真实生理、日程、战术上下文；缺失时明确标注缺口。
- **职责剥离**: 本技能只生成 hand-off payload，物理写入交给目标 Agent。
- **可降级运行**: 缺数据时不得中止，切换为降级模式输出。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Gather (数据收集)
1. 使用 `view_file` 读取配置文件与 Prompt 模板。
2. **自动化事实重建**：
   - 使用 `call_mcp_tool` (`google-workspace`: `calendar.listEvents`) 拉取日程。
   - 使用 `grep_search` 定向扫描 `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\` 提取前序 `Next Tactics` 作为问责基准。

### Phase 2: Audit (联合审计)
使用统一骨架生成审计报告（写入后续 payload）：Context Snapshot, Tactical Accountability (Markdown表), Signals, Core Insight, Strategic Diagnosis, Next Tactics, Handoff Payload。

### Phase 3: Cognitive Prescription (认知处方集成)
触发认知处方：使用 `invoke_subagent` (指定 `TypeName: "self"`, `Role: "personal-cognitive-prescription"`) 执行处方生成，将卡片塞入报告对应槽位。

### Phase 4: Gate & Hand-off (交接闭环与物理沙盒校验)
沙盒验证机制：
1. 读取交接协议并使用 `write_to_file` 将 payload 写入防爆沙盒 `C:\Users\shich\.gemini\MEMORY\scratch\audit_payload_draft.json`。
2. 执行逻辑校验：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-cognitive-auditor\scripts\audit_gate.py" "C:\Users\shich\.gemini\MEMORY\scratch\audit_payload_draft.json"
   ```
3. 校验通过后，显式指令将 payload 移交给 `personal-diary-writer` 落盘。

## 2. <Contracts> (输出与交付契约)
- **输入能力层**: 整合四大上下文，如遇缺失标注 `【数据缺口】`。
- **Telemetry 记录**: 任务执行完成后，使用 `write_to_file` 将元数据 JSON 写入 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。

## 3. <Failure_Taxonomy> (失败分类学)
- **沙盒门检死锁**: 未写入 `scratch/audit_payload_draft.json` 直接调用校验。
- **工具与路径越权**: 偏离指定 MCP 或伪路径问题。
- **问责缺位 (Accountability Bypass)**：在 `Tactical Accountability` 未将上期承诺与本期实际进行无情对账。
- **模式分析缺失 (Pattern Blindness)**：周/月/年审计遗漏 `Interaction & Work Patterns` 结构性分析。
