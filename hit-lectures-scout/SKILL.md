---
name: hit-lectures-scout
description: 医疗数字化前沿科研侦察兵。Primary owner for medical AI paper scouting, clinical literature scanning, RWE filtering, and frontier academic breakthrough watch. Use for Nature/JAMA-level paper scouting and research-to-commercial-defense translation. Prefer hit-industry-radar for news/event scans and hit-weekly-brief for think-tank or whitepaper briefs.
---

<strategy-gene>
Keywords: 医疗 AI 论文, 医学信息化, 数字化转型, 科研侦察, 研发转化, RWE 校验, 专有资产映射
Summary: 捕捉医疗数字化非共识信号，通过“范式跃迁”框架进行战略升维，将学术突破深度映射至卫宁健康核心架构（ACE、MSL、Logic Lake等），并转化为宏观行业建议与微观研发销售杠杆。
Strategy:
1. 弹性侦察：默认 7 天视窗，结果不足 5 篇时自动回溯至 14 天。扩大检索范围涵盖数字化转型、临床决策支持(CDSS)等系统级突破。
2. 提纯脱水：强制执行 RWE (真实世界证据) 校验，过滤无临床对照的噪声。
3. 强资产映射：强制将外部学术信号翻译并挂载至卫宁健康专有架构词典，强化排他性商业价值。
4. 双轨杠杆转换：外部展示层输出宏观行业建议与范式跃迁叙事，内部执行层输出1个具体研发任务与1条销售防御话术。
AVOID: 严禁在报告中保留 [URL] 占位符；禁止发布无临床场景适配的 L1 级情报；禁止绕过 DOI 精准校验；严禁使用干瘪的学术翻译，必须加入商业战略推演。
</strategy-gene>

# SKILL.md: HIT Intel Scout V6.2 (医疗数字化战略侦察兵)

> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除"学术灌水"与"幻觉"，将学术突破转化为卫宁研发部的具体任务与销售线的防御武器。

## When to Use
- 当用户要求扫描医疗 AI 论文、追踪医疗大模型突破，或输出带商业含义的科研战报时使用。
- 目标不是普通论文综述，而是将学术信号转成研发任务与销售防御资产。

## Workflow

### 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **默认视窗**: **过去 7 天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7 天内核心突破数 < 5 篇，则**必须自动将检索视窗扩大至 14 天**。

### Subtask Packaging Protocol (Antigravity Native)
**CRITICAL RULE**: 为保护主代理的上下文不被海量论文全文撑爆，必须使用系统的异步回调机制。严禁主代理直接通过 Web 搜索遍历数十篇 PDF。

### 核心工作流 (Blackboard Protocol)

### Phase 1: 混合调度 — deepxiv-sdk + 子代理并发 (Map-Reduce Delegation) [Mode: PLANNING]

**Preprints 管线 (deepxiv-sdk 直控 & 降级预案)**:
1. **deepxiv-sdk 脚本调用**: 通过 shell command 执行 `python "{SKILL_DIR}/assets/deepxiv_preprints_scout.py"`。该脚本通过 `deepxiv_sdk.Reader` API 执行混合检索、提纯与先验去重。
2. **弹性降维**: 若脚本返回结果 < 5 篇，自动将检索窗口扩大至 14 天。
3. **API 降级预案 (Resilience Routing)**: 若 `deepxiv_preprints_scout.py` 执行失败，主代理必须立刻拉起 `research` 子代理，下发 `assets/task_preprints_fallback.md` 指令，命令其使用 `search_web` 配合 `site:arxiv.org/list/cs.AI/recent` 手动抓取预印本信息并回调结果。绝不允许因 API 故障导致管线断流。

**EN/CN Journals 管线 (原生并发委派)**:
4. **并发调度**: 严禁通过物理文件顺序执行！主代理必须直接使用 `invoke_subagent` 拉起两个 `research` 类型的子代理，分别将 `assets/task_journals_en.md` 和 `assets/task_journals_cn.md` 的内容作为 `Prompt` 发出。
5. **结果回收**: 主代理原地挂起，利用系统原生的回调（Callback）机制回收提纯后的高纯度结论，直接消灭中间临时文件 `Response_*.md` 的读写。

**汇合与去重**:
6. **时序与逻辑补位**: 在所有并发管线（Preprints / EN Journals / CN Journals）回调结束后。若顶级正刊论文不足，提取热点趋势补齐信息密度。
7. **语义拦截**: 若某篇论文已在过去 14 天内被扫描过且无重大二阶评论，强制拦截。将高纯度信息推入数字黑板。

### Phase 2: Arbiter 提纯与 TRL 脱水 [Mode: EXECUTION]
1. **战略分流**: 筛选 Top 10-15 篇文献进入数字黑板。
2. **Arbiter 审计**: 强制执行"真实世界证据 (RWE)"校验。无临床对照实验、无真实场景适配的论文标记为 L1/Noise。
3. **TRL 评估**: 依据 S-T-C 框架（信号-威胁-对策）进行成熟度脱水。
4. **"So What" 框架激活**: 每一项 L4 级信号必须输出：`1个具体的研发预研任务（含建议技术栈）` 和 `1条针对竞对的销售防御话术`。

