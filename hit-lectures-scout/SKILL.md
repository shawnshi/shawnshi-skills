---
name: hit-lectures-scout
description: 医疗数字化前沿科研侦察兵。Primary owner for medical AI paper scouting, clinical literature scanning, RWE filtering, and frontier academic breakthrough watch. Use for Nature/JAMA-level paper scouting and research-to-commercial-defense translation. Prefer hit-industry-radar for news/event scans and hit-weekly-brief for think-tank or whitepaper briefs.
---

<strategy-gene>
Keywords: 医疗 AI 论文, 科研侦察, 研发转化, RWE 校验
Summary: 捕捉医疗数字化非共识信号，将学术突破转化为具体的研发任务与销售防御资产。
Strategy:
1. 弹性侦察：默认 7 天视窗，结果不足 5 篇时自动回溯至 14 天。
2. 提纯脱水：强制执行 RWE (真实世界证据) 校验，过滤无临床对照的噪声。
3. 杠杆转换：每项高价值信号必须输出 1 个研发任务与 1 条销售防御话术。
AVOID: 严禁在报告中保留 [URL] 占位符；禁止发布无临床场景适配的 L1 级情报；禁止绕过 DOI 精准校验。
</strategy-gene>

# SKILL.md: HIT Intel Scout V6.0 (医疗数字化战略侦察兵)

> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除"学术灌水"与"幻觉"，将学术突破转化为卫宁研发部的具体任务与销售线的防御武器。

## When to Use
- 当用户要求扫描医疗 AI 论文、追踪医疗大模型突破，或输出带商业含义的科研战报时使用。
- 目标不是普通论文综述，而是将学术信号转成研发任务与销售防御资产。

## Workflow

### 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **默认视窗**: **过去 7 天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7 天内核心突破数 < 5 篇，则**必须自动将检索视窗扩大至 14 天**。

### Subtask Packaging Protocol (Policy-Bound)
**CRITICAL RULE**: Heavy ingestion work should be packetized to protect context quality, but delegation is optional and must follow the active runtime policy.
1. **Packet Creation**: Before starting the heavy task, write the required parameters, URLs, or chapter outlines to a physical sandbox file such as `tmp/playgrounds/Task_Packet_[TIMESTAMP].md`.
2. **Execution Choice**: If the runtime supports sub-agents and the user explicitly asked for delegation, hand the packet to a bounded worker. Otherwise, execute the task locally in small batches and keep only extracted notes.
3. **Resume**: Read only the distilled result file or summary notes before continuing orchestration or final review.

### 核心工作流 (Blackboard Protocol)

### Phase 1: 混合调度 — deepxiv-sdk + 子代理并发 (Map-Reduce Delegation) [Mode: PLANNING]

**Preprints 管线 (deepxiv-sdk 直控)**:
1. **deepxiv-sdk 脚本调用**: 通过 shell command 执行 `python skills/hit-lectures-scout/assets/deepxiv_preprints_scout.py`。该脚本通过 `deepxiv_sdk.Reader` API 执行：
   - `Reader.search()` × 7 组关键词，混合检索 (BM25+Vector)，按 `categories` 和 `date_from/date_to` 精确过滤
   - `Reader.trending(days=7)` 补充热门论文
   - `Reader.brief()` 批量提纯 Top 30 论文（获取 TLDR / Keywords / Citations / GitHub URL）
   - 按 `arxiv_id` 先验去重，输出至 `tmp/playgrounds/Response_Preprints.md`
2. **弹性降维**: 若 7 天内结果 < 5 篇，脚本自动将检索窗口扩大至 14 天（与 §1 触发逻辑一致）。

**EN/CN Journals 管线 (委派可选)**:
3. **处理方式选择**: 将 `assets/task_journals_en.md` 和 `assets/task_journals_cn.md` 作为任务包。若可安全委派，则交给有界 worker；否则主代理顺序完成两条管线。
4. **结果落盘**: 无论由谁执行，都必须将提纯结果分别写回 `tmp/playgrounds/Response_EN.md` 与 `tmp/playgrounds/Response_CN.md`。

