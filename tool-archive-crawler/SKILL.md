---
name: tool-archive-crawler
description: 用于非结构化历史文件和旧档案的清洗与翻新。当用户要求“扫描旧档案”、“挖掘历史文件”、“翻新旧笔记”、“矿工扫描”或清洗特定目录时使用，将其提取并强行锚定入 Tier 2 双链图谱。
---

<strategy-gene>
Keywords: 旧档案翻新, 知识提纯, 双向链接, 图谱挂载
Summary: 将本地无价值废墟提纯为符合 Compiled Truth | Timeline 的核心双链资产。
Strategy:
1. 快速判定原始数据的战略含金量，过滤纯水文与低质噪音。
2. 强制使用 `[[ ]]` 对核心实体（人名/公司/术语）进行物理硬链接。
3. 提取结果必须严格遵循 Tier 2 (Durable Knowledge) 格式规范进行重写落盘。
AVOID: 严禁无中生有编造时间点；严禁保留无意义的对话废话；严禁全篇照搬。
</strategy-gene>

# Tool Archive Crawler (数字废墟矿工)

## Workflow

### Phase 1: Scanning (扫描与鉴别)
1. 锁定用户指定的旧文件或目录（通常位于 `raw/` 或外部挂载路径）。
2. 快速判断该资产的**含金量**：如果全是无价值流水账，直接建议丢弃或留在 Tier 1；如果包含行业洞见、重要人脉、项目复盘，进入下一阶段。

### Phase 2: Entity & Graph Anchoring (实体捕捉与清洗)
1. 在文本中提取所有具备持久价值的**实体**（人名、公司、产品、专有医疗/AI术语）。
2. 剥离废话、客套话与情绪化表达。

### Phase 3: Remolding to Tier 2 (架构重塑)
强制将提取出的内容重构为一个全新的、符合 `pai/memory.md` 规范的 Markdown 资产：
1. **[Top] Compiled Truth / 编译事实**：生成高密度的核心结论。
2. **[Bottom] Timeline / 证据时间线**：将原始文件的事件/观点按照时间或逻辑打平成列表。
3. **图谱挂载 (Entity Linking Contract)**：在上述两部分中，**必须**将找出的重要实体使用双层方括号 `[[ ]]` 包裹（如 `[[卫宁健康]]`，`[[Acme AI]]`），并在其附近补全精确的动作关系谓词。

### Phase 4: Writeback (物理落盘)
1. 使用 `write_file` 将新结构写入 `MEMORY/wiki/` 或对应的 Tier 2 子目录中。

## Failure Modes
- **全篇无高价值实体**：直接中止提纯，保留原样，向用户反馈无需升级架构。
- **缺失上下文时间**：在 Timeline 中明确标注 `[日期未知]`，按业务逻辑顺序排列。

## Output Contract
输出一份简短的清单即可：
1. 落盘路径。
2. 新挖掘出并打上双链的 `[[实体集合]]`。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "tool-archive-crawler", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)