---
name: personal-diary-writer
version: 8.1.0
description: 个人日志原子写入器。Primary owner for physical diary/log writeback and atomic persistence only. Use when content is already decided and must be safely written to disk. Prefer personal-cognitive-auditor for periodic review analysis, personal-monthly-insights for interaction meta-analysis, and mentat-insight-diary for first-person system introspection content.
triggers: ["写日记", "记录今日状态", "保存审计日志"]
---

<strategy-gene>
Keywords: 日志写入, diary, 落盘, 原子写入
Summary: 将已经确定的日志内容安全写入本地日记资产。
Strategy:
1. 确认内容已定稿、目标日期和目标文件。
2. 使用原子写入方式追加或创建日志。
3. 回读确认写入成功并报告路径。
AVOID: 禁止替用户扩写未确认内容；禁止覆盖旧日志。
</strategy-gene>

# Personal Diary Writer (Atomic I/O V8.1 Native)

本技能负责处理高频、轻量级的每日状态记录以及日志条目的原子化落盘操作。不负责虚构数据或替代上游审计判断。

## 1. 核心流程与架构 (The Protocol)

### Phase 0: Reconnaissance (证据先行) [Mode: PLANNING]
- **自动化事实重建**: 在组装日志前，必须调用原生的 `call_mcp_tool` (指向 `google-workspace` 服务器的 `calendar.listEvents`) 获取真实的日程数据。
- **能量数据硬锁**: 关于个人的生理能量状态，主代理**绝对禁止**凭空捏造。必须使用原生 `run_command` 调用专用脚本提取：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" insight_cn --days 3`
  若脚本执行失败，对应字段强制填入 `[DATA_UNAVAILABLE]`，严禁大模型自行脑补推演。

### Phase 1: Structure Alignment (结构对齐) [Mode: PLANNING]
严格按照以下格式组装内容（绝对禁止合并或遗漏标题）：
```markdown
# YYYY-MM-DD 星期X

## 今日工作 (Tactical Context)
- ...

## 核心产出 (Strategic Professional Assets)
- ...

## 明日战术锁定 (Next Day Tactics)
1. ...

## 认知结晶 (Cognitive Distillation)
...

## 熵增对抗 (Chaos Mitigation)
...

## 今日认知处方 (Cognitive Prescription)
...

## 能量管理 (Biological-Cognitive Correlation)
- **系统态势**: [必须提取自 Garmin 简报]
- **执行带宽**: 综合 [分数]/100 (认知 [分数] / 物理 [分数])
- **睡眠负债**: [提取债务小时数]h, 深睡占比 [比例]%
- **摩擦解构**: [基于真实数据的纯生理定性分析]
- **交叉归因**: [将生理耗散与今日某项具体高压业务事件挂钩]
- **干预指令**: [具体的强制动作，如“取消明日非必要会议”]

## 标签
#tag
```
- **联动防御**: 检查能量管理中的 `干预指令`，**必须**将其无条件映射到顶部的 `## 明日战术锁定 (Next Day Tactics)` 中作为最高优先级任务。

### Phase 2: Writeback (安全落盘) [Mode: EXECUTION]
由于日志的特性（需追加或原子插入），若无合适的原生直接写入方式，需走以下脚本流：
1. **暂存区**: 使用 `write_to_file` 将组装好的格式化文本写入绝对路径的临时文件 `C:\Users\shich\.gemini\tmp\log_entry.md`。
2. **安全追加**: 调用原生 `run_command` 执行原子前置操作：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\io_engine\diary_ops.py" prepend --content_file "C:\Users\shich\.gemini\tmp\log_entry.md"`

### 附属落盘协议 (Secondary Write-Backs)
- **Mentat Insight Archival**: 若属于 Mentat 深度日志，物理归档至 `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md`。必须使用 `diary_ops.py`。
- **全局记忆同步**: 接收到认知深度 >= 4 的产出时，格式化为 JSON 并调用：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\io_engine\memory_sync.py"` 同步至全局记忆。

## 2. <Contracts> (输出与交付契约)
- **Schema 绝对防御**: 最终落盘的日志必须严格遵循预定义的 Markdown 模板骨架，不可合并任何区块。所有的 `#tag` 必须规范化。
- **Telemetry 记录**: 任务结束时，使用 `write_to_file` 工具将元数据以 JSON 格式保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
  JSON 结构示例：`{"skill_name": "personal-diary-writer", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **幻觉工具调用 (Tool Hallucination)**：严禁使用废弃的 `gws` 终端命令获取日程，必须走 MCP 路由；严禁使用错误的伪名如 `run_shell_command` 或 `write_file`。
- **环境死锁与乱码 (Deadlock & Encoding Crash)**：调用任何 Python I/O 脚本时，必须包含 `$env:PYTHONIOENCODING="utf-8"`；所有的路径（脚本调用与临时文件读写）绝对禁止使用 Linux `~` 变量，必须使用 Windows 硬连接绝对地址 `C:\Users\shich\.gemini\...`。
- **数据编造 (Data Forgery)**：在组装“能量管理”区块时，严禁使用模型自身的权重推测身体状态。必须基于 `garmin_intelligence.py` 的返回。如缺少数据，强行熔断填入 `[DATA_UNAVAILABLE]`。
