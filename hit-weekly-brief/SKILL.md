---
name: hit-weekly-brief
description: 医疗行业战区研报中枢 (V5.2)。Primary owner for weekly think-tank, consulting, and whitepaper briefs in healthcare or digital health. Use for McKinsey/BCG/Gartner-style report digestion and weekly strategic brief generation. Prefer hit-industry-radar for market-news/event scans and hit-lectures-scout for academic or clinical paper scouting.
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

<strategy-gene>
Keywords: 数字健康周报, 智库研报, 二跳推理, 跨界注入
Summary: 聚合顶级智库研报并执行 Contrarian (逆向) 对抗分析，识别被主流忽略的破坏性信号。
Strategy:
1. 四维度扫描：并行调度策略、技术、政策、跨界（FinTech/军工）四条管线。
2. 织者关联：将零散预测串联为系统级规律，执行与卫宁技术的结合点推理。
3. 非共识对抗：强制寻找与主流研报相反的证据，识别“共识幻觉”。
4. 强制双链图谱与双轨落盘：对核心企业、人物或专有名词必须使用 `[[ ]]` 进行硬链接；若是长效落盘，必须遵守 Compiled Truth | Timeline 上下分割规范。
AVOID: 严禁重复 14 天内的旧报；禁止包含无 ROI 支撑的营销废话；禁止漏掉跨界启发模块；严禁越界将原始抓取数据写入核心图谱；严禁在报告中遗漏重要实体的双链标记。
</strategy-gene>

# SKILL.md: HIT Weekly Brief (行业战区周报) V5.2

> **Version**: 5.2 (Lobster Architecture x Antigravity Subagents)
> **Vision**: 消除智库研报中的“共识幻觉”与“信息茧房”。系统不仅聚合顶级咨询结论，更通过“二跳推理”与“跨界注入”识别被主流忽略的破坏性信号。

## When to Use
- 当用户要求生成数字健康周报、扫描本周智库/白皮书、或提炼医疗行业周度战略信号时使用。
- 目标是交付带非共识视角和行动建议的周报，不是简单罗列报告目录。

## Workflow

### 核心架构约束 (The 5-Layer Value Chain)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (异步侦察)**: Phase 1 强制并行触发 4 个 Subagent，隔离实时搜索噪音。
- **Inversion (窗口对齐)**: Phase 1 自动计算滑动窗口日期，信息不足触发战略补位。
- **Generator (三维降维)**: 强制将情报归类为 [技术演进]、[安全与合规]、[资本与政策]。
- **Pipeline (流程硬锁)**: 严格按 S-I-A (Signal-Insight-Action) 框架执行。
- **Reviewer (非共识对抗)**: Phase 3 强制执行“反向验证”，搜索与主流智库相反的证据。

### 0.2 龙虾架构增强
1.  **感知层 (Sense)**: 依靠原生 `vector-lake search` 扫描历史数据执行语义去重 (SemHash)。拒绝复读上周已推送过的旧白皮书摘要。
2.  **个性化层 (Serendipity)**: 在 Phase 1 侦察中，**强制预留 10% 算力配额**执行“跨界扫描”。检索金融、物流或军工领域的 AI 架构报告，寻找与医疗 IT 同构的底层启发。
3.  **关联层 (Connect)**: 激活 **Weaver (织者)**。将不同智库的零散预测进行“黑板化”串联，识别“非共识信号”。
4.  **激活层 (Activate)**: **Format Stack (分层交付)**。顶部强制注入 10s 紧急预警，正文强制包含“战略教练指令”。

### Subtask Packaging Protocol (Antigravity Native)
**CRITICAL RULE**: 为应对研报处理的海量 Token 消耗，必须使用原生 `invoke_subagent` 执行并发清洗。绝对禁止主代理在当前上下文挂起并顺序阅读大量长篇 PDF。

### 启动序列与边界 (Boot Sequence)
- **时间锚点**: 默认计算过去 7 天。若核心资讯不足 5 条，必须回溯至 14 天执行“战略补位”。

### 核心工作流 (Blackboard Protocol)

