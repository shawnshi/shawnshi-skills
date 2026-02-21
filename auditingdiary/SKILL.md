---
name: auditingdiary
description: Manages personal diary entries and performs cognitive audits (weekly, monthly, annual) using structured prompts. Use when the user asks to update their daily log, or requests a weekly, monthly, or annual review/audit of their diary.
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
*   **Atomic Logging**: 安全地向日志文件顶部追加内容，绝不覆盖。
*   **Cognitive Audit**: 基于模板的周/月/年深度复盘。
*   **Quantified Self**: 自动生成专注度、情绪与产出的统计报告。
*   **Semantic Alignment**: 强制对齐 `references/semantic_layer.md` 中的本体。

## 1. Daily Log Workflow (`更新当日日志`)

当用户要求更新日志时：

1.  **Context Gathering (Auto)**:
    *   获取日期: `YYYY-MM-DD`。
    *   获取日程: `/calendar:get-schedule`。
    *   获取健康数据: `${garmin-health-analysis}` (Resting HR, Body Battery, Sleep)。
2.  **Session Analysis (Automated Distillation)**:
    *   **回溯当前会话**: 分析对话历史，提取以下内容：
        *   **核心产出**: 本次会话完成的文件修改、代码编写、调研分析等（参考 `prompts/SESSION_ANALYSIS.md`）。
        *   **认知结晶**: 过程中的深度洞察、发现的逻辑矛盾或新形成的策略建议。
        *   **战术锁定**: 对话中提到的后续待办事项。
3.  **Draft Presentation & Refinement**:
    *   展示基于 session 自动生成的日志草案。
    *   **交互确认**: 补充自动分析无法获取的维度（如“专注度(1-5)”、“情绪”以及未在对话中体现的私密反思）。
4.  **Execution**:
    *   基于 `references/templates.md` 组装最终内容。
    *   调用脚本写入：
        ```bash
        python scripts/diary_ops.py prepend --file "privacy/{YYYY}Diary.md" --content "..."
        ```

## 2. Audit Workflow (周/月/年审计)

### Standard Audit
1.  **Read Context**: 读取相关时间段的日志。
    ```bash
    python scripts/diary_ops.py read --file "diary" --from "YYYY-MM-DD" --to "YYYY-MM-DD"
    ```
2.  **Strategic Context**: 读取 `memory.md`，提取"个人行业观点"作为审计的战略锚点。
3.  **Discovery (Auto)**: 扫描 `references/work_nodes.md` 中定义的目录，检索本周期的产出物列表。
4.  **Work Analysis (Workspace)**: 扫描 Google Workspace，检索本周期的产出物列表。
5.  **Work Analysis (Deep Read)**: 对新增产出进行深度阅读，分析战略意图与认知增量。
6.  **Strategic Alignment Analysis**: 对比实战产出与 `memory.md` 中的观点，执行 `prompts/weekly/PART_VI_STRATEGIC_ALIGNMENT.md` 逻辑。
7.  **Health Data**: 制定时间范围的健康评估: `${garmin-health-analysis}`，并将报告保存在 `.gemini/health/` 目录。
8.  **Generate Report**: 使用 `prompts/` 下对应的模块化提示词生成深度分析。
9.  **Save**:
    ```bash
    python scripts/diary_ops.py prepend --file "diary" --content_file "tmp/audit_report.md"
    ```
10. **Memory Synchronization**:
    *   从审计报告中提取符合“战略偏好”与“行业洞察”定义的金句。
    *   调用脚本更新 `memory.md`：
        ```bash
        python scripts/memory_sync.py --category "战略偏好" --items '["观点1", "观点2"]'
        python scripts/memory_sync.py --category "行业洞察" --items '["洞察1", "洞察2"]'
        ```

### Advanced Strategic Audit (New)
当进行**年度审计**或用户要求**深度复盘**时，请联动外部 Agent：

1.  **Identify Key Themes**: 从统计数据中提取 Top 3 标签（如 `#Strategy/MedicalAI`）。
2.  **Call Thinker Roundtable**:
    *   针对核心议题调用 `${thinker-roundtable}`。
    *   Prompt: "基于我过去一年的 #Strategy/MedicalAI 记录，进行多维度的战略审视与盲区探测。"
3.  **Synthesize**: 将 Roundtable 的结论整合进年度审计报告。

## 3. Operations & Analysis

### Read (`读取日志`)
按日期范围读取日志条目：
```bash
python scripts/diary_ops.py read --file "diary" --from "2026-02-15" --to "2026-02-21"
```

### Search (`搜索日志`)
```bash
python scripts/diary_ops.py search --file "diary" --query "关键词"
```

### Statistics (`生成统计`)
生成可视化统计报告（情绪分布、专注度趋势、高频标签）。
```bash
python scripts/diary_ops.py stats --file "diary"
```

### Discovery (`扫描工作产出`)
```bash
python scripts/discovery_engine.py --days 7 --extensions .md .pptx .docx
```

### Backup (`备份日志`)
手动触发备份（写入操作前也会自动触发）。
```bash
python scripts/diary_ops.py backup --file "diary" --dir "privacy/backups"
```

## Troubleshooting
*   **Permission Error**: 确保 `privacy/` 目录存在且可写。
*   **Validation Error**: 若脚本提示 `Content missing date header`，请确保写入内容以 `# YYYY-MM-DD` 开头。
