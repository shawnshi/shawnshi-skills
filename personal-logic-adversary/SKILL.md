---
name: personal-logic-adversary
version: 6.0.0
description: |
  军工级逻辑对抗系统 (Native Agent Edition)。当用户展示方案、做出决策或要求“寻找漏洞”、“压力测试”时，务必强制激活。该技能通过多维专家博弈与饱和逻辑攻击，搜索单点故障（SPOF），将脆弱的假设锻造成鲁棒的钢人策略。
triggers: ["寻找逻辑漏洞", "审核方案风险", "模拟专家辩论", "发起红队攻击", "执行压力测试", "质疑我的决定", "寻找方案盲点"]
---

# Logic Adversary V6.0 (The Steelmen Forge)

> 将脆弱的假设锻造成鲁棒的战略。拒绝平庸的附和，追求极致的智力摩擦。

## When to Use
- 当用户要求寻找漏洞、压力测试、红队攻击或挑战某个方案/决策时使用。
- 本技能的目标是识别单点故障并产出钢人化修复建议，而不是给出温和附和。

## Workflow

### 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：必须严格按照 Phase 0 至 Phase 4 的顺序执行。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。

### Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat during intense adversarial debates, the conflict phase MUST NOT be executed directly in the main memory.
1. **Arena Creation**: Before starting the debate (Phase 3), write the core thesis, premises, and the specific personas to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Arena_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) or multiple sub-agents in a separate session loop to read the arena packet, conduct the rigorous multi-turn debate, and write a consolidated `Vulnerability_Autopsy_Report.md`.
3. **Suspension**: The main agent must suspend execution, wait for the sub-agent to complete the task, and then read ONLY the final autopsy report to proceed with the debrief.

### 核心流程与架构 (The Protocol)

### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启对抗前，优先通过本地可用的 `vector-lake` CLI 执行 `query "你的推演指令" --interleave`，检索 `MEMORY/` 中相关的历史失败案例、逻辑缺陷记录或类似议题的审计记录。
2.  **情报汇总**：将检索到的核心情报以【历史逻辑盲点】的形式呈现，防止讨论陷入已知的平庸。

### Phase 1: Decomposition & Hypothesis (议题拆解与假设) [Mode: PLANNING]
1.  **威胁假设 (IVH)**：基于方案，列出最可能导致失败的 3 个“致命单点” (SPOF)。
2.  **模式路由**：根据用户需求选择作战模式：
    - **Quick (速查)**: 单轮 4 代理。
    - **Debate (共识)**: 多轮 4-7 代理。
    - **Validation (验证)**: 备选方案对比。
    - **Attack (红队)**: 32 代理饱和攻击。
3.  **工作区初始化**：使用 `run_shell_command` 创建专属目录 `C:\Users\shich\.gemini\MEMORY\roundtable\workspace_adversary_{议题关键词}_{date}\`。
4.  **写入节点**：使用 `write_file` 写入 `00_init.md`，包含议题原子化断言（Assertions）与承重墙识别。调用 `ask_user` 获取启动确认。

### Phase 2: Adversarial Engagement (博弈与 Engage) [Mode: EXECUTION]
1.  **执行 Workflow**：运行选定的 `Workflows/*.md`。
2.  **碎片化落盘**：每一轮质疑与博弈结束后，直接使用 `write_file` 将内容写入 `01_round1.md`, `02_round2.md`... 等碎片文件。
3.  **证据织网**：质疑必须引用 `references/philosophy.md` 中的公理/谬误。

### Phase 3: Reconstruction (钢人重构) [Mode: EXECUTION]
1.  **冲突存证**：记录分歧点。
2.  **Steelmen Recommendations**：系统必须为方案中最脆弱的论点构建一个在逻辑上更强大的防御性版本（钢人版本），并给出物理修复建议。
3.  **写入报告**：使用 `write_file` 将重构建议写入 `98_reconstruction.md`。

### Phase 4: Archival & Sync (归档与同步) [Mode: EXECUTION]
1.  **物理合并**：使用 `run_shell_command` 执行 `python C:\Users\shich\.gemini\skills\personal-logic-adversary\scripts\session_merger.py "工作区绝对路径" "目标文件绝对路径"`。
2.  **Telemetry (Mandatory)**：记录元数据至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
3.  **Lake Sync**：触发向量湖同步。

## Resources
- `scripts/session_merger.py`
- `references/philosophy.md`
- `Workflows/*.md`
- `C:\Users\shich\.gemini\tmp\playgrounds\Arena_Packet_[TIMESTAMP].md`
- `C:\Users\shich\.gemini\MEMORY\roundtable\workspace_adversary_{议题关键词}_{date}\`

## Failure Modes
- ❌ **严禁谄媚**：代理严禁赞美方案，必须保持“手术刀式”的冷峻。
- ❌ **反对模式塌陷**：若结论高度一致，强制引入“魔鬼代言人 (Devil's Advocate)”。
- ✅ **动词驱动**：输出严禁使用形容词，必须基于因果逻辑。
- ✅ **物理证据**：所有质疑必须锚定 `philosophy.md` 或外部物理事实。
- `IF [Action == "Start Debate"] THEN [Halt if Input contains "Social pleasantries"] AND [Require Direct Logical Conflict]`
- `IF [Action == "Execute Script"] THEN [Require Path == "Absolute Path (e.g., C:/Users/shich/.gemini/...)"]`
- `IF [Action == "Final Audit"] THEN [Halt if Output lacks "Defense/Steelman Recommendations"]`

## Output Contract
- 最终交付必须包含至少 3 个致命单点（SPOF）、一份脆弱论点的钢人版本，以及可执行的物理修复建议。
- 若启用辩论/攻击模式，必须保留工作区碎片文件并合并出最终 `Vulnerability_Autopsy_Report.md`。

## Telemetry
- 使用 `write_file` 记录元数据至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。

## Legacy Notes
- ❌ **严禁谄媚**：代理严禁赞美方案，必须保持“手术刀式”的冷峻。
- ❌ **反对模式塌陷**：若结论高度一致，强制引入“魔鬼代言人 (Devil's Advocate)”。
- ✅ **动词驱动**：输出严禁使用形容词，必须基于因果逻辑。
- ✅ **物理证据**：所有质疑必须锚定 `philosophy.md` 或外部物理事实。

## 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Start Debate"] THEN [Halt if Input contains "Social pleasantries"] AND [Require Direct Logical Conflict]`
- `IF [Action == "Execute Script"] THEN [Require Path == "Absolute Path (e.g., C:/Users/shich/.gemini/...)"]`
- `IF [Action == "Final Audit"] THEN [Halt if Output lacks "Defense/Steelman Recommendations"]`

---
*Updated to V6.0 | System State: Locked*
