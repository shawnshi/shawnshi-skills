---
name: hit-weekly-brief
description: 医疗行业战区研报中枢 (V4.0)。当用户询问“本周麦肯锡研报”、“数字医疗白皮书”或需要“生成周报”时，务必激活。该技能通过 ADK 五维补偿架构与 S-I-A 战略推演，将噪音降维为高管视角的抗幻觉决策资产。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

# SKILL.md: HIT Weekly Brief (行业战区周报) V4.0

> **Version**: 4.0 (ADK 5-Patterns x Strategic Deduction)
> **Vision**: 将碎片化的全球智库动态降维打击，交付可以直接用于高管决策的 Alpha 级情报。通过结构化补偿消除 LLM 的描述性膨胀。

## 0. 核心架构约束 (Core Mandates)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (异步侦察)**: Phase 1 强制并行触发 3 个 Subagent，隔离实时搜索噪音。
- **Inversion (窗口对齐)**: Phase 1 自动计算滑动窗口日期，信息不足触发战略补位。
- **Generator (三维降维)**: 强制将情报归类为 [技术演进]、[安全与合规]、[资本与政策]，输出严格遵循 Markdown 铁律。
- **Pipeline (时序流转)**: 严格按 S-I-A (Signal-Insight-Action) 框架执行，禁止跳过战略建议环节。
- **Reviewer (二元校验)**: Phase 3 执行针对“信噪比”与“动作映射度”的二元硬审计。

## 1. 启动序列与边界 (Boot Sequence)
- **时间锚点**: 默认计算过去 7 天。若核心资讯不足 5 条，必须回溯至 14 天执行“战略补位”。

## 2. 核心工作流 (Execution Protocol)

### Phase 1: 分层侦察与 Inversion 拦截 [Mode: PLANNING]
1. **Orchestrator 并发调度**:
   - `strategy_scout`: 麦肯锡、波士顿等顶级咨询 PDF/报告。
   - `tech_scout`: Gartner、IDC 等技术趋势与架构。
   - `policy_scout`: WHO、世行及国内宏观政策。
2. **战略补位**: 若资讯量不足，强制从“政策咨询”与“行业研讨会纪要”中补齐。

### Phase 2: 主轴提炼与 Generator 降维 [Mode: EXECUTION]
1. **主轴定调**: 用一句话概括最核心共识（如：“代理式 AI 的实战化”）。
2. **3D Parsing**: 强制将所有 Fact 归入三维模型，禁止散点叙事。

### Phase 3: S-I-A 推演与 Reviewer 审计 [Mode: VERIFICATION]
1. **战略建议 (Action)**: 针对卫宁高管/销售线给出 3 条直接话术或打法。
2. **Binary Eval (二元硬审计)**:
   - [ ] 是否所有 Fact 均有权威机构背书？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售转化价值？ [Yes/No]
   - [ ] 是否剔除了所有形容词堆砌？ [Yes/No]

### Phase 4: 物理归档与自愈 (Self-Healing) [Mode: EXECUTION]
1. **路径**: `{root}\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`。
2. **技能自愈**: 将修正后的逻辑（如：拒绝重复抓取过时白皮书）回写至 `## Gotchas`。

## 3. 输出格式铁律 (Formatting Ironballs)

```markdown
# 全球数字健康智库周报 - [YYYY-MM-DD 至 YYYY-MM-DD]
> **本周战略主轴**：[极具统摄力的共识概括]

## I. 核心资讯一览 (Top Signals)
| 机构 | 报告名称 | 核心摘要 |
|:---|:---|:---|
| [McKinsey等] | [Title] | [1句话本质提取] |

## II. 行业深度解读 (3D Analysis)
### 1. 技术演进：[趋势命名]
- **现象 (Fact)**：[数据支撑事实]
- **解读 (Insight)**：[底层逻辑]
- **场景映射**：[临床/运营位移]

### 2. 安全与架构
### 3. 资本与政策

## III. 战略教练指令 (Directives)
- [产品叙事/销售话术建议]
- [战略规划建议]
```

## 4. 历史失效先验 (Gotchas)
- DO NOT list more than 7 reports; SELECT only for high Signal-to-Noise Ratio.
- ALWAYS check the publication date of PDFs; IGNORE any report older than the defined window.
- ELIMINATE marketing buzzwords; USE cold, ROI-driven business language.
