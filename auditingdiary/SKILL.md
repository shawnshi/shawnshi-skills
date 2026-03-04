---
name: auditingdiary
description: 管理个人日记条目，并使用结构化提示词进行认知审计（周/月/年度复盘）。
 triggers: ["复盘今天的日常日志", "提取我这段时间的认知盲点", "生成季度审计摘要草稿", "评估今天的毫无意义交互", "给我的日记加上高阶时间戳", "更新今日日志", "本周审计", "月度审计", "年度审计", "生成统计", "扫描工作产出", "备份日志"]
---

"""
@Input:  Daily Context (Calendar/Health/Chat), User Reflections.
@Output: Structured Log Entries, Markdown Audit Reports.
@Pos:    Cognitive Layer. The "Unification State" of the system.

!!! Maintenance Protocol: All file I/O MUST use scripts/diary_ops.py to ensure atomic prepends.
!!! Semantic Compliance: Tags MUST strictly follow references/semantic_layer.md.
"""

# Auditing Diary (Strategic Architect Edition)

管理个人认知熵值的核心工具。通过结构化日志与周期性审计，维持长期战略对齐。

## Core Capabilities
*   **Atomic Logging**: 安全地向日志目录（按季度拆分的 `YYYY-Q#.md`）顶部追加内容，绝不覆盖。
*   **Cognitive Audit**: 基于模板的周/月/年深度复盘，支持跨季度与年度连续读取。
*   **Quantified Self**: 自动生成专注度、情绪与产出的跨季度统计报告。
*   **Semantic Alignment**: 强制对齐 `references/semantic_layer.md` 中的本体。

## Execution Protocol (执行协议)

### Phase 0: Context Gathering & Triage [PLANNING Mode]
1.  **Intent Recognition (意图识别)**: 明确用户意图是 Daily Log 还是 Audit Workflow (周/月/年复盘)。
2.  **Context Assembly (上下文收集)**:
    *   获取当前日期: `YYYY-MM-DD`。
    *   **强制拉取健康数据**: 若为 Daily Log，必须调用 `${garmin-health-analysis}` 抓取当日生理指征（RHR, HRV, BB, Sleep）。
    *   **强制拉取日程**: 若为 Daily Log，必须拉取当日日程及**明日日程** (`/calendar:get-schedule`)，以自动校准“明日战术锁定”。
3.  **Density Gateway (触发网关与大纲阻断)**:
    *   **若是 Daily Log**: 评估当日交互对话。如果没有实质性的会话内容，跳过深度复盘提取。
    *   **若是 Audit Workflow**: 读取相应期段的日志记录。如果无实质内容，则拦截执行以免浪费算力。如果需要执行长篇复盘，**必须**在此阶段先生成初步大纲并使用 `notify_user` 挂起审批。未经大纲审批，严禁进入起草阶段。

### Phase 1: Cognitive Distillation & Drafting [EXECUTION Mode]
1.  **Session Analysis (会话抽提)**: 
    *   使用 `prompts/SESSION_ANALYSIS.md` 分析对话历史，提取核心产出与结晶。
    *   **必须严格按照 JSON Schema 输出**，同时由模型评估生成 `cognitive_depth_score` (认知深度得分 1-5)。
    *   如果为 Daily Log 且 `cognitive_depth_score` < 3，则精简文本记录。
2.  **Report Drafting (复盘起草)**: 
    *   如果是 Audit Workflow，在审批通过后，执行严谨的深度文件分析。
    *   通过 GEB-Flow 结构（带 `🟢 🟡 🔴` 状态标签与标准 YAML 元数据）落地生成实体 `.md` 报告（如 `tmp/audit_report.md`）。

### Phase 2: Operations & Write-Back [EXECUTION Mode]
1.  **Atomic Logging (原子写入)**: 
    *   调用脚本写入（脚本会自动计算日期归属的 `YYYY-Q#.md` 文件并在 `Diary` 目录下创建或追加）：
        ```bash
        python scripts/diary_ops.py prepend --file "diary" --content "..."
        ```
    *   若是完整审计报告，使用 content_file:
        ```bash
        python scripts/diary_ops.py prepend --file "diary" --content_file "tmp/audit_report.md"
        ```
2.  **Strategic Sync (记忆蒸馏)**: 
    *   提取高深度的洞察（`cognitive_depth_score` >= 4 或明确的战略增量），并调用脚本更新 `memory.md`：
        ```bash
        python scripts/memory_sync.py --category "战略偏好" --items '["观点1"]'
        python scripts/memory_sync.py --category "行业洞察" --items '["洞察1"]'
        ```

## Anti-Patterns (绝对禁令)
*   ❌ **禁止纯文字摘要式复盘**：如果只是堆砌今天做了什么（流水账），则视为无效输出。必须提炼“认知增量”或“异常发现”。
*   ❌ **禁止越级生成 (Skip-Phase)**：复杂审计任务在 Phase 0 未通过大纲确认前，绝对禁止直接调用提示词生成完整报告并写盘。
*   ❌ **禁止非法文件操作与覆盖写入**：任何日志动作必须是原子化 prepend（追加），绝不允许覆盖写入 (Overwrite) 原有日志文件，必须且只能依赖 `diary_ops.py`。
*   ❌ **禁止散乱格式解析缺失**：对于状态提取必须使用设定的 JSON Output，严禁以不稳定 Markdown 作为数据流转媒介。

## Supported Operations (工具指令参考)

### Read (`读取日志`)
按日期范围读取日志条目：
```bash
python scripts/diary_ops.py read --file "diary" --from "YYYY-MM-DD" --to "YYYY-MM-DD"
```

### Search (`搜索日志`)
```bash
python scripts/diary_ops.py search --file "diary" --query "关键词"
```

### Statistics (`生成统计`)
跨季度生成全体数据的可视化统计日志（情绪分布、专注度趋势、高频标签）。
```bash
python scripts/diary_ops.py stats --file "diary"
```

### Discovery (`扫描工作产出`)
```bash
python scripts/discovery_engine.py --days 7 --extensions .md .pptx .docx
```

### Backup (`备份日志`)
手动触发备份（为所有季度生成时间戳备份）。
```bash
python scripts/diary_ops.py backup --file "diary" --dir "privacy/backups"
```

## Troubleshooting
*   **Permission Error**: 确保 `privacy/` 目录存在且可写。
*   **Validation Error**: 若脚本提示 `Content missing date header`，请确保写入内容以 `# YYYY-MM-DD` 开头。