### Phase 1: 四路并发原生沙盒扫描 (Native Concurrent Map-Reduce) [Mode: PLANNING]
0. **Initialize Blackboard**: 在主代理内存中建立认知黑板，无需依赖物理临时文件。
1. **获取沙盒指令**: 读取本技能 `assets/` 目录下的静态指令包以获取四条核心管线的侦察意图和强制 Schema：
   - `assets/Task_strategy.md`: 顶级智库战略分析
   - `assets/Task_policy.md`: 公卫与合规政策分析
   - `assets/Task_tech.md`: 医疗技术与架构趋势
   - `assets/Task_serendipity.md`: 跨界技术架构注入
2. **集群并发调度 (Concurrent Dispatch)**: 主代理必须直接调用 `invoke_subagent` 工具，并发拉起 4 个 `research` 类型的子代理，将上述 4 份指令的内容作为 `Prompt` 悉数发出。
3. **挂起与回调**: 主代理原地静默挂起。等待四个维度的子代理在独立沙盒中完成全文提纯后，利用系统回调回收包含 DOI、核心事实与 TRL 评级的硬核数据块。
4. **逻辑补位与图谱语义去重**: 若顶级智库报告不足，主动提取热点趋势补齐信息密度。随后调用 `mcp_vector-lake-mcp_search_vector_lake` (Mode: claim/page) 扫描图谱防重。确认未与过去 14 天的历史报告重复后，将数据推入数字黑板。

### Phase 2: 概念化用与多跳关联 (Semantic Translation & Weaver) [Mode: EXECUTION]
1. **主轴定调**: 用一句话概括本周智库的“最大共识”与“最大隐忧”。
2. **概念化用 (Semantic Translation)**: **[强制约束]** 废除孤立的跨界拼接。在解读非医疗行业报告（如金融审计、通用AI、网络安全）时，禁止使用通用语言。必须将其核心概念 1:1 翻译为医疗 IT 实景实体。例如：将“边缘计算”翻译为“床旁监护终端流式分析”；将“统一治理失败”翻译为“临床决策Agent与后勤Agent的权限隔离”。
3. **Weaver 织网**: 将跨界报告的逻辑顺滑映射到医疗业务（如：手术机器人实时监控、HIS灾备）进行二跳推理。
4. **Memory Interleave (原生 MCP 增强)**: 若发现跨界启示与核心产品（如卫宁 WiNEX）的结合点存在“工程逻辑空白”，**强制调用原生图谱探针**：
   直接使用工具 `mcp_vector-lake-mcp_query_logic_lake` 查询过往架构设计、HIS/EMR 重构记录，通过 L3 级冷库回溯确认跨界逻辑的可落地性。禁止使用原生 Shell 拼凑查询。

### Phase 3: Contrarian 对抗与多跳审计 [Mode: VERIFICATION]
1. **非共识对抗**: 必须调用 `cognitive-logic-adversary`。**强制要求**寻找一份与本周麦肯锡/Gartner 主推共识**完全相反**的数据报告或专家评论。优先通过向量湖在本地库中寻找“曾遭遇的相反教训”。
2. **Binary Eval (二元硬审计)**:
   - [ ] 是否包含至少一个“非医疗行业”的跨界启发？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售话术或打法转换价值？ [Yes/No]