**汇合与去重**:
5. **时序与逻辑补位**: 只有在 deepxiv 脚本和全部 journal 管线都完成后，主代理才能读取三个 `Response` 文件。若顶级正刊论文不足，必须提取热点趋势补齐信息密度。
6. **资产回收与 SemHash 拦截**: 扫描物理目录执行 SemHash 去重。Preprints 数据已按 `arxiv_id` 先验去重，此处仅需跨管线（preprints vs journals）去重。若某篇论文已在过去 14 天内被扫描过且无重大二阶评论，强制拦截。将合并后的高纯度信息推入数字黑板，随后立即清扫 `tmp/` 下的中间产物。

### Phase 2: Arbiter 提纯与 TRL 脱水 [Mode: EXECUTION]
1. **战略分流**: 筛选 Top 10-15 篇文献进入数字黑板。
2. **Arbiter 审计**: 强制执行"真实世界证据 (RWE)"校验。无临床对照实验、无真实场景适配的论文标记为 L1/Noise。
3. **TRL 评估**: 依据 S-T-C 框架（信号-威胁-对策）进行成熟度脱水。
4. **"So What" 框架激活**: 每一项 L4 级信号必须输出：`1个具体的研发预研任务（含建议技术栈）` 和 `1条针对竞对的销售防御话术`。

### Phase 3: Weaver 关联与多跳路由审计 [Mode: EXECUTION]
1. **Weaver 织网**: 寻找黑板上论文与卫宁核心产品或本周竞对动态的联结。
2. **Memory Interleave (MSA 增强)**: 若发现"技术落地可行性"存在证据断层，且本地 `vector-lake` CLI 可用，则通过 shell command 执行查询补齐二跳推理；若不可用，则显式说明缺口并改用本地资料人工补证。
3. **激活 Reviewer**: 调用 `personal-logic-adversary` 技能；若当前运行时不能直接激活技能，则在本地执行同等强度的红队审计，推演其在 DRG 环境下的成本黑洞。

### Phase 4: 战略推演与杠杆锻造 (Activate) [Mode: EXECUTION]
1. **杠杆转换**: 将成果翻译为研发任务与销售话术。
2. **内容洗练**: 直接应用高管视角的冷酷风格优化内容，剔除学术冗余。

### Phase 5: 结构化生成与元数据审计 (Self-Healing & Persistence) [Mode: EXECUTION]
1. **强制模板**: 必须读取 `assets/report_template.md` 作为输出骨架。
2. **知识入湖**: 若本地 `vector-lake` CLI 可用，则通过 shell command 执行 `sync`；若不可用，则至少完成本地物理归档并记录未同步原因。
3. **元数据完整性审计**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]`、`[URL]` 或占位符。必须逐一校验 DOI 和源地址。若缺失则使用搜索/浏览工具二次精准核验。
4. **逻辑断层审计**: 确保每一项推理均挂载了精确的 `[Ref: Evidence_Node_ID]`。

### Phase 6: The Hard Gate (物理层强制审计)
1. **写草稿**: 你必须将组装好的战报写入临时文件 `~/.gemini/tmp/draft_hit_scout.md`。
2. **执行审计**: 调用 shell 执行 `python ~/.gemini/skills/scripts/hit_audit_gate.py ~/.gemini/tmp/draft_hit_scout.md --mode scout`。
3. **处理失败**: 若审计报错（如未发现 RWE/研发任务/销售话术，或残留占位符），必须退回修正草稿。最多重试 2 次。
4. **物理归档**: **[MANDATORY]** 只有审计脚本返回 `Audit Passed` 后，才能调用 `write_file` 将最终报告保存在 `~/.gemini/MEMORY/raw/DigitalHealthLecturesScout/`。

## Resources
- `assets/deepxiv_preprints_scout.py`
- `assets/task_journals_en.md`
- `assets/task_journals_cn.md`
- `assets/report_template.md`
- `tmp/playgrounds/Response_Preprints.md`
- `tmp/playgrounds/Response_EN.md`
- `tmp/playgrounds/Response_CN.md`
- 关联技能：`personal-logic-adversary`

## Failure Modes
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- 严禁在最终报告中保留 `[Link]`、`[URL]` 或其他占位符链接。
- 若顶级正刊不足或证据断层，必须显式触发补位流程，而不是直接生成低密度输出。

## Output Contract
- 最终战报必须包含 Top 10-15 文献、RWE/TRL 审计结果，以及每个 L4 信号对应的研发预研任务和销售防御话术。
- 报告必须使用 `assets/report_template.md` 输出，并完成归档与证据节点标注。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "hit-lectures-scout", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`
