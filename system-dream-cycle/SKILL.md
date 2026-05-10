<strategy-gene>
Keywords: 夜间清洗, 热缓冲提纯, 垃圾回收, 内存归档, 图谱同步
Summary: Mentat 系统的后台静默演化管线。通过确定性脚本清理环境熵增，并通过局部大模型提纯将临时态热知识沉淀为长期 Tier 2 图谱结构。
Strategy:
1. 算力隔离：垃圾回收与孤岛扫描必须交由 deterministic 脚本执行，绝对禁止 LLM 手动遍历文件系统。
2. 双轨提纯：读取 hot_facts.md，提取高价值实体并严格遵循 "Compiled Truth | Timeline" Schema 落盘。
3. 闭环清空：提纯成功后，物理重置热事实缓冲池。
4. 强制实体锚定：对知识库中未落地的概念孤岛发出告警。
</strategy-gene>

# System Dream Cycle (架构演化与系统清洗)

## 0. Intent
This skill acts as the background evolution loop for the Mentat system. It shifts compute from interactive sessions to silent batch processing, ensuring temporal entropy does not decay system performance. It implements garbage collection, structural integrity checks, and high-density memory diarization.

## 1. Trigger
- "触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"

## 2. Execution Pipeline (Strict Order)

### Phase 1: 物理层静默 GC (Garbage Collection)
**约束**: 严禁动用 `list_directory` 去偷看临时文件。必须强制调用确定性脚本完成。
- **动作**: 
  执行命令: 
  `uv run "{SKILL_DIR}/scripts/garbage_collector.py" --path "C:/Users/shich/.gemini/tmp" --max-age 24h`
- **处理**: 
  读取该 Python 脚本输出的 JSON 日志，记录 `deleted` 与 `scanned` 的值备用，无需进行额外解释。

### Phase 2: 热缓冲双轨提纯 (Hot Memory Diarization)
**约束**: 遵守 `memory.md` 中的 "Compiled Truth | Timeline" 双轨契约和实体映射规范。
1. **读取缓冲**:
   调用 `read_file` 提取 `C:/Users/shich/.gemini/MEMORY/hot_facts.md`。若文件不存在或内容为空，跳过此阶段。
2. **逻辑提纯**:
   在脑内进行实体化拆解。判断缓冲中记录的事件/实体应当归属到 Tier 2 (如 `MEMORY/wiki/`, `MEMORY/winning/`) 下的哪个文件。
3. **物理落盘 (Append-only + Rewrite)**:
   - 调用 `replace` 或 `write_file`，对对应的目标知识文件进行更新。
   - **严格排版**: 底部 Timeline 区域仅做追加（Append）；顶部的 Compiled Truth（编译事实）必须进行结构化重写。如果提到具体人物、公司、政策，强制包上 `[[ ]]` (例如: `[[OpenAI]]`)。
4. **重置缓冲**:
   落盘全部成功后，调用 `write_file`，将 `C:/Users/shich/.gemini/MEMORY/hot_facts.md` 覆写为一个空文件（或提示语句如 `<!-- 缓冲已于近期清空 -->`），完成状态闭环。

### Phase 3: 拓扑孤岛扫描 (Topology Orphan Check)
**约束**: 图谱扫描属于高维遍历，严禁交给 LLM 执行 O(N) 分析。
- **动作**:
  执行命令:
  `uv run "{SKILL_DIR}/scripts/orphan_scanner.py" --dir "C:/Users/shich/.gemini/MEMORY/wiki"`
- **处理**:
  阅读脚本返回的 JSON 报告。如果 `orphan_count > 0`，提取 Top 3 最频繁引用的孤岛标签作为“建议下个周期拓展的实体目标”。不采取写盘动作。

### Phase 4: 外部系统触发 (Vector Lake Sync)
*(Optional / Dependent on Extension Availability)*
如果检测到环境中配置了 Vector Lake，或者在之前的治理中需要全量推送，可在此阶段通过 `run_shell_command` 或对应的 MCP 工具触发图谱硬同步。如不可用，直接跳过。

---

## 3. Output Contract
当整个 Pipeline 完成后，禁止使用长篇大论或思考链刷屏，必须只返回一份如下的紧凑型结构化汇报框：

```json
{
  "system_status": "Dream Cycle Completed",
  "gc_stats": {
    "scanned": 150,
    "purged": 12
  },
  "memory_diarization": {
    "hot_facts_processed": 5,
    "entities_updated": ["[[Entity1]]", "[[Entity2]]"]
  },
  "topology_health": {
    "orphan_count": 3,
    "recommended_expansion": ["[[Orphan1]]", "[[Orphan2]]"]
  }
}
```

## 4. Telemetry
如果存在系统全局审计或监控记录器，可在此阶段自动将状态回传，保障 Mentat 系统的可观测性。否则，该段 JSON 输出即作为本次的唯一遥测数据。