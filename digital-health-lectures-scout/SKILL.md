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
- **默认视窗**: 本周（当前周一至周日）。
- **弹性降维 (Rolling Window)**: 若本周核心期刊的科研突破数返回为空（Zero-hit），则**必须自动将检索视窗扩大至过去 30 天**，确保输出高信噪比的情报。

## 2. 核心工作流 (The Research Cycle)

_指令：必须使用大模型联网搜索能力。在执行抽取与推演时，请务必查阅并严格遵循 `references/strategic_deduction.md` 中的判定标准。_

### 第一阶段：第一阶段：并发调度子Agent与情报降噪 (Parallel Subagent Recon)
*指令：你现在是 Orchestrator。Gemini CLI 已经为你注册了 4 个专门的 Subagent 工具。你必须利用并行函数调用（Parallel Function Calling）机制，**同时触发**这 4 个工具，让它们独立完成不同领域的情报搜集。*

1. **并行分发 (Dispatch)**: 向以下 4 个 Subagent 传入目标时间窗口（如“过去7天”），强制要求它们开始检索并返回结果：
   - 调用工具 `global_sci_scout`
   - 调用工具 `clinical_scout`
   - 调用工具 `china_local_scout`
   - 调用工具 `preprint_scout`

2. **全局降噪与提纯池 (Aggregation & Deduplication)**:
   - 等待所有子 Agent 执行完毕并回传数据。
   - **交叉去重**: 严格比对结果，剔除不同来源报道的同一项研究（尤其注意剔除 Pre-print 转正发表的重复项）。
   - **战略分流**: 从 4 个维度的混合情报池中，强制筛选出 **Top 3-5 篇最具颠覆性或最接近商业变现能力**的核心文献，进入第二阶段进行 TRL 脱水。剩余的全部降级，移入最终报告的“视野外围扫描 (Radar Scan)”。

### 第二阶段：技术脱水与成熟度判定 (TRL Extraction)
- **要求**：绝不照抄摘要。提取硬指标（样本量 N, AUC 准确率, 实验设计阶段）。
- **执行**：依据 `references/strategic_deduction.md`，强制将其归类为 `[纸面概念 | 算法打榜 | 临床可用]` 三个阶段之一。

### 第三阶段：中国重力场与卫宁战略推演 (Strategic Deduction)
- **要求**：代入卫宁健康高管视角。
- **执行**：依据 `references/strategic_deduction.md`，严厉拷问该技术在 DRG 2.0 时代的真实商业价值（OpEx/CapEx），以及合规壁垒（数据不出院、三类证）。最后，给出对卫宁 MSL / ACE 底座架构的防御或吸纳建议。

## 3. 输出格式铁律 (Formatting Ironballs)

**ALWAYS use this exact template pattern for the final output.**

```markdown
---
Title: "医疗数字化情报速递: [核心议题简称]"
Date: YYYY-MM-DD
Status: Done
Author: Digital Health Scout Agent
Tags: [AI, DigitalHealth, WiNEX, Intelligence]
Target_Component: [如: MSL / ACE / Logic Lake]
---

# 医疗数字化前沿战略简报 (Recon Window: [精确的起止日期])
> 视角: Winning Health Strategic Architect | 弹性视窗状态: [本周/过去30天]

## 🏆 战略核弹文献 (Top Pick & Strategic Deep Dive)
*（挑选 3-5 篇最具颠覆性或最接近商业变现能力的研究）*

### [论文中英文双语标题]
- **来源阵地**: [Journal Name] | **日期**: [YYYY-MM-DD]
- **主导机构**: [Institution/First Author]
- **数据锚点**: [真实的原链 URL]
- **论文摘要**: [500字左右论文摘要]

#### 1. 技术硬脱水 (Tech Core & TRL)
- **预判成熟度 (TRL)**: [纸面概念 / 算法打榜 / 临床可用]
- **支撑硬核数据**: [例如：N=50000, AUC=0.92, 跨院区双盲前瞻实验]
- **极简干货 (Summary)**: [200字内，不带任何废话的技术原理阐释]
- **完整性盲点**: [标明是全本阅读还是仅根据 Abstract 盲猜]

#### 2. 中国实战压测 (China Localization Test)
- **DRG 控费杠杆**: [增加医院负担，还是降低 ALOS？]
- **合规生死线**: [依赖公有云的死穴？三类器械证的门槛漫长？]

#### 3. 卫宁架构映射 (Winning Health Directives)
- **MSL/ACE 冲击波**: [对现存规则引擎的区别或降维打击在哪里？]
- **OpEx 商业演进推演**: [24个月内的变现路径猜想]

#### 4. 🔴 红队对抗 (The Red Team Failsafe)
- **算力灾难与医疗毒性**: [在什么长尾临床边缘情境下，这套系统会杀人或崩溃？]

---

## 📚 视野外围扫描 (Radar Scan)
*（若当期论文极多，选取 7-10 篇列于此处；要求一针见血）*

### 1. [Title]
- **来源**: [BMJ / CMA / medRxiv 等] | **日期**: [YYYY-MM-DD]
- **一句话战报**: [100字以内的高度浓缩]
- **直达锚点**: [URL]

*(重复以上结构)*

## 📚 扫描论文清单 (Paper Scan)

### 1. [Title]
- **来源**: [BMJ / CMA / medRxiv 等] | **日期**: [YYYY-MM-DD]
- **一句话战报**: [50字以内的高度浓缩]
- **直达锚点**: [URL]

*(重复以上结构)*
```

## 4. 归档与落盘 (Archiving)
1. **物理路径**: 生成结果强制保存在 `C:\Users\shich\.gemini\MEMORY\DigitalHealthLecturesScout`。
2. **文件命名**: `Weekly_DigitalHealth_[YYYYMMDD].md`。

---
*Optimized following Gemini Skill Creator Best Practices (V3.0 Framework).*
