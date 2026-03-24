---
name: personal-diary-auditing
version: 4.1.1
description: |
  个人认知审计与日志治理专家 (V4.1.1)。当用户要求“复盘今日日志”、“提取认知盲点”或需要“周/月/年度审计报告”时激活。通过 ADK 五维补偿架构执行深层审计。
---

# SKILL: Diary Auditing & Cognitive Governance

管理个人认知熵值的核心工具。集成 Google ADK 5-Patterns，通过结构化补偿消除 LLM 的描述性膨胀，维持长期战略对齐。

## 0. 核心架构约束 (Core Mandates)
### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
Inversion (数据下锚): Phase 0 强制调用 garmin-health-analysis 与 gws-calendar 获取真实物理锚点，禁止脑补。
Pipeline (流程硬锁): 严格执行 Phase 0-2 闭环，月/年审计强制“单步阻塞”。
Generator (语义防御): 强制对齐 references/semantic_layer.md 本地本体，输出必须包含标准 YAML 元数据。
Tool Wrapper (原子操作): 所有的文件 I/O 必须通过 scripts/diary_ops.py 执行，禁止直接重定向。
Reviewer (深度审计): Phase 1 引入 cognitive_depth_score 评价体系，Phase 2 执行语义对齐度二元校验。
### 1. 核心调度约束 (Global State Machine)
[全局熔断协议]：系统必须严格依照 Phase 0 至 Phase 2 的顺序单步流转。跨越任何 Phase 前，必须在输出首行打印 [System State: Moving to Phase X] 探针。

## 2. 执行协议 (Execution Protocol)
### Phase 0: Context Gathering & Inversion [PLANNING Mode]
Context Assembly:
健康下锚: 【强制物理调用】激活 garmin-health-analysis 获取 RHR, HRV, BB 等数据。
日程校准: 【强制物理调用】激活 gws-calendar-agenda 拉取日程。
Audit Workflow (回溯拦截):
必须调用 diary_ops.py extract_tactics 抓取上一周期战术作为问责基准。
【大纲拦截】：展示包含 PART 0-VII 的大纲，调用 ask_user 获取审批。
### Phase 1: Cognitive Distillation & Reviewer [EXECUTION Mode]
Session Analysis: 提取核心产出，生成 cognitive_depth_score (1-5)。
Weekly Audit Enhancement (每周审计特别增强):
【强制同步】：在执行“每周审计”或“本周复盘”时，必须依次激活以下两个子系统：
Usage Insight: 激活 personal-monthly-insights 并调用 python analyze_insights_v4.py --period 7d --extract-only，随后执行 Stage 2-4，生成最近 7 天的系统交互战略报告。
Health Audit: 激活 personal-health-analysis 并运行 python scripts/garmin_intelligence.py insight_cn --days 7 与 python scripts/garmin_chart.py dashboard --days 7，生成最近 7 天的生理准备度审计。
【合成要求】：在最终周报的“精力与状态”及“交互效率”章节，必须引用上述两项审计的原始数据。
Monthly Audit Enhancement (月度审计特别增强):
【强制同步】：在执行“月度审计”或“月度复盘”时，必须依次激活以下两个子系统：
Usage Insight (30d): 激活 personal-monthly-insights 并调用 python analyze_insights_v4.py --period 30d --extract-only，随后执行 Stage 2-4，生成最近 30 天的系统交互战略报告（重点关注摩擦基因的演化）。
Health Audit (30d): 激活 personal-health-analysis 并运行 python scripts/garmin_intelligence.py insight_cn --days 30 与 python scripts/garmin_chart.py dashboard --period 30d，生成最近 30 天的生理基线漂移审计。
【合成要求】：月报必须对比 30 天内的生理趋势（RHR/HRV 趋势）与交互效率的因果关联。
Surgical Drafting (单步阻塞):
对于月/年复盘，每次对话【仅允许】起草 1 个维度（如“健康与精力”）。
完成后必须 [STOP] 挂起，等待指令后继续。
Reviewer 审计: 在交付前，Agent 执行二元校验：
 标签是否 100% 对齐 semantic_layer.md？ [Yes/No]
 报告是否包含 PART 0 中的历史战术问责？ [Yes/No]
 (仅限周/月报) 是否已包含对应周期的交互洞察与生理数据？ [Yes/No]
### Phase 2: Atomic Operations & Write-Back [EXECUTION Mode]
Atomic Logging (Win32 物理适配):
禁止命令行直接传参复杂字符。
必须执行：write_file 到 tmp -> 调用 diary_ops.py prepend --content_file 注入。
Mentat Insight Archival (同步调用内观日记):
【强制要求】：在生成日志的同时，必须同步生成一份符合 insight-diary 标准的 OODA 审计报告。
物理归档路径：{root_dir}/memory/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md。
归档策略：强制使用 diary_ops.py 执行季度级 prepend 操作。
Strategic Sync (记忆蒸馏):
若 cognitive_depth_score >= 4，格式化为 JSON 写入 tmp。
调用 scripts/memory_sync.py 同步至 memory.md。
## 3. Anti-Patterns (绝对禁令)
❌ 禁止纯文字摘要：必须提炼“认知增量”与“摩擦定性”。
❌ 禁止非法文件操作：绝不允许 Overwrite 原始日志，必须依赖 diary_ops.py 原子化操作。
❌ 禁止越级生成：未经大纲核准严禁生成全文。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "logic-adversary", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
- **[ARCHIVE_PREPEND]**: 必须使用 `diary_ops.py` 执行季度级 prepend，严禁创建碎片文件。
- **[PROMPT_MANDATE]**: 执行“每周审计”或“月度审计”前，**必须强制读取** `prompts/weekly.md` 或 `prompts/MONTHLY.md`。严禁仅依赖 `SKILL.md` 中的简化大纲。
- **[TABLE_MANDATE]**: 战术问责 (PART 0) 必须使用 Markdown Table 格式，并包含 Root Cause 分析。
- **[TACTICS_EXTRACT]**: `extract_tactics` 必须支持 Level 2/3 标题及多种中文同义词（如“下周重点任务”），否则将导致 Phase 0 问责中断。
- ALWAYS use `--content_file` for multi-line log prepends.
- DO NOT summarize historical tactics.
- ENSURE all tags are wrapped in `#tag` format.
