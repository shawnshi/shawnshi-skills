name: hit-weekly-brief
description: 医疗行业战区研报中枢 (V5.0)。当用户询问“本周麦肯锡研报”、“数字医疗白皮书”或需要“生成周报”时，务必激活。该技能基于《龙虾教程》五层价值链重构，集成跨界 Serendipity 注入、非共识 Contrarian 对抗与黑板模式协作，交付高信噪比、具备决策优势的战略资产。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

# SKILL.md: HIT Weekly Brief (行业战区周报) V5.0

> **Version**: 5.0 (Lobster Architecture x Strategic Advantage)
> **Vision**: 消除智库研报中的“共识幻觉”与“信息茧房”。系统不仅聚合顶级咨询结论，更通过“二跳推理”与“跨界注入”识别被主流忽略的破坏性信号。

## 0. 核心架构约束 (The 5-Layer Value Chain)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (异步侦察)**: Phase 1 强制并行触发 4 个 Subagent，隔离实时搜索噪音。
- **Inversion (窗口对齐)**: Phase 1 自动计算滑动窗口日期，信息不足触发战略补位。
- **Generator (三维降维)**: 强制将情报归类为 [技术演进]、[安全与合规]、[资本与政策]。
- **Pipeline (流程硬锁)**: 严格按 S-I-A (Signal-Insight-Action) 框架执行。
- **Reviewer (非共识对抗)**: Phase 3 强制执行“反向验证”，搜索与主流智库相反的证据。

### 0.2 龙虾架构增强
1.  **感知层 (Sense)**: 依靠原生 `grep_search` 扫描 `MEMORY/DigitalHealthWeeklyBrief` 执行语义去重 (SemHash)。拒绝复读上周已推送过的旧白皮书摘要。
2.  **个性化层 (Serendipity)**: 在 Phase 1 侦察中，**强制预留 10% 算力配额**执行“跨界扫描”。检索金融、物流或军工领域的 AI 架构报告，寻找与医疗 IT 同构的底层启发。
3.  **关联层 (Connect)**: 激活 **Weaver (织者)**。将不同智库的零散预测进行“黑板化”串联，识别“非共识信号”。
4.  **激活层 (Activate)**: **Format Stack (分层交付)**。顶部强制注入 10s 紧急预警，正文强制包含“战略教练指令”。

