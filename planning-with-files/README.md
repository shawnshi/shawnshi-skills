# Planning with Files: 磁盘持久化记忆

<!-- 
@Input: Complex Tasks (>5 steps), Research Goals, Errors
@Output: task_plan.md, findings.md, progress.md
@Pos: [ACE Layer: Orchestration] | [MSL Segment: Meta-Management]
@Maintenance: Regular cleanup of stale plan files in projects.
@Axioms: Disk Over RAM | Read Before Decide | 3-Strike Error Protocol
-->

> **核心内核**：抗干扰的任务协同调度器。实现“Manus 式”工作记忆持久化，确保复杂任务在长周期执行中的一致性。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 任务状态管理引擎，负责将易失的上下文（RAM）实时落地为物理文件（Disk）。
- **反向定义**: 它不是一个简单的 TODO 列表，而是一个具备容错能力的动态执行地图。
- **费曼比喻**: 就像是在一个风暴中的航海日记，无论环境多么混乱，只要日记在，你就知道船在哪、要去哪、漏了几个洞。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 管理“执行状态”、“研究发现”、“错误日志”等元管理实体。
- **ACE 角色**: 作为系统的 **Orchestrator (编排者)**，充当系统的“外部主板”。

## 2. 逻辑机制 (Mechanism)
- [Plan Initialization] -> [Discovery Logging] -> [Status Tracking] -> [Error Diagnosis]

## 3. 策略协议 (Strategic Protocols)
- **磁盘优先 (Disk-First)**：任何重大发现必须实时落地为 findings.md，严禁仅依靠易失性上下文。
- **读前决策**：执行重大变更前必须回读计划文件，强制对齐目标。
- **熔断机制**：遭遇连续 3 次逻辑失败时强制停机，重新评估错误矩阵。
