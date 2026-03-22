---
name: personal-diary-auditing
description: 个人认知审计与日志治理专家 (V4.0)。当用户要求“复盘今日日志”、“提取认知盲点”、“评估交互价值”或需要“周/月/年度审计报告”时，务必激活。该技能通过 ADK 五维补偿架构，对个人记录执行深层审计，强制执行防跳步审计流、物理数据锁与二元语义校验。
triggers: ["复盘今天的日常日志", "提取我这段时间的认知盲点", "生成季度审计摘要草稿", "评估今天的毫无意义交互", "给我的日记加上高阶时间戳", "更新今日日志", "本周审计", "月度审计", "年度审计", "生成统计", "扫描工作产出", "备份日志"]
---

# Personal Diary Auditing (V4.0: Cognitive OS Edition)

管理个人认知熵值的核心工具。集成 Google ADK 5-Patterns，通过结构化补偿消除 LLM 的描述性膨胀，维持长期战略对齐。

## 0. 核心架构约束 (Core Mandates)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Inversion (数据下锚)**: Phase 0 强制调用 `garmin-health-analysis` 与 `gws-calendar` 获取真实物理锚点，禁止脑补。
- **Pipeline (流程硬锁)**: 严格执行 Phase 0-2 闭环，月/年审计强制“单步阻塞”。
- **Generator (语义防御)**: 强制对齐 `references/semantic_layer.md` 本地本体，输出必须包含标准 YAML 元数据。
- **Tool Wrapper (原子操作)**: 所有的文件 I/O 必须通过 `scripts/diary_ops.py` 执行，禁止直接重定向。
- **Reviewer (深度审计)**: Phase 1 引入 `cognitive_depth_score` 评价体系，Phase 2 执行语义对齐度二元校验。

## 1. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格依照 Phase 0 至 Phase 2 的顺序单步流转。跨越任何 Phase 前，必须在输出首行打印 `[System State: Moving to Phase X]` 探针。

## 2. 执行协议 (Execution Protocol)

### Phase 0: Context Gathering & Inversion [PLANNING Mode]
1.  **Context Assembly**:
    *   **健康下锚**: 【强制物理调用】激活 `garmin-health-analysis` 获取 RHR, HRV, BB 等数据。
    *   **日程校准**: 【强制物理调用】激活 `gws-calendar-agenda` 拉取日程。
2.  **Audit Workflow (回溯拦截)**: 
    *   必须调用 `diary_ops.py extract_tactics` 抓取上一周期战术作为问责基准。
    *   【大纲拦截】：展示包含 PART 0-VII 的大纲，调用 `ask_user` 获取审批。

### Phase 1: Cognitive Distillation & Reviewer [EXECUTION Mode]
1.  **Session Analysis**: 提取核心产出，生成 `cognitive_depth_score` (1-5)。
2.  **Weekly Audit Enhancement (每周审计特别增强)**:
    *   【强制同步】：在执行“每周审计”或“本周复盘”时，必须依次激活以下三个子系统：
        1.  **Usage Insight**: 激活 `personal-monthly-insights` 并调用 `python analyze_insights_v4.py --period 7d --extract-only`，随后执行 Stage 2-4，生成最近 7 天的系统交互战略报告。
        2.  **Quantitative Retro**: 激活 `system-retro` 并运行 `python C:\Users\shich\.gemini\scripts\system_retro.py`，获取本周技能调用的量化损耗（Token 黑洞、失败率、延迟分布）。
        3.  **Health Audit**: 激活 `personal-health-analysis` 并运行 `python scripts/garmin_intelligence.py insight_cn --days 7` 与 `python scripts/garmin_chart.py dashboard --days 7`，生成最近 7 天的生理准备度审计。
    *   【合成要求】：在最终周报的“精力与状态”及“交互效率”章节，必须引用上述三项审计的原始数据。将“算力蒸发”与“生理疲劳”进行关联分析。
3.  **Monthly Audit Enhancement (月度审计特别增强)**:
    *   【强制同步】：在执行“月度审计”或“月度复盘”时，必须依次激活以下两个子系统：
        1.  **Usage Insight (30d)**: 激活 `personal-monthly-insights` 并调用 `python analyze_insights_v4.py --period 30d --extract-only`，随后执行 Stage 2-4，生成最近 30 天的系统交互战略报告（重点关注摩擦基因的演化）。
        2.  **Health Audit (30d)**: 激活 `personal-health-analysis` 并运行 `python scripts/garmin_intelligence.py insight_cn --days 30` 与 `python scripts/garmin_chart.py dashboard --period 30d`，生成最近 30 天的生理基线漂移审计。
    *   【合成要求】：月报必须对比 30 天内的生理趋势（RHR/HRV 趋势）与交互效率的因果关联。
4.  **Surgical Drafting (单步阻塞)**: 
    *   对于月/年复盘，每次对话【仅允许】起草 1 个维度（如“健康与精力”）。
    *   完成后必须 `[STOP]` 挂起，等待指令后继续。
5.  **Reviewer 审计**: 在交付前，Agent 执行二元校验：
    - [ ] 标签是否 100% 对齐 `semantic_layer.md`？ [Yes/No]
    - [ ] 报告是否包含 PART 0 中的历史战术问责？ [Yes/No]
    - [ ] (仅限周/月报) 是否已包含对应周期的交互洞察与生理数据？ [Yes/No]

### Phase 2: Atomic Operations & Write-Back [EXECUTION Mode]
1.  **Atomic Logging (Win32 物理适配)**: 
    *   禁止命令行直接传参复杂字符。
    *   必须执行：`write_file` 到 tmp -> 调用 `diary_ops.py prepend --content_file` 注入。
2.  **Mentat Insight Archival (同步调用内观日记)**: 
    *   【强制要求】：在生成日志的同时，必须同步生成一份符合 `insight-diary` 标准的 OODA 审计报告。
    *   物理归档路径：`{root_dir}/memory/privacy/Diary/mentat_audit/[YYYY-MM-DD]_Audit.md`。
    *   内容必须包含：观测 (Observe)、导向 (Orient)、决策 (Decide)、执行 (Act) 及认知结晶。
3.  **Strategic Sync (记忆蒸馏)**: 
    *   若 `cognitive_depth_score` >= 4，格式化为 JSON 写入 tmp。
    *   调用 `scripts/memory_sync.py` 同步至 `memory.md`。

## 3. Anti-Patterns (绝对禁令)
*   ❌ **禁止纯文字摘要**：必须提炼“认知增量”与“摩擦定性”。
*   ❌ **禁止非法文件操作**：绝不允许 Overwrite 原始日志，必须依赖 `diary_ops.py` 原子化操作。
*   ❌ **禁止越级生成**：未经大纲核准严禁生成全文。

## 4. 历史失效先验 (Gotchas)
- ALWAYS use `--content_file` for multi-line log prepends to avoid Windows CLI escaping errors.
- DO NOT summarize historical tactics; EXTRACT verbatim from previous audit reports.
- ENSURE all tags are wrapped in `#tag` format and registered in the semantic layer.
