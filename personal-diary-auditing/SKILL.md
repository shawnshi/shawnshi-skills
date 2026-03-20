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
2.  **Surgical Drafting (单步阻塞)**: 
    *   对于月/年复盘，每次对话【仅允许】起草 1 个维度（如“健康与精力”）。
    *   完成后必须 `[STOP]` 挂起，等待指令后继续。
3.  **Reviewer 审计**: 在交付前，Agent 执行二元校验：
    - [ ] 标签是否 100% 对齐 `semantic_layer.md`？ [Yes/No]
    - [ ] 报告是否包含 PART 0 中的历史战术问责？ [Yes/No]

### Phase 2: Atomic Operations & Write-Back [EXECUTION Mode]
1.  **Atomic Logging (Win32 物理适配)**: 
    *   禁止命令行直接传参复杂字符。
    *   必须执行：`write_file` 到 tmp -> 调用 `diary_ops.py prepend --content_file` 注入。
2.  **Strategic Sync (记忆蒸馏)**: 
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
