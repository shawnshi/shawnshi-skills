---
name: auditingdiary
description: 管理个人日记条目，并使用结构化提示词进行认知审计（周/月/年度复盘）。增加底层防跳步与物理数据锁。
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

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格依照 Phase 0 至 Phase 2 的顺序单步流转。跨越任何 Phase 前，必须在输出首行打印 `[System State: Moving to Phase X]` 探针。严禁跨级跳跃（如未收集数据直接生成报告）。

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
    *   **健康数据锚定**: 若为 Daily Log，【强制物理调用】：必须使用系统工具 `activate_skill` 激活 `name='garmin-health-analysis'` 以获取真实的生理数据锚点（RHR, HRV, BB, Sleep）。严禁大模型自行脑补数据。
    *   **日程校准**: 若为 Daily Log，【强制物理调用】：必须使用系统工具 `activate_skill` 激活 `name='gws-calendar-agenda'` 技能并通过 `gws calendar +agenda` 拉取当日及明日日程。严禁脑补。
3.  **Density Gateway (触发网关与大纲阻断)**:
    *   **若是 Daily Log**: 评估当日交互对话。如果没有实质性的会话内容，跳过深度复盘提取。
    *   **若是 Audit Workflow**: 
        *   **[强制回溯与战术提取]**: 必须调用 `python scripts/diary_ops.py extract_tactics --file "diary"` 精准抓取上一周期的 `Tactics` 作为 PART 0 的客观问责基准。严禁大模型凭空归纳。
        *   **[大纲对齐校验]**: 请求核准的大纲必须显式包含标准模板的 PART 0-VII 模块。
        *   【大纲拦截】：【必须强制】调用 `ask_user` 展示初步大纲并请求审批。未经核准，严禁进入起草阶段。

### Phase 1: Cognitive Distillation & Drafting [EXECUTION Mode]
1.  **Session Analysis (会话抽提)**: 
    *   使用 `prompts/SESSION_ANALYSIS.md` 分析对话历史，提取核心产出与结晶。
    *   **必须严格按照 JSON Schema 输出**，同时由模型评估生成 `cognitive_depth_score` (认知深度得分 1-5)。
    *   如果为 Daily Log 且 `cognitive_depth_score` < 3，则精简文本记录。
2.  **Report Drafting (复盘起草)**: 
    *   **[高保真落盘协议]**: 落盘文件必须是会话推演内容的 1:1 物理投影。严禁执行摘要式压缩或逻辑稀释。
    *   如果是 Audit Workflow，在审批通过后，执行严谨的深度文件分析。
    *   通过 GEB-Flow 结构（带 `🟢 🟡 🔴` 状态标签与标准 YAML 元数据）落地生成实体 `.md` 报告。
    *   **【单步阻塞执行】**：对于月/年复盘报告，每次对话轮次【仅允许】起草 1 个审计维度（如“健康与精力”或“决策盲点”）。生成后必须立即 `[STOP]` 挂起，等待用户回复“继续”后才允许推进。
    *   **【Escalation Hook (升维挂载点)】**：在复盘期间如果发现某一个系统性摩擦点（Persistent Friction）跨天/周重复出现，主动阻断起草并询问用户：*"发现[问题X]反复消耗系统能量。是否需要挂载 `morphism-mapper-master` 技能，使用跨界视角进行破局推演？"* 待用户确认后再行调用或跳过。

### Phase 2: Operations & Write-Back [EXECUTION Mode]
1.  **Atomic Logging (原子写入)**: 
    *   **[Win32 物理适配准则]**: 在 Win32 环境下，对于包含复杂字符或多行内容的日志，禁止使用 CLI 的 `--content` 直接传参。必须强制执行：`write_file` 到临时目录 -> 通过 `--content_file` 注入。
    *   【脚本执行保护】：所有文件 I/O 必须通过 `run_shell_command` 调用脚本。调用脚本写入（脚本会自动计算日期归属文件并追加）：
        ```bash
        python scripts/diary_ops.py prepend --file "diary" --content_file "PATH_TO_TEMP_FILE"
        ```
    *   如果脚本报错或找不到，【必须】立即中止操作向用户报告，严禁擅自使用 `write_file` 覆盖原有的季度日志文件。
2.  **Strategic Sync (记忆蒸馏)**: 
    *   提取高深度的洞察（`cognitive_depth_score` >= 4）。
    *   **[强制文件传参]**: 必须将洞察内容格式化为 JSON 数组并 `write_file` 保存至临时目录（如 `tmp/memory_updates.json`）。
    *   调用脚本更新 `memory.md`（严禁使用 `--items` 传参）：
        ```bash
        python scripts/memory_sync.py --category "认知结晶" --file "PATH_TO_TEMP_FILE"
        ```

## Anti-Patterns (绝对禁令)
*   ❌ **禁止纯文字摘要式复盘**：如果只是堆砌流水账，则视为无效输出。必须提炼“认知增量”。
*   ❌ **禁止越级生成 (Skip-Phase)**：复杂审计任务在 Phase 0 未通过大纲确认前，绝对禁止直接生成完整报告。
*   ❌ **禁止非法文件操作与覆盖写入**：任何日志动作必须是原子化 prepend，绝不允许覆盖写入 (Overwrite) 原有日志文件，必须且只能依赖 `diary_ops.py`。
*   ❌ **禁止直接传参 JSON**：调用 `memory_sync.py` 时严禁在命令行中拼接 JSON 字符串，必须使用 `--file` 参数。

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

### Extract Tactics (`提取历史战术`)
提取上一个周度审计报告中的战术承诺：
```bash
python scripts/diary_ops.py extract_tactics --file "diary"
```

### Statistics (`生成统计`)
```bash
python scripts/diary_ops.py stats --file "diary"
```

### Discovery (`扫描工作产出`)
```bash
python scripts/discovery_engine.py --days 7 --extensions .md .pptx .docx
```

### Sync Memory (`记忆同步`)
```bash
python scripts/memory_sync.py --category "行业洞察" --file "tmp/my_insights.json"
```

### Backup (`备份日志`)
```bash
python scripts/diary_ops.py backup --file "diary" --dir "privacy/backups"
```

## Troubleshooting
*   **Permission Error**: 确保 `privacy/` 目录存在且可写。
*   **Validation Error**: 若脚本提示 `Content missing date header`，请确保写入内容以 `# YYYY-MM-DD` 开头。