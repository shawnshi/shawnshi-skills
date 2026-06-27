---
name: cognitive-logic-adversary
version: 9.0.0
tier: action-allowed
description: '执行饱和逻辑攻击以识别单点故障(SPOF)，并将脆弱假设重构为防御性钢人策略。禁止用于撰写附和性赞美报告、常规内容摘要或非对抗性文本编辑。'
triggers: ["寻找逻辑漏洞", "审核方案风险", "模拟专家辩论", "发起红队攻击", "执行压力测试", "质疑我的决定", "寻找方案盲点"]
---

<strategy-gene>
Keywords: 逻辑漏洞, 红队攻击, SPOF 审计, 钢人重构
Summary: 通过饱和逻辑攻击识别致命单点故障，重构为防御性钢人方案。
Strategy:
1. 1. 沙盒对抗：冲突博弈需在物理文件中执行，防止 Context 塌陷。
2. 2. 威胁假设：直接锁定最可能导致失败的 3 个致命单点 (SPOF)。
3. 3. 钢人重构：为最脆弱论点提供更强大的防御版本。
AVOID: 赞美或附和方案；使用主观形容词描述风险；未侦察便开启博弈。
</strategy-gene>

# Logic Adversary V9.0 (The Steelmen Forge)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `call_mcp_tool` (调用 vector-lake 检索历史盲点)
2. `write_to_file` (创建物理沙盒与 00_init 议题)
3. `invoke_subagent` (委托对抗代理进行沙盒博弈)
4. `run_command` (可选：执行 game_resolver.py 计算帕累托前沿与博弈共识)
5. `write_to_file` (子代理碎片化写入与重构报告)
6. `run_command` (session_merger.py 合并碎片)
7. `invoke_subagent` (委托 Vector-Lake-Ingestor 进行异步入湖)

## 0. 核心调度约束 (Global State Machine)
> **[全局协议]**：严格按 Phase 0 至 Phase 4 顺序执行。跨越 Phase 时，需在对话以 `[System State: Moving to Phase X]` 声明。

### Sub-agent Delegation Protocol (Mandatory Sandboxing)
- 为防止主上下文衰退，对抗博弈约束已左移，需委托子代理执行。
1. **Arena Creation**: 博弈前，使用 `write_to_file` 将议题与人设写入物理沙盒 `C:\Users\shich\.gemini\tmp\playgrounds\Arena_Packet_[TIMESTAMP].md`。
2. **Delegation**: 调用 `invoke_subagent` (指定 `TypeName: "self"`) 唤醒独立代理读取沙盒、执行辩论并产出 `Vulnerability_Autopsy_Report.md`。
3. **Suspension**: 主代理挂起，仅在子代理完成后读取 Autopsy 报告。

---

## 1. 核心流程与架构 (The Protocol)
### Phase 0: Reconnaissance (语义侦察) [Mode: PLANNING]
1.  **任务**：在开启对抗前，优先通过 `call_mcp_tool` 调度 `vector-lake-mcp` (或原生检索工具) 检索 `MEMORY/` 中相关的历史失败案例、逻辑缺陷记录。
2.  **情报汇总**：将检索到的核心情报以【历史逻辑盲点】的形式呈现，防止讨论陷入已知的平庸。

### Phase 1: Decomposition & Hypothesis (议题拆解与假设) [Mode: PLANNING]
1.  **威胁假设 (IVH)**：基于方案，列出最可能导致失败的 3 个“致命单点” (SPOF)。
2.  **模式路由**：根据用户需求选择作战模式：
    - **Quick (速查)**: 单轮 4 代理。
    - **Debate (共识)**: 多轮 4-7 代理。
    - **Validation (验证)**: 备选方案对比。
    - **Attack (红队)**: 32 代理饱和攻击。
3.  **写入节点**：使用原生 `write_to_file` 将议题原子化断言写入 `C:\Users\shich\.gemini\MEMORY\roundtable\workspace_adversary_{议题关键词}_{date}\00_init.md` (目录会自动创建)。
4.  **门禁确认**：调用 `ask_question` 工具获取用户的启动确认。

### Phase 2: Adversarial Engagement (博弈与 Engage) [Mode: EXECUTION]
1.  **执行 Workflow**：运行选定的 `Workflows/*.md`。
2.  **碎片化落盘**：每一轮质疑与博弈结束后，直接使用原生 `write_to_file` 将内容写入工作区内的 `01_round1.md`, `02_round2.md` 等碎片文件。
3.  **证据织网**：质疑必须引用 `references/philosophy.md` 中的公理/谬误。

### Phase 3: Reconstruction (钢人重构) [Mode: EXECUTION]
1.  **冲突存证**：记录分歧点。若处于 Validation (备选方案验证) 模式，需先通过 `write_to_file` 将代理打分导出为 `debate_results.json`。
2.  **博弈解析 (Game Theory Resolve)**：调用 `run_command` 执行：
    ```powershell
    $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-logic-adversary\scripts\game_resolver.py" "C:\Users\shich\.gemini\MEMORY\roundtable\workspace_adversary_{议题关键词}_{date}\debate_results.json" --pareto --chart
    ```
    获取稳定性得分最高的最优共识解。
3.  **Steelmen Recommendations**：系统必须为方案中最脆弱的论点构建一个在逻辑上更强大的防御性版本（钢人版本），并给出物理修复建议。
4.  **写入报告**：使用原生 `write_to_file` 将重构建议与博弈图表写入 `98_reconstruction.md`。

### Phase 4: Archival & Sync (归档与同步) [Mode: EXECUTION]
1.  **物理合并**：调用原生的 `run_command` 工具执行以下命令合并碎片：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-logic-adversary\scripts\session_merger.py" "工作区绝对路径" "目标文件绝对路径"
   ```
2.  **Lake Sync (异步入湖)**：提取含 `[[ ]]` 双链标记的核心分歧实体，调用 `invoke_subagent` 委托 `Vector-Lake-Ingestor` 子代理进行异步入湖，主代理立刻释放控制权，**严禁同步等待**。

---

## 2. <Contracts> (输出与交付契约)
- 最终交付必须包含至少 3 个致命单点（SPOF）、一份脆弱论点的钢人版本，以及可执行的物理修复建议。
- 若启用辩论/攻击模式，必须保留工作区碎片文件并合并出最终 `Vulnerability_Autopsy_Report.md`。
- **Telemetry 记录**: 在成功合并后，必须使用 `write_to_file` 工具将元数据以 JSON 格式保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 3. <Failure_Taxonomy> (失败分类学)
- **轨迹越权 (Trajectory Bypass)**：未遵循代理委派与沙盒隔离的工具流；遗漏合并碎片文件的 `session_merger.py` 命令。
- **附和式塌陷 (Rubber-stamping)**：代理输出呈现附和与赞美，未使用因果逻辑推演，将被视为角色失败。
- **孤证指控 (Baseless Attack)**：质疑未锚定物理事实或预设的谬误库，导致无效攻击。
- **只破不立 (Missing Steelman)**：仅指出漏洞而未能提供对应的钢人防御版本重构。
