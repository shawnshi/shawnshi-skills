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
5. 优雅降级：任何子脚本或组件崩溃时，必须记录错误并继续，严禁中断整个清扫管线。
</strategy-gene>

# Mentat Dream Cycle (架构演化与系统清洗)

## 0. Intent
This skill acts as the background evolution loop for the Mentat system. It shifts compute from interactive sessions to silent batch processing, ensuring temporal entropy does not decay system performance. It implements garbage collection, structural integrity checks, and high-density memory diarization.

## 1. Trigger
- "触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"

## 2. Execution Pipeline (Strict Order)

### Phase 1: 物理层与语义层双重 GC (Garbage Collection)
**约束**: 严禁动用 `list_directory` 去偷看文件。
1. **物理 GC**: 执行底层临时文件清理：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/garbage_collector.py" --path "C:/Users/shich/.gemini/tmp" --max-age 24h`
   *(读取输出 JSON 日志记录 `deleted` 和 `scanned`)*
2. **语义 GC**: 调用 `mcp_vector-lake-mcp_gc_vector_lake` (或原生 CLI) 自动清理图谱内长期无关联的孤儿节点及碎片，实现 Knowledge Decay 清理。

### Phase 2: 热缓冲双轨提纯 (Hot Memory Diarization)
**约束**: 遵守 `memory.md` 中的 "Compiled Truth | Timeline" 双轨契约和实体映射规范。防范 O(N) 写入疲劳。
1. **读取缓冲**: 调用 `read_file` 提取 `C:/Users/shich/.gemini/MEMORY/hot_facts.md`。若文件不存在或内容为空，跳过此阶段。
2. **逻辑提纯与阈值分流 (O(N) Protection)**:
   在脑内进行实体化拆解，评估要更新的唯一实体数量。
   - **分支 A (Entities <= 8)**: 调用 `replace` 或 `write_file`，对对应的目标知识文件进行原地更新。严格排版：底部 Timeline 追加，顶部 Compiled Truth 重写。
   - **分支 B (Entities > 8)**: 为防止系统 Context 耗尽，禁止逐个写盘。将所有编译好的实体卡片统一追加写入 `C:/Users/shich/.gemini/MEMORY/wiki/.meta/Entity_Backlog.md` 待处理队列。
3. **重置缓冲**: 落盘成功后，将 `hot_facts.md` 覆写为 `<!-- 缓冲已于近期清空 -->`。

### Phase 2.5: 技能批量优化 (Skill Optimization Backward Pass)
**约束**: 严禁直接单次报错就去修改技能，必须进行批量（Minibatch）验证防抖。
1. **读取错误缓冲**: 读取 `C:/Users/shich/.gemini/MEMORY/skill_audit/failure_batch.jsonl`，按技能名分组。
2. **过滤孤例**: 丢弃失败次数 < 2 的技能报错（过滤偶然噪声）。
3. **唤醒 Creator**: 对于失败次数 >= 2 的技能，调用 `invoke_subagent` 启动 `mentat-skill-creator`，将该技能的批量错误摘要送入，并要求其产出单点补丁（Edit Budget）。
4. **清空批次**: 处理完毕后清空已修复技能的错误日志。

### Phase 3: 拓扑孤岛扫描 (Topology Orphan Check)
**约束**: 图谱扫描严禁 LLM 手动 O(N) 分析。环境强制 UTF-8 防崩溃。
- **动作**: 执行命令：
  `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orphan_scanner.py" --dir "C:/Users/shich/.gemini/MEMORY/wiki"`
- **处理与落盘**: 阅读 JSON 报告。如果 `orphan_count > 0`，提取 Top 5 最频繁引用的孤岛标签，通过 `replace` 写入建议清单：`C:/Users/shich/.gemini/MEMORY/wiki/.meta/Orphan_Backlog.md`。
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
  ]
}
```

## 4. Telemetry
该段 JSON 输出即作为本次演化任务的唯一遥测数据，供系统全局监控记录使用。