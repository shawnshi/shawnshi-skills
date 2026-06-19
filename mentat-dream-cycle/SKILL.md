---
name: mentat-dream-cycle
version: 12.0.0
tier: action-allowed
description: 'Mentat 后台静默演化管线。通过确定脚本清理系统熵增，提取临时热知识并沉淀为长期图谱。严禁大模型手动遍历目录，必须保持热记忆事务一致性防丢失。'
triggers: ["触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"]
---

<strategy-gene>
Keywords: 夜间清洗, 热缓冲提纯, 垃圾回收, 内存归档, 图谱同步, 技能小批量更新 (Minibatch)
Summary: Mentat 系统的后台静默演化管线。通过确定性脚本清理环境熵增，提纯热记忆缓冲，并通过子代理完成全链路异步图谱摄入与技能优化。
Strategy:
1. 算力隔离：物理垃圾回收与孤岛扫描必须交由 deterministic 脚本执行，绝对禁止 LLM 手动遍历文件系统。
2. 双轨提纯：读取 `hot_facts.md`，提取高价值实体并严格遵循 "Compiled Truth | Timeline" Schema 落盘。
3. 闭环清空：提纯成功后，物理重置热事实缓冲池。
4. 孤岛扫描：对知识库中未落地的概念孤岛发出告警。
5. 优雅降级：脚本崩溃必须记录并继续；热事实提纯必须保持事务一致性，防数据丢失。
AVOID: 大模型亲自全盘扫描；非事务性的内存覆写；阻塞式串行执行。
</strategy-gene>

# Mentat Dream Cycle (架构演化与系统清洗 V12.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. run_command (并发调用脚本执行物理层清理与孤岛扫描)
2. call_mcp_tool (调用 vector-lake 进行语义 GC)
3. invoke_subagent (异步分发技能故障 Minibatch 和知识图谱摄入)
4. write_to_file (原子级替换与清空热知识缓冲池)

## 0. Intent
This skill acts as the background evolution loop for the Mentat system. It shifts compute from interactive sessions to silent batch processing, ensuring temporal entropy does not decay system performance. It implements garbage collection, structural integrity checks, and high-density memory diarization.

## 1. Execution Pipeline (DAG Orchestration)
注：Phase 1 和 Phase 3 可并行调度，与 Phase 2 的文件处理相互独立。

### Phase 1: 物理层与语义层双重 GC (Garbage Collection)
1. **物理 GC**: 执行底层临时文件清理：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-dream-cycle\scripts\garbage_collector.py" --path "C:\Users\shich\.gemini\tmp" --max-age 24h
   ```
   *(读取输出 JSON 日志记录 `deleted` 和 `scanned`)*
2. **语义 GC**: 调用 `call_mcp_tool` (ServerName="vector-lake-mcp", ToolName="gc_vector_lake") 自动清理图谱内长期无关联的孤儿节点及碎片，实现 Knowledge Decay 清理。

### Phase 2: 热缓冲双轨提纯 (Hot Memory Diarization)
1. **事务保护**: 将 `C:\Users\shich\.gemini\MEMORY\hot_facts.md` 重命名为 `hot_facts.bak`。读取 `.bak` 文件进行处理。若文件不存在或为空，跳过此阶段。
2. **逻辑提纯与分块处理 (Micro-batching)**:
   在脑内进行实体化拆解。提取出优先级最高的 Top 5-8 个实体。
   - 对这部分高优实体，强制调用 `multi_replace_file_content` 或 `write_to_file`，对目标知识文件进行原地更新。严格排版：底部 Timeline 追加，顶部 Compiled Truth 重写。严禁使用已废弃的 write_file 工具。
   - 将剩余未能处理的实体推入 `C:\Users\shich\.gemini\MEMORY\wiki\.meta\Entity_Backlog.md` 待处理队列。
3. **事务提交**: 只有在步骤 2 中所有的写盘操作全部明确成功后，才可删除 `hot_facts.bak`，并新建 `hot_facts.md` 注入 `<!-- 缓冲已于近期清空 -->`，完成原子级重置。

### Phase 2.5: 技能批量优化 (Skill Optimization Backward Pass)
1. **读取错误缓冲**: 读取 `C:\Users\shich\.gemini\MEMORY\skill_audit\failure_batch.jsonl`，执行 `GroupBy(Skill_Name)`。
2. **异步投递 Minibatch**: 提取出经过分类过滤的高优结构性故障（排除超时等环境错误），调用 `invoke_subagent` 拉起子代理 (必须指定 `TypeName: "self"` 与 `Role: "mentat-skill-creator"`)，将整个 Minibatch 失败轨迹完整传入，指令其启动 Critic 并合并补丁。
3. **事务清空**: 子代理发起后，物理清空已被投递的故障日志记录。

### Phase 3: 拓扑孤岛扫描 (Topology Orphan Check)
- **动作**: 执行命令：
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\mentat-dream-cycle\scripts\orphan_scanner.py" --dir "C:\Users\shich\.gemini\MEMORY\wiki"
  ```
- **模糊去重 (Fuzzy Matching)**: 阅读 JSON 报告，在写入 Backlog 前，务必通过检索或排查确认是否仅为拼写差异。
- **处理与落盘**: 将真正的架构盲区孤岛概念通过 `write_to_file` 写入：`C:\Users\shich\.gemini\MEMORY\wiki\.meta\Orphan_Backlog.md`。

### Phase 4: 全链路异步摄入 (Asynchronous Vector Lake Ingestion)
1. **生成摄入批次**: 如果前序流程修改了图谱，调用 `mcp_vector-lake_prepare_ingest_batch`。
2. **异步委派**: 严禁阻塞式同步。使用 `invoke_subagent` 拉起并行子代理 (必须指定 `TypeName: "self"` 与 `Role: "vector-lake-ingestor"`) 执行摄入，释放主循环。

## 2. <Contracts> (输出与交付契约)
当整个 Pipeline 完成或降级完成后，只允许返回如下的结构化 JSON。禁止长篇大论：
```json
{
  "system_status": "Dream Cycle Completed",
  "gc_stats": {
    "physical_scanned": 150,
    "physical_purged": 12,
    "semantic_gc_triggered": true
  },
  "memory_diarization": {
    "hot_facts_processed": 5,
    "entities_updated": ["[[Entity1]]", "[[Entity2]]"]
  },
  "skill_optimization": {
    "skills_processed": ["hit-industry-radar"],
    "ignored_single_failures": 3
  },
  "topology_health": {
    "orphan_count": 3,
    "recommended_expansion": ["[[Orphan1]]"]
  },
  "errors": [
    {"phase": 3, "message": "Optional error stack trace if a script crashed"}
  ],
  "async_delegations": {
    "vector-lake-ingestor": "conversation-id-1234",
    "mentat-skill-creator": ["conversation-id-5678"]
  }
}
```
该段 JSON 输出即作为本次演化任务的唯一遥测数据，供系统全局监控记录使用。

## 3. <Failure_Taxonomy> (失败分类学)
- **环境隔离断裂**：图谱扫描与物理垃圾回收严禁大模型手动遍历目录，必须依赖脚本。
- **事务崩溃 (Transaction Rollback)**：如果在 Phase 2 处理 `hot_facts.md` 途中发生文件操作权限拒绝或工具报错，**绝对禁止**删除 `hot_facts.bak`。必须保留备份并退出当前阶段，保证用户记忆不被擦除。
- **故障过滤门限**：严禁响应单次报错。必须过滤掉网络超时、文件锁定等临时性错误，只收集连续的逻辑重构请求或工具栈格式错误。
