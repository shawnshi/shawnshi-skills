---
name: mentat-dream-cycle
description: Mentat 系统的后台静默演化管线。通过确定性脚本清理环境熵增，并通过局部大模型提纯将临时态热知识沉淀为长期 Tier 2 图谱结构。
triggers: ["触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"]
---

<strategy-gene>
Keywords: 夜间清洗, 热缓冲提纯, 垃圾回收, 内存归档, 图谱同步, 技能小批量更新 (Minibatch)
Summary: Mentat 系统的后台静默演化管线。通过确定性脚本清理环境熵增，并通过局部大模型提纯将临时态热知识沉淀为长期 Tier 2 图谱结构，同时执行技能的批量进化。
Strategy:
1. 算力隔离：物理垃圾回收与孤岛扫描必须交由 deterministic 脚本执行，绝对禁止 LLM 手动遍历文件系统。
2. 双轨提纯：读取 hot_facts.md，提取高价值实体并严格遵循 "Compiled Truth | Timeline" Schema 落盘。
3. 闭环清空：提纯成功后，物理重置热事实缓冲池。
4. 强制实体锚定：对知识库中未落地的概念孤岛发出告警。
5. 优雅降级：任何子脚本崩溃必须记录并继续。热事实提纯必须保持 Transactional 事务一致性，防范数据丢失。
6. 并行调度 (DAG)：物理层扫描与底层 GC 应当尽最大可能异步并行执行，避免管线阻塞。
</strategy-gene>

# Mentat Dream Cycle (架构演化与系统清洗)

## 0. Intent
This skill acts as the background evolution loop for the Mentat system. It shifts compute from interactive sessions to silent batch processing, ensuring temporal entropy does not decay system performance. It implements garbage collection, structural integrity checks, and high-density memory diarization.

## 1. Trigger
- "触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"

## 2. Execution Pipeline (DAG Orchestration)
注：Phase 1 和 Phase 3 可并行调度，与 Phase 2 的文件处理相互独立。
### Phase 1: 物理层与语义层双重 GC (Garbage Collection)
**约束**: 严禁动用 `list_directory` 去偷看文件。
1. **物理 GC**: 执行底层临时文件清理：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/garbage_collector.py" --path "C:/Users/shich/.gemini/tmp" --max-age 24h`
   *(读取输出 JSON 日志记录 `deleted` 和 `scanned`)*
2. **语义 GC**: 调用 `mcp_vector-lake-mcp_gc_vector_lake` (或原生 CLI) 自动清理图谱内长期无关联的孤儿节点及碎片，实现 Knowledge Decay 清理。

### Phase 2: 热缓冲双轨提纯 (Hot Memory Diarization)
**约束**: 遵守 `memory.md` 中的 "Compiled Truth | Timeline" 双轨契约和实体映射规范。防范数据丢失与 O(N) 写入疲劳。
1. **事务保护**: 将 `C:/Users/shich/.gemini/MEMORY/hot_facts.md` 拷贝或重命名为 `hot_facts.bak`。读取 `.bak` 文件进行处理。若文件不存在或为空，跳过此阶段。
2. **逻辑提纯与分块处理 (Micro-batching)**:
   在脑内进行实体化拆解。提取出优先级最高的 Top 5-8 个实体。
   - 对这部分高优实体，调用 `replace` 或 `write_file`，对目标知识文件进行原地更新。严格排版：底部 Timeline 追加，顶部 Compiled Truth 重写。
   - 将剩余未能处理的实体推入 `C:/Users/shich/.gemini/MEMORY/wiki/.meta/Entity_Backlog.md` 待处理队列，或写回新的 `hot_facts.md`。
3. **事务提交**: 只有在步骤 2 中所有的写盘操作全部明确成功后，才可删除 `hot_facts.bak`，并向 `hot_facts.md` 注入 `<!-- 缓冲已于近期清空 -->`，完成原子级重置。

### Phase 2.5: 技能批量优化 (Skill Optimization Backward Pass)
**约束**: 严禁响应单次报错。必须对失败轨迹进行聚合 (Minibatch Merge) 以抵御噪声，并使用 Soft Validation Gate 验证。
1. **读取错误缓冲**: 读取 `C:/Users/shich/.gemini/MEMORY/skill_audit/failure_batch.jsonl`，执行 `GroupBy(Skill_Name)`。
2. **分类与过滤 (Failure Taxonomy)**: 丢弃孤立的单次报错。过滤掉临时性环境错误 `[Network_Timeout, File_Locked]`，仅提取 `[Logic_Error, Schema_Violation, Context_Exceeded]` 等结构性故障。
3. **异步投递 Minibatch**: 对于通过过滤的高优故障集合，调用 `invoke_subagent` 拉起 `mentat-skill-creator`。不要只传摘要，必须将属于该技能的**整个 Minibatch 失败轨迹**完整传入，指令其启动 Critic 提取普遍性故障并合并补丁。
4. **事务清空**: `invoke_subagent` 发起后，物理清空已被投递的故障日志记录。

### Phase 3: 拓扑孤岛扫描 (Topology Orphan Check)
**约束**: 图谱扫描严禁 LLM 手动 O(N) 分析。环境强制 UTF-8 防崩溃。
- **动作**: 执行命令：
  `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orphan_scanner.py" --dir "C:/Users/shich/.gemini/MEMORY/wiki"`
- **模糊去重 (Fuzzy Matching)**: 阅读 JSON 报告，提取 Top 5 最频繁引用的孤岛标签。在写入 Backlog 前，务必通过 Vector Lake 检索或心智排查，确认其是否仅为拼写差异（如同义词、大小写）。若是，则将其降级为链接修复任务。
- **处理与落盘**: 将真正属于架构盲区的孤岛概念，通过 `replace` 写入建议清单：`C:/Users/shich/.gemini/MEMORY/wiki/.meta/Orphan_Backlog.md`。
- **容灾**: 若本阶段抛出环境异常，记录错误并跳入 Phase 4，不可中断。

### Phase 4: 全链路异步摄入 (Asynchronous Vector Lake Ingestion)
*(Dependent on Extension Availability)*
如果前序流程修改了图谱文件，且环境具备 Vector Lake：
1. **放弃阻塞式 Sync**: 严禁直接调用耗时的 `sync_vector_lake` 以避免死锁与 EOF。
2. **生成摄入批次**: 调用 `mcp_vector-lake-mcp_prepare_ingest_batch`。
3. **异步委派**: 使用 `invoke_subagent` 拉起 `vector-lake-ingestor` 并行子节点去执行摄入，彻底释放主循环。

---

## 3. Output Contract
当整个 Pipeline 完成或降级完成后，只允许返回如下的结构化 JSON。禁止长篇大论。

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

## 4. Telemetry
该段 JSON 输出即作为本次演化任务的唯一遥测数据，供系统全局监控记录使用。