## 0.5 Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat, long-running pipelines (e.g., scraping multiple URLs, parsing heavy PDFs, or filtering high-noise feeds) MUST NOT be executed directly in the main memory.
1. **Packet Creation**: Before starting a heavy ingestion task, write the specific parameters, source URLs, or target documents to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Digestion_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist` or a dedicated reader) to consume the packet, execute the heavy scraping/extraction, and write the purified output back to a designated result file.
3. **Suspension**: The main agent must suspend execution, wait for the sub-agent to complete the task, and then read ONLY the final synthesized result file to continue formatting the weekly brief.

## 1. 启动序列与边界 (Boot Sequence)
- **时间锚点**: 默认计算过去 7 天。若核心资讯不足 5 条，必须回溯至 14 天执行“战略补位”。

## 2. 核心工作流 (Blackboard Protocol)

### Phase 1: 物理沙盒切分与子代理并发 (Map-Reduce Delegation) [Mode: PLANNING]
0. **Initialize Blackboard**: 创建 `tmp/intelligence_blackboard.json` 共享状态。
 1. **构建物理任务包 (Task Packetization)**: 必须通过 `write_file` 在 `tmp/playgrounds/` 下生成四个独立的结构化指令包：
 - `Task_strategy.md`: 目标锚定 McKinsey, BCG, Bain, Deloitte, PwC 最新研报。必须使用 `google_web_search` 和 `web_fetch` 交叉验证发布日期。提取战略信号。
 - `Task_policy.md`: 目标锚定 WHO, RAND, World Bank, OECD, ONC 等发布的公共卫生、数据隐私及医疗互联互通政策报告。必须使用 `web_fetch` 验证日期。
 - `Task_tech.md`: 目标锚定 Gartner, IDC, Forrester, Accenture 等 IT 智库本周发布的医疗技术、架构与 AI 趋势报告。聚焦技术落地成熟度。
 - `Task_serendipity.md`: 目标锚定非医疗高精尖行业（如 FinTech/Defense）对医疗有借鉴价值的技术白皮书。
 2. **集群并发调度 (Concurrent Dispatch)**: 并发调用 4 次 `generalist` 子代理。将对应的 Task 文件路径作为 Payload 传入。**指令硬锁**：“保持极低的创造力，仅做事实搬运。禁止输出多余废话，仅交付包含 DOI/链接、核心事实与初步 TRL 评级的硬核数据。必须调用 `web_fetch` 物理验证报告日期是否在本周（或过去14天）。”。要求子代理将结果分别写入 `tmp/playgrounds/Response_strategy.md`, `Response_policy.md`, `Response_tech.md`、`Response_serendipity.md`。
 3. **逻辑补位**: 若顶级正刊论文不足，必须提取热点趋势补齐信息密度。
 4. **资产回收与 SemHash 拦截 (Harvest & Intercept)**: 主代理读取四个 `Response` 文件。调用 `grep_search` 或 `vector-lake search` 扫描本地 `MEMORY/DigitalHealthWeeklyBrief` 历史战报执行去重。确认未与过去 14 天的历史报告重复后，将合并后的高纯度信息推入数字黑板，随后清扫 `tmp/playgrounds/` 下的中间产物。

### Phase 2: 主轴提炼与 Weaver 多跳关联 [Mode: EXECUTION]
1. **主轴定调**: 用一句话概括本周智库的“最大共识”与“最大隐忧”。
2. **Weaver 织网**: 将跨界报告的逻辑（如：金融级的低延迟交易审计）与医疗业务（如：手术机器人实时监控）进行二跳推理。
3. **Memory Interleave (MSA 增强)**: 若发现跨界启示与卫宁本地技术现状的结合点存在“工程逻辑空白”，**强制执行以下命令调用向量湖**：
   `python C:\Users\shich\.gemini\extensions\vector-lake\cli.py query "[你的推演指令]" --interleave`
   通过递归回溯 L3 级冷库（如过往架构设计、HIS/EMR 重构记录），确认跨界逻辑的可落地性。

### Phase 3: Contrarian 对抗与多跳审计 [Mode: VERIFICATION]
1. **非共识对抗**: 必须调用 `personal-logic-adversary`。**强制要求**寻找一份与本周麦肯锡/Gartner 主推共识**完全相反**的数据报告或专家评论。优先通过向量湖在本地库中寻找“曾遭遇的相反教训”。
2. **Binary Eval (二元硬审计)**:
   - [ ] 是否包含至少一个“非医疗行业”的跨界启发？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售话术或打法转换价值？ [Yes/No]

### Phase 4: 交付与元数据审计 (Deliver & Persistence) [Mode: EXECUTION]
1. **强制加载模板**: 读取 `resources/template.md` 模板文件和 `examples/DHWB-Reference.md` 参考战报，强制对其排版风格和业务深度进行基准对齐。
2. **元数据完整性审计 (Metadata Integrity Audit)**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]`、`[URL]` 或任何占位符。必须逐一校验引用报告的 DOI、发布日期与原始地址。若元数据缺失，必须调用 `google_web_search` 执行二次定向爬取，确保证据链 100% 闭环。
3. **Format Stack 渲染**: 生成具备“高压迫感”的战略简报。确保每一条战略建议均挂载了精确的 `[Ref: Evidence_Node_ID]`。
4. **物理归档**: 使用 `write_file` 保存至 `C:\Users\shich\.gemini\MEMORY\\raw\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`。
5. **技能自愈**: 将元数据缺失或共识幻觉的失败先验回写至 `## Gotchas`。

## 3. 输出格式铁律 (Format Stack)
（详细排版见 `resources/template.md`。必须严格遵守 S-I-A 战略推演框架和 GitHub Alerts 视觉呈现。）

## 4. Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "hit-weekly-brief", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 5. 历史失效先验 (NLAH Gotchas)
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- `IF [Action == "Select Reports"] THEN [Halt if Count > 7] AND [Require High Signal-to-Noise Ratio]`
- `IF [Section == "Main Consensus"] THEN [Require >= 1 "Contrarian" Viewpoint]`
- `IF [Action == "Publish Brief"] THEN [Halt if lacks "Cross-domain Insight (Serendipity)"]`
- `IF [Report contains ("[Link]" OR "[URL]")] THEN [Halt Execution] AND [Require execute(google_web_search) for Verified Source]`
- `IF [Content contains "Marketing Buzzwords"] THEN [Halt] AND [Require "Cold, ROI-driven Business Language"]`