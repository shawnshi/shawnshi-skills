---
name: digital-health-lectures-scout
description: 当用户询问有关数字健康研究或医疗 AI 论文时触发。**主Agent将扮演 Orchestrator (指挥官)，并行调用 4 个内置 Subagents (global_sci_scout, clinical_scout, china_local_scout, preprint_scout)**。它会汇总子 Agent 的情报，并应用基于“卫宁健康”战略和 DRG/合规情况的 S-T-C 和技术成熟度等级 (TRL) 评估框架。
triggers: ["检索医疗AI论文", "扫描本周前沿探索", "Nature最新数字化研究", "JAMA医疗前沿", "科研哨兵扫描", "分析医疗大模型突破", "医疗AI论文", "Nature/JAMA研究", "医疗前沿创新"]
tools: [global_sci_scout, clinical_scout, china_local_scout, preprint_scout]

---

# SKILL.md: Digital Health Intel Scout V3.0 (医疗数字化战略侦察兵)

## 0. 工程纪律 (Engineering & GEB-Flow)
生成的每一份报告，顶部**必须**包含 YAML 元数据 (Title, Date, Status, Author, Tags, Target_Component)，以支持在 `MEMORY` 库中的后续 RAG 检索。

## 1. 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **触发指令**: 当用户提及“医疗 AI 论文”、“本周前沿探索”、“Nature/JAMA 最新数字化研究”或任何需要深度科研扫描的请求时，强制激活此技能。
- **默认视窗**: **过去7天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7天内的核心科研突破数少于 5 篇，则**必须自动将检索视窗扩大至过去14 天**。

## 2. 核心工作流 (The Research Cycle)

### 第一阶段：并发调度与 Lateral Search (Parallel Subagent Recon)
*指令：你现在是 Orchestrator。Gemini CLI 已经为你注册了 4 个专门的 Subagent 工具。你必须利用并行函数调用机制，同时触发这 4 个工具。*

1. **并行分发与横向扩展 (Lateral Expansion)**: 向 4 个 Subagent 传入7天日期窗口，并要求它们不仅盯着顶级站点，还要关注 ResearchGate、Google Scholar 上的高引用二阶信号。
2. **全局提纯与逻辑补位 (Aggregation & Trend Sensing)**:
   - 等待所有数据回传。
   - **战略分流**: 筛选 Top 5-7 篇核心文献进行深度 TRL 脱水。
   - **逻辑补位**: 若顶级正刊论文不足，**必须**从 `preprint_scout` 中提取 5个正处于“算法打榜”阶段的热点趋势进行补充，确保简报的信息密度。

### 第三阶段：中国重力场与卫宁战略推演 (Strategic Deduction)
- **执行**：依据 `references/strategic_deduction.md`，执行 DRG 2.0 压测。
- **逻辑补充**：即便在缺乏“临床可用”级研究时，也必须针对“算法打榜”阶段的趋势，推演其对卫宁 MSL / ACE 底座的潜在防御性布局建议。

## 3. 输出格式铁律 (Formatting Ironballs)

---
## 🏆 战略核弹文献 (Top Pick & Strategic Deep Dive)
### 论文概要
来源阵地、发布日期、主导机构、数据锚点[URL]、论文摘要（500字）
#### 1. 技术硬脱水 (Tech Core & TRL)
#### 2. 中国实战压测 (China Localization Test)
#### 3. 卫宁架构映射 
*(重复以上结构)*
```

## 📚 视野外围扫描 (Radar Scan)
*（🔴 强约束：此处必须列出至少 10 篇文献，以确保情报覆盖的广度）*

### 1. [Title]
- **来源**: [Journal/Platform] | **日期**: [YYYY-MM-DD]
- **一句话战报**: [500字以内的高度浓缩，包括论文的摘要，以及对卫宁的借鉴意义。]
- **直达锚点**: [URL]

*(重复以上结构，直至满足 10 篇条目)*

## 📚 扫描论文清单 (Paper Scan)

### 1. [Title]
- **来源**: [BMJ / CMA / medRxiv 等] | **日期**: [YYYY-MM-DD]
- **一句话战报**: [100字以内的高度浓缩]
- **直达锚点**: [URL]

*(重复以上结构)*
```

## 🔴 红队对抗 (The Red Team Failsafe)


## 4. 归档与落盘 (Archiving)
1. **物理路径**: 生成结果强制保存在 `C:\Users\shich\.gemini\MEMORY\DigitalHealthLecturesScout`。
2. **文件命名**: `Weekly_DigitalHealth_[YYYYMMDD].md`。

---
*Optimized following Gemini Skill Creator Best Practices (V3.0 Framework).*
