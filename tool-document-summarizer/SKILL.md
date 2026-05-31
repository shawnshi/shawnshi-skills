---
name: tool-document-summarizer
description: 医疗文档战略情报引擎 (V2.0 Antigravity Native)。当用户上传或提及 PDF/DOCX/PPTX/XLSX 文件并要求“总结”、“提取要点”或“审计盲区”时，务必激活。该技能具备本体驱动的语义压缩能力，输出带有战略标签的精准摘要，并执行系统级底层属性回写与图谱入湖。
triggers: ["智能提取文档摘要", "总结文档", "分析文件内容", "提取PDF核心要点"]
---

<strategy-gene>
Keywords: 医疗文档摘要, 合规审计, 战略标签, 并发分片处理
Summary: 针对医疗信息化文档执行本体驱动的语义压缩，拦截上下文黑洞，并强制进行物理回写与图谱入湖。
Strategy:
1. 原生并发分片：对超长文档严禁串行裸读，强制利用子代理集群并发拆解。
2. 战略打标：生成涵盖领域、技术、政策及价值的 5 层级战略标签。
3. 物理与云端双向注入：既要把摘要回写进源文件的系统属性，也要把提纯后的情报抛入 Vector Lake。
AVOID: 禁止单次 Prompt 加载超 10,000 字全文；严禁携带占位符的 JSON 进入 apply 回写流程；严禁裸调用相对路径脚本。
</strategy-gene>

# Tool Document Summarizer (Medical Intelligence x Antigravity Edition)

批量处理医疗信息化文档的战略情报引擎。具备本体驱动的摘要生成、合规性审计及战略盲区检测能力。是全系统防御“长文本算力黑洞 (Token Blackhole)”的最前线堡垒。

## When to Use
- 当用户上传或指向 PDF、DOCX、PPTX、XLSX 等文档，并要求总结、提取要点或审计盲区时使用。
- 适用于单文档摘要和文档库级战略审计，不适用于无文件输入的泛泛问答。

## Workflow

### Core Capabilities

*   **Intelligent Summarization**: 生成 100-150 字的高精度中文摘要，自动提取医院、厂商及核心指标。
*   **Compliance Audit**: 基于《电子病历评级标准》与《互联互通标准》自动检测文档合规性缺口。
*   **Strategic Tagging**: 生成 5 层级标签（领域 > 主题 > 核心技术 > 政策映射 > 战略价值）。
*   **Metadata Injection**: 将摘要与标签自动回写至源文件（PDF/Office）的系统级属性中，实现 OS 级别索引增强。
*   **Vector Lake Sync**: 将提炼后的核心洞察全异步汇入底层逻辑图谱。

### Native Sub-agent Delegation Protocol (并发分片处理)
**CRITICAL RULE**: 绝对禁止主代理在当前对话中直接裸读高达几十 MB、数百页的招投标文件或评级标准，这会导致主节点注意力崩溃并清空短期记忆。
1. **分发策略 (Shredding)**: 对于超长文档，主代理必须调用原生的 `invoke_subagent` 工具，拉起多个 `research` 或专用的分析子代理集群，将文档按章节或页码切片并并发投喂。
2. **静默组装 (Assembly)**: 主代理在派发完所有子代理分片任务后，强制原地挂起。在回收全部摘要分片后，才启动统一的宏观战略提纯。旧版的手写工单文件系统（Packet）现已彻底废除。

### 脚本指令执行规范 (Execution Protocol)

所有后台的引擎脚本必须使用绝对的物理防御封装：
**护盾前缀**: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/...`

#### 1. 核心指令 (Auto-Orchestration)
当需要处理整个目录时，调用编排脚本，它会自动处理提取、分析、审计与产物存储：
```bash
$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orchestrate_enhanced.py" all --dir <DOCUMENT_DIRECTORY>
```

#### 2. 分步执行 (Advanced Pipeline)
*   **仅提取文本**: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orchestrate_enhanced.py" extract --dir <PATH>`
*   **仅生成摘要**: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orchestrate_enhanced.py" generate`
*   **安全阻断 (Pollution Guard)**: 在执行下一步的 apply 回写前，主代理**必须检查** `output/document_summaries_enhanced.json` 中是否仍含有 `PENDING` 或 `[等待LLM]` 字样。如存在，严禁进入回写！
*   **仅物理回写元数据**: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orchestrate_enhanced.py" apply`
*   **清理垃圾**: `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/orchestrate_enhanced.py" clean`

#### 3. 图谱入湖与战略落盘 (Async Graph Sync)
所有处理完成后，主代理必须读取生成的 `output/STRATEGIC_AUDIT.md` (战略审计)，并提取高价值论断，调用 `mcp_vector-lake-mcp_prepare_ingest_batch` 并抛给 `vector-lake-ingestor` 执行后台异步全量入湖。

### Best Practices for Agents
1.  **路径感知**: 所有中间产物默认生成在源文件同级的 `output/` 目录下，严禁去根目录寻找。
2.  **大文件预警**: 对于超过 50MB 的源文件，切片处理时间极长，必须向用户发出进度预警。

## Resources
- `{SKILL_DIR}/scripts/orchestrate_enhanced.py`
- `{SKILL_DIR}/scripts/requirements.txt`
- `output/STRATEGIC_AUDIT.md`
- `output/document_summaries_enhanced.json`

## Failure Modes
- **[Token_Blackhole_Defense]**: 绝对禁止单次 Prompt 加载超过 10,000 字全文。必须严格使用子代理分片切割，当检测到上下文有突破 50k token 趋势时必须主动断链。
- **[Metadata_Pollution_Lock]**: 绝对禁止未完成 LLM 推理的占位符（PENDING）进入 apply 流程。这是物理层面的数据破坏，会导致源文件属性永久性污染。
- **[Win32_COM_Deadlock]**: 回写 Office 元数据时受限于 Windows COM 接口单线程锁。若并发回写参数（--workers）设置 >5，将大概率抛出 `COMError: 文件正在被另一个程序使用`，引发系统级阻塞。
- **[Path_Decode_Crash]**: 坚决禁止剥离 `$env:PYTHONIOENCODING="utf-8"` 前缀，否则处理含有中文文件名的 PDF 时，将 100% 触发路径崩溃。

## Output Contract
- 最终交付至少包含 100-150 字中文摘要、5 层级战略标签，以及必要时的合规缺口与战略盲区结论。
- 必须明确告知用户，核心情报已物理写入原文件，并已异步同步至中央智库（Vector Lake）。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "tool-document-summarizer", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`