### Phase 4: 全局叙事缝合与渲染草稿 (Narrative Synthesis & Draft) [Mode: EXECUTION]
1. **强制加载模板**: 读取 `resources/template.md` 模板文件和 `examples/DHWB-Reference.md` 参考战报，强制对其排版风格和业务深度进行基准对齐。
2. **全局叙事缝合 (Storylining)**: 先从收集的情报中提取 3-4 个统摄全篇的医疗原生术语（如 Medical Semantic Layer, Ambient Copilots, Logic Lake）。在后续生成章节时，必须向这几个核心概念“收敛”，形成首尾呼应的战报闭环，避免多代理并发带来的报告“碎片化”。
3. **元数据完整性审计 (Metadata Integrity Audit)**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]`、`[URL]` 或任何假链接。必须使用网页浏览工具逐一校验引用报告的真实性。
4. **Format Stack 渲染草稿**: 生成具备“高压迫感”的战略简报草稿。开局必须抛出包含全量情报（含非医疗报告）的“全球顶尖智库发布雷达”表。确保每一条战略建议均挂载精确的 `[Ref: Evidence_Node_ID]`，并将商业策略切实转化为“销售话术转译”与“研发架构落地”。将草稿强制写入临时文件 `C:/Users/shich/.gemini/tmp/draft_hit_brief.md`。

### Phase 5: The Hard Gate 与异步图谱生态入湖
1. **跨平台防爆审计**: 调用 shell 执行，并在命令头强制挂载中文字符集声明以避免输出崩溃：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/hit_audit_gate.py" "C:/Users/shich/.gemini/tmp/draft_hit_brief.md" --mode brief`
2. **处理失败**: 若审计报错（如未发现非共识观点/跨界启发，或残留营销水词），必须退回 Phase 4 修正草稿。最多重试 2 次。
3. **物理归档**: 脚本返回 `Audit Passed` 后，使用 `write_file` 保存至 `C:/Users/shich/.gemini/MEMORY/raw/DigitalHealthWeeklyBrief/DHWB-YYYYMMDD.md`。
4. **知识异步入湖 (Async Graph Ingestion)**：
   - 主代理甄别战报中的“非共识观点”等高价值战略实体，利用 `write_file` 将其转化存储入 `C:/Users/shich/.gemini/MEMORY/wiki/Entity_*.md` 节点中。
   - **绝对禁令**: 严禁直接调用阻塞式 `sync_vector_lake`。
   - **异步同步**: 必须调用 `mcp_vector-lake-mcp_prepare_ingest_batch` 提取变更队列，随后利用 `invoke_subagent` 拉起 `vector-lake-ingestor` 执行后台异步摄入。
5. **技能自愈**: 将元数据缺失或共识幻觉的失败先验回写至 `## Gotchas`。

## Resources
- `resources/template.md`
- `examples/DHWB-Reference.md`
- `assets/Task_strategy.md`
- `assets/Task_policy.md`
- `assets/Task_tech.md`
- `assets/Task_serendipity.md`
- 关联技能：`cognitive-logic-adversary`

## Failure Modes
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- `IF [Action == "Select Reports"] THEN [Halt if Count > 7] AND [Require High Signal-to-Noise Ratio]`
- `IF [Section == "Main Consensus"] THEN [Require >= 1 "Contrarian" Viewpoint]`
- `IF [Action == "Publish Brief"] THEN [Halt if lacks "Cross-domain Insight (Serendipity)"]`
- `IF [Report contains ("[Link]" OR "[URL]")] THEN [Halt Execution] AND [Require verified search/browse before delivery]`
- `IF [Content contains "Marketing Buzzwords"] THEN [Halt] AND [Require "Cold, ROI-driven Business Language"]`

## Output Contract
- （详细排版见 `resources/template.md`。必须严格遵守 S-I-A 战略推演框架和 GitHub Alerts 视觉呈现。）
- 最终周报必须包含本周主轴、至少一个跨界启发、至少一个 Contrarian 观点，以及可转译为销售/战略动作的结论。
- 所有引用都必须去占位符并完成元数据校验。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:/Users/shich/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "hit-weekly-brief", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 5. 历史失效先验 (NLAH Gotchas)
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- `IF [Action == "Select Reports"] THEN [Halt if Count > 7] AND [Require High Signal-to-Noise Ratio]`
- `IF [Section == "Main Consensus"] THEN [Require >= 1 "Contrarian" Viewpoint]`
- `IF [Action == "Publish Brief"] THEN [Halt if lacks "Cross-domain Insight (Serendipity)"]`
- `IF [Report contains ("[Link]" OR "[URL]")] THEN [Halt Execution] AND [Require verified search/browse before delivery]`
- `IF [Content contains "Marketing Buzzwords"] THEN [Halt] AND [Require "Cold, ROI-driven Business Language"]`
