---
name: personal-diary-writer
version: 9.0.0
tier: action-allowed
description: '原子写入今日工作、生理数据与认知审计日志至本地系统。仅在确认内容定稿并要求“落盘、保存日志”时使用。禁止用于分析历史互动、提炼长期结论或扩写未提供的事实。'
triggers: ["写日记", "记录今日状态", "保存审计日志"]
---

<strategy-gene>
Keywords: 日志写入, diary, 落盘, 原子写入
Summary: 将已经确定的日志内容安全写入本地日记资产。
Strategy:
1. 1. 确认内容已定稿、目标日期和目标文件。
2. 2. 走 MCP 获取日程，走专属脚本提取生理数据。
3. 3. 遵循预设 Schema 组装，并依赖 IO 脚本完成原子写入。
AVOID: 替用户扩写未确认内容；覆盖旧日志。
</strategy-gene>

# Personal Diary Writer (Atomic I/O V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `call_mcp_tool` (获取日程数据)
2. `run_command` (执行 garmin_intelligence.py)
3. `write_to_file` (写入缓存文件 log_entry.md)
4. `run_command` (执行 diary_ops.py 原子操作)
5. 注：偏离此轨迹则视为执行越权或幻觉。

## 1. 核心流程与架构 (The Protocol)
### Phase 0: Reconnaissance (证据先行)
- **自动化事实重建**: 调用原生 `call_mcp_tool` (`google-workspace: calendar.listEvents`) 获取真实日程数据。
- **能量数据提取**: 生理状态数据校验已左移至脚本约束。调用原生 `run_command` 提取：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-health-analysis\scripts\garmin_intelligence.py" insight_cn --days 3`
  如遇脚本失败，退级填入 `[DATA_UNAVAILABLE]`。

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
- **系统级聚焦同步**: 每次生成日志时，必须无条件调用脚本自动提取“明日战术”并更新 Antigravity CLI 的系统核心聚焦：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\io_engine\focus_sync.py" --log_file "C:\Users\shich\.gemini\tmp\log_entry.md"`
- **Mentat Insight Archival**: 若属于 Mentat 深度日志，物理归档至 `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md`。必须使用 `diary_ops.py`。
- **全局记忆同步**: 接收到认知深度 >= 4 的产出时，格式化为 JSON 并调用：
  `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\io_engine\memory_sync.py"` 同步至全局记忆。

## 2. <Contracts> (输出与交付契约)
- **Schema 结构防御**: 组装日志需遵从预设 Markdown 模板骨架。相关的格式强制校验由落盘脚本 (`diary_ops.py`) 自动处理。
- **Telemetry 记录**: 任务结束时，使用 `write_to_file` 工具将遥测数据以 JSON 格式保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 3. <Failure_Taxonomy> (失败分类学)
- **轨迹越权 (Trajectory Bypass)**：未遵循 `[IN_ORDER]` 轨迹的执行（例如绕开 `garmin_intelligence.py` 或试图用原生写文件工具覆盖已有日记）。
- **环境死锁与乱码 (Encoding Crash)**：调用 Python I/O 脚本时，缺失 `$env:PYTHONIOENCODING="utf-8"` 前缀引发的崩溃。
- **路径异常 (Path Error)**：使用 Linux `~` 变量而非 Windows 绝对硬路径 `C:\Users\shich\.gemini\...` 导致的作用域失效。
