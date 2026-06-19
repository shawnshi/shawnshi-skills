---
name: tool-document-summarizer
version: 9.0.0
tier: action-allowed
description: '医疗文档战略情报引擎。基于本体驱动执行语义压缩，产出战略打标摘要并回写系统属性与双链图谱。禁止用于非专业领域普通文本的泛读，或尝试一口气加载整个PDF全文。'
triggers: ["智能提取文档摘要", "总结文档", "分析文件内容", "提取PDF核心要点"]
---

<strategy-gene>
Keywords: 医疗文档摘要, 合规审计, 战略标签, 并发分片处理
Summary: 针对医疗信息化文档执行本体驱动的语义压缩与战略打标，强制回写元数据并入湖。
Strategy:
1. 1. 原生并发分片：对超长文档利用子代理集群并发拆解或调用外部脚本处理。
2. 2. 战略打标：生成涵盖领域、技术、政策及价值的 5 层级标签。
3. 3. 物理与云端双向注入：摘要回写系统属性，情报抛入 Vector Lake。
AVOID: 单次加载超长全文导致上下文崩溃；回写带有占位符的 JSON 污染源文件。
</strategy-gene>

# Tool Document Summarizer (Medical Intelligence x Antigravity Edition V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (orchestrate_enhanced.py 提取与摘要生成)
2. `view_file` (检查输出的 JSON 避免污染)
3. `run_command` (orchestrate_enhanced.py apply 物理回写)
4. `call_mcp_tool` (调用 vector-lake 异步入湖)
5. `write_to_file` (写入遥测)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Native Sub-agent Delegation Protocol (并发分片处理)
- **防爆约束**: 针对高达数十 MB 的招标卷宗，长文本黑洞防御已左移至脚本控制。
1. **分发策略**: 使用 `run_command` 拉起处理脚本，或遇极度复杂推演时利用 `invoke_subagent` 委派切片子任务。
2. **静默组装**: 主代理派发完子任务后挂起，回收分片后再执行宏观合并。

### Phase 2: 脚本指令执行规范 (Execution Protocol)
引擎脚本需基于 `run_command` 并挂载安全前缀：
`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-document-summarizer\scripts\...`

#### 1. 核心编排 (Auto-Orchestration)
处理整个目录：
```bash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-document-summarizer\scripts\orchestrate_enhanced.py" all --dir <DOCUMENT_DIRECTORY>
```

#### 2. 安全回写门控 (Pollution Guard)
- 在执行 apply 回写前，需利用 `view_file` 检查 `output/document_summaries_enhanced.json` 中是否仍含 `PENDING` 或 `[等待LLM]`。若存在，阻断后续回写。
- **物理回写**: `$env:PYTHONIOENCODING="utf-8"; python "...orchestrate_enhanced.py" apply`
- **清理**: `$env:PYTHONIOENCODING="utf-8"; python "...orchestrate_enhanced.py" clean`

#### 3. 图谱入湖 (Async Graph Sync)
处理完成后，读取 `output/STRATEGIC_AUDIT.md`，提取高价值论断，调用 `call_mcp_tool` (`vector-lake-mcp`: `prepare_ingest_batch`) 执行后台异步全量入湖。

## 2. <Contracts> (输出与交付契约)
- **交付内容**：100-150 字中文摘要、5 层级战略标签，合规缺口与战略盲区结论。
- **回写通告**：明确告知用户情报已物理写入原文件，并异步同步至 Vector Lake。
- **Telemetry**：使用 `write_to_file` 将元数据 JSON 写入 `C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。

## 3. <Failure_Taxonomy> (失败分类学)
- **上下文黑洞 (Token Blackhole)**：单次 Prompt 加载超大文本导致截断或崩溃。
- **元数据污染 (Metadata Pollution)**：包含未完成推理占位符的 JSON 进入 apply 流程，导致物理文件属性受损。
- **COM 死锁 (Win32 COM Deadlock)**：由于单线程锁限制，回写 Office 元数据时设置并发 >5 引发的系统阻塞。
- **路径乱码 (Path Decode Crash)**：漏写 `$env:PYTHONIOENCODING="utf-8"` 导致中文文件名的 IO 崩溃。
