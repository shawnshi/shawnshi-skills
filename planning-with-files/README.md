# planning-with-files
<!-- Input: Complex multi-step task descriptions. -->
<!-- Output: task_plan.md, findings.md, progress.md. -->
<!-- Pos: Orchestration Layer (Working Memory on Disk). -->
<!-- Maintenance Protocol: Update 'scripts/check-complete.sh' for phase verification logic. -->

## 核心功能
实现“Manus 式”磁盘持久化工作记忆。通过在项目根目录维护三个核心 Markdown 文件，确保复杂任务在长周期执行中的一致性与可追溯性。

## 战略契约
1. **磁盘优先**: 任何重要的发现或决策必须立即记录到 `findings.md`，严禁仅依靠上下文窗口。
2. **读前决策**: 在执行重大变更前，必须重读 `task_plan.md` 以刷新目标感知，防止语义漂移。
3. **三击回退**: 遇到连续 3 次失败时，必须停止执行，向用户汇报错误矩阵并重新评估方案。