### Phase 3: Weaver 关联与强专有资产映射 [Mode: EXECUTION]
1. **Weaver 织网**: 寻找黑板上论文与核心产品或本周竞对动态的联结。
2. **专有资产强映射 (Proprietary Asset Mapping)**: **[CRITICAL]** 强制将外部学术突破翻译并对齐至卫宁健康底层战略架构。例如，将“智能体(Agent)”映射至“ACE引擎”，将“知识图谱/多模态数据”映射至“Logic Lake逻辑湖”，将“数字前门/智能分诊”映射至“MSL医疗语义层”与“WiNGPT”。
3. **Memory Interleave (MSA 增强)**: 若发现"技术落地可行性"存在证据断层，则显式调用工具进行关联补充。
4. **激活 Reviewer**: 调用 `cognitive-logic-adversary` 技能，推演该技术在 DRG/DIP 环境下的真实成本黑洞，作为防伪校验。

### Phase 4: 战略推演、范式跃迁与杠杆锻造 (Activate) [Mode: EXECUTION]
1. **范式跃迁提取 (Paradigm Shift)**: 为每篇核心论文总结一句话的代际跃迁公式（如 `From [旧有共识] To [前沿理念]`），提升报告战略高度。
2. **双轨杠杆转换**: 
   - **内部执行轨 (Micro)**: 将高价值信号严格翻译为 `1个具体预研任务（含建议技术栈）` 与 `1条针对竞对的销售防御话术`。
   - **外部布道轨 (Macro)**: 跳出学术本身，站在行业布道者高度，输出“行业数字化转型路线规划或系统顶层架构建议”。
3. **内容洗练**: 应用高管视角的冷酷且富有煽动性的布道风格，剔除生硬的学术翻译，确保逻辑的 MECE 原则（相互独立，完全穷尽）。

### Phase 5: 结构化生成与元数据审计 (Self-Healing & Persistence) [Mode: EXECUTION]
1. **强制模板**: 必须读取 `assets/report_template.md` 作为输出骨架。
2. **物理归档与强迫工具校验**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]` 或 `[URL]`，且严禁凭空推测或幻觉编造链接。你**必须显式调用 `search_web` 或 `read_url_content` 工具**检索 DOI 数据库或访问论文原始页面，确认地址无误后，方可写入真实的 `[Ref: DOI_Link]`。
3. **学术概念异步入湖 (Async Graph Ingestion)**：战报落盘后，若发现新的高价值架构或临床陷阱，通过 `write_file` 创建或更新 `C:/Users/shich/.gemini/MEMORY/wiki/Concept_[概念名].md`。
   - **绝对禁令**: 严禁直接调用阻塞式 `sync_vector_lake`。
   - **异步同步**: 必须调用 `mcp_vector-lake-mcp_prepare_ingest_batch`，随后利用 `invoke_subagent` 拉起 `vector-lake-ingestor` 后台执行入湖，彻底释放主循环。

### Phase 6: The Hard Gate (物理层强制代码审计)
1. **写草稿**: 必须将组装好的战报写入临时文件 `C:/Users/shich/.gemini/tmp/draft_hit_scout.md`。
2. **执行跨平台审计**: 调用 shell 执行并强制挂载 UTF-8 编码，防止中文崩溃：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/hit_audit_gate.py" "C:/Users/shich/.gemini/tmp/draft_hit_scout.md" --mode scout`
3. **处理失败**: 若审计报错（如未发现 RWE 标记、缺失预研任务或残留 URL 占位符），必须退回修正草稿，最多重试 2 次。
4. **最终落盘**: **[MANDATORY]** 只有在审计脚本返回 `Audit Passed` 后，才能使用 `write_file` 归档保存至 `C:/Users/shich/.gemini/MEMORY/raw/DigitalHealthLecturesScout/`。

## Resources
- `assets/deepxiv_preprints_scout.py`
- `assets/task_preprints_fallback.md`
- `assets/task_journals_en.md`
- `assets/task_journals_cn.md`
- `assets/report_template.md`
- 关联技能：`cognitive-logic-adversary`

## Failure Modes
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- 严禁在最终报告中保留 `[Link]`、`[URL]` 或其他占位符链接。
- 若顶级正刊不足或证据断层，必须显式触发补位流程，而不是直接生成低密度输出。

## Output Contract
- 最终战报必须包含 Top 10-15 文献、RWE/TRL 审计结果，以及每个 L4 信号对应的研发预研任务和销售防御话术。
- 报告必须使用 `assets/report_template.md` 输出，并完成归档与精准证据节点标注。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "hit-lectures-scout", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`
