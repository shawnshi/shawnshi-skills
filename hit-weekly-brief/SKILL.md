name: hit-weekly-brief
description: 医疗行业战区研报中枢 (V5.0)。当用户询问“本周麦肯锡研报”、“数字医疗白皮书”或需要“生成周报”时，务必激活。该技能基于《龙虾教程》五层价值链重构，集成跨界 Serendipity 注入、非共识 Contrarian 对抗与黑板模式协作，交付高信噪比、具备决策优势的战略资产。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

# SKILL.md: HIT Weekly Brief (行业战区周报) V5.0

> **Version**: 5.0 (Lobster Architecture x Strategic Advantage)
> **Vision**: 消除智库研报中的“共识幻觉”与“信息茧房”。系统不仅聚合顶级咨询结论，更通过“二跳推理”与“跨界注入”识别被主流忽略的破坏性信号。

## 0. 核心架构约束 (The 5-Layer Value Chain)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (异步侦察)**: Phase 1 强制并行触发 3 个 Subagent，隔离实时搜索噪音。
- **Inversion (窗口对齐)**: Phase 1 自动计算滑动窗口日期，信息不足触发战略补位。
- **Generator (三维降维)**: 强制将情报归类为 [技术演进]、[安全与合规]、[资本与政策]。
- **Pipeline (流程硬锁)**: 严格按 S-I-A (Signal-Insight-Action) 框架执行。
- **Reviewer (非共识对抗)**: Phase 3 强制执行“反向验证”，搜索与主流智库相反的证据。

### 0.2 龙虾架构增强
1.  **感知层 (Sense)**: 集成 `history_manager.py`，执行 **SemHash (语义去重)**。拒绝复读上周已推送过的旧白皮书摘要。
2.  **个性化层 (Serendipity)**: 在 Phase 1 侦察中，**强制预留 10% 算力配额**执行“跨界扫描”。检索金融、物流或军工领域的 AI 架构报告，寻找与医疗 IT 同构的底层启发。
3.  **关联层 (Connect)**: 激活 **Weaver (织者)**。将不同智库的零散预测进行“黑板化”串联，识别“非共识信号”。
4.  **激活层 (Activate)**: **Format Stack (分层交付)**。顶部强制注入 10s 紧急预警，正文强制包含“战略教练指令”。

## 1. 启动序列与边界 (Boot Sequence)
- **时间锚点**: 默认计算过去 7 天。若核心资讯不足 5 条，必须回溯至 14 天执行“战略补位”。

## 2. 核心工作流 (Blackboard Protocol)

### Phase 1: 分层侦察与 Serendipity 注入 [Mode: PLANNING]
1. **Initialize Blackboard**: 创建 `tmp/intelligence_blackboard.json` 共享状态。
2. **Orchestrator 并发调度**:
   - `strategy_scout`: 麦肯锡、波士顿等顶级咨询 PDF/报告。
   - `policy_scout`: 卫健委、WHO 及数据局红头文件。
   - **`serendipity_scout` (跨界注入)**: 扫描非医疗高精尖行业（如 FinTech/Defense）的 AI 治理白皮书。
3. **SemHash 拦截**: 剔除过去 14 天已推送的内容。

### Phase 2: 主轴提炼与 Weaver 关联 [Mode: EXECUTION]
1. **主轴定调**: 用一句话概括本周智库的“最大共识”与“最大隐忧”。
2. **Weaver 织网**: 将跨界报告的逻辑（如：金融级的低延迟交易审计）与医疗业务（如：手术机器人实时监控）进行二跳推理。

### Phase 3: Contrarian 对抗与 Reviewer 审计 [Mode: VERIFICATION]
1. **非共识对抗**: 必须调用 `logic-adversary`。**强制要求**寻找一份与本周麦肯锡/Gartner 主推共识**完全相反**的数据报告或专家评论，防止高管决策中的“回声室效应”。
2. **Binary Eval (二元硬审计)**:
   - [ ] 是否包含至少一个“非医疗行业”的跨界启发？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售话术或打法转换价值？ [Yes/No]

### Phase 4: 激活交付与自愈 (Self-Healing) [Mode: EXECUTION]
1. **Format Stack 渲染**: 生成具备“高压迫感”的战略简报。
2. **物理归档**: `{root}\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`。
3. **技能自愈**: 若审计发现“智库复读”现象，将拦截逻辑回写至 `## Gotchas`。

## 3. 输出格式铁律 (Format Stack)

```markdown
# 全球数字健康智库周报 - [YYYY-MM-DD]
> **本周战略主轴**：[极具统摄力的共识概括]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[共识偏离/突发威胁]**: [建议防御动作]

## I. 织者洞察 (Serendipity View)
- **跨界启发**: [来自金融/军工等行业的逻辑映射]
- **So What**: [对卫宁 MSL/ACE 的物理启示]

## II. 行业深度解读 (3D Analysis)
### 1. 技术演进 (Fact -> Insight -> Contrarian)
- **主流共识**: [Fact]
- **非共识挑战**: [Contrarian Data/Argument]

### 2. 安全与合规
### 3. 资本与政策

## III. 战略教练指令 (Directives)
- [针对高管的决策建议]
- [针对销售线的战术话术]
```

## 4. 历史失效先验 (Gotchas)
- DO NOT list more than 7 reports; SELECT only for high Signal-to-Noise Ratio.
- **[CRITICAL]** ALWAYS include at least one "Contrarian" viewpoint to challenge the main consensus.
- **[CRITICAL]** NO "Serendipity" = NO PUSH. Every brief must have one cross-domain insight.
- ELIMINATE marketing buzzwords; USE cold, ROI-driven business language.
