---
name: hit-lectures-scout
description: 医疗数字化前沿侦察兵。当用户询问“医疗AI最新论文”、“Nature/JAMA研究动态”或“科研前沿趋势”时，务必激活。该技能并行调用 4 个专业侦察兵，通过 S-T-C 框架对论文成熟度（TRL）执行硬核评估。
triggers: ["检索医疗AI论文", "扫描本周前沿探索", "Nature最新数字化研究", "JAMA医疗前沿", "科研哨兵扫描", "分析医疗大模型突破", "医疗AI论文", "Nature/JAMA研究", "医疗前沿创新"]
---

# SKILL.md: HIT Intel Scout V3.0 (医疗数字化战略侦察兵)

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
   - **战略分流**: 筛选 Top 5-10 篇核心文献进行深度 TRL 脱水。
   - **逻辑补位**: 若顶级正刊论文不足，**必须**从 `preprint_scout` 中提取 5个正处于“算法打榜”阶段的热点趋势进行补充，确保简报的信息密度。

### 第三阶段：中国重力场与卫宁战略推演 (Strategic Deduction)
- **执行**：依据 `references/strategic_deduction.md`，执行 DRG 2.0 压测。
- **逻辑补充**：即便在缺乏“临床可用”级研究时，也必须针对“算法打榜”阶段的趋势，推演其对卫宁 MSL / ACE 底座的潜在防御性布局建议。

## 3. 输出格式铁律 (Formatting Ironballs)

---
## 🎯 本周核心情报速递 (Executive Signals)
> *[用一段冷峻、精炼的话，总结本周学术界释放的最强收敛性信号。例如：本周医疗人工智能正全面从“实验室Demo”转向“真实世界工作流”，核心矛盾集中于人机交互的信任赤字。]*

| 刊物 | 核心标题 | 战略概述 (1句话) | 链接 |
|:---|:---|:---|:---|
| [Nature/JAMA等] | [Title] | [提炼核心洞察，如：揭示了交互透明度对医生信任的核心影响] | [URL] |
*(列出本周 Top 5-7 的核心论文)*

---
## 🔬 深度解剖：[填写本周核心现象/主题，如：AI助理的“交互坍塌”]
*选中论文：[核心论文标题] ([期刊], [日期])*

### A. 核心逻辑解构 (Core Logic & Attrition)
- **现象/悖论**：[提炼论文中揭示的反常识现象或物理边界，使用数据对比支撑]
- **底层归因**：[使用第一性原理或系统动力学解释失败/成功的原因，如：特征工程缺失、意图偏移]

### B. 卫宁健康战略支点 (Winning Health Strategic Pivot)
- **底层底座映射 (MSL/ACE)**：[放弃对Chat的幻想，说明该情报对卫宁医疗语义层(MSL)或Agent编排引擎的启示]
- **产品护城河 (WiNEX/WinDAN)**：[说明如何通过“由医生监管的AI(Human-in-the-loop)”或隐形感知构建防御]

### C. 阻力测算与二阶效应 (The 2nd Order Effects)
- **合规/法律黑洞**：[推演新技术可能带来的伪信任或法律责任边界模糊]
- **算力与架构压测**：[讨论边缘云需求、算力枯竭或联邦学习的必要性]

---
## 📡 视野外围扫描 (Radar Scan)
*(高密度罗列本周其他 5-10 篇值得关注的文献，仅保留：刊物、一句话战报、URL)*
1. **[刊物]**：[Title] - [一句话说明其边际增量]。[URL]

---
## ⚔️ 周度指挥官指令 (Commander's Directives)
*基于本周情报，向卫宁战略或研发体系下达 1-2 条执行调整指令：*
- **建议动作 1**：[例如：建议WiNEX研发中心评估AI助手的交互模式，从“开放提问”转向“结构化信息过滤”。]
- **风险规避**：[防范何种技术陷阱]

## 4. 归档与落盘 (Archiving)
1. **物理路径**: 生成结果强制保存在 `C:\Users\shich\.gemini\MEMORY\DigitalHealthLecturesScout`。
2. **文件命名**: `Weekly_DigitalHealth_[YYYYMMDD].md`。

---
*Optimized following Gemini Skill Creator Best Practices (V3.0 Framework).*
