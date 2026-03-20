---
name: hit-lectures-scout
description: 医疗数字化前沿侦察兵 (V4.0)。当用户询问“医疗AI最新论文”、“Nature/JAMA研究动态”或“科研前沿趋势”时，务必激活。该技能并行调用 4 个专业侦察兵，通过 ADK 五维补偿架构与 S-T-C 框架对论文成熟度（TRL）执行硬核评估与自愈迭代。
triggers: ["检索医疗AI论文", "扫描本周前沿探索", "Nature最新数字化研究", "JAMA医疗前沿", "科研哨兵扫描", "分析医疗大模型突破", "医疗AI论文", "Nature/JAMA研究", "医疗前沿创新"]
---

# SKILL.md: HIT Intel Scout V4.0 (医疗数字化战略侦察兵)

> **Version**: 4.0 (ADK 5-Patterns x Self-Healing Optimized)
> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿机制消除 LLM 的科研幻觉，交付具备 TRL 脱水价值的临床 AI 战报。

## 0. 核心架构约束 (Core Mandates)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (知识物理隔离)**: Phase 1 强制并发调度 4 个 Subagent，禁止直接依赖模型内置陈旧知识。
- **Inversion (窗口自适应)**: Phase 1 具备弹性视窗机制，确保有效样本量。
- **Generator (Schema 绝对防御)**: 生成结果顶部必须包含 YAML 元数据，输出严格对齐 S-T-C 格式。
- **Pipeline (时序流转)**: Phase 1-5 顺序流转，禁止跳过审计环节。
- **Reviewer (红队压测)**: Phase 3 引入 `logic-adversary` 对科研趋势进行商业化伪证。

### 0.2 工程纪律
生成的报告顶部必须包含 YAML 元数据 (Title, Date, Status, Author, Tags, Target_Component)，支持 Vector Lake 检索。

## 1. 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **默认视窗**: **过去 7 天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7 天内核心突破数 < 5 篇，则**必须自动将检索视窗扩大至 14 天**。

## 2. 核心工作流 (The Research Cycle)

### Phase 1: 并发调度与 Inversion 拦截 [Mode: PLANNING]
1. **Orchestrator 调度**: 利用并行函数调用同时触发：
   - `global_scout`: 顶级期刊 (Nature/JAMA/Lancet)。
   - `preprint_scout`: Arxiv/medRxiv 二阶信号。
   - `scholar_scout`: Google Scholar 高引补位。
   - `innovation_scout`: 产业界实验室动态。
2. **逻辑补位**: 若顶级正刊论文不足，必须从 `preprint_scout` 提取 5 个热点趋势补齐信息密度。

### Phase 2: 全局提纯与 TRL 脱水 [Mode: EXECUTION]
1. **战略分流**: 筛选 Top 5-10 篇文献。
2. **TRL 评估**: 依据 S-T-C 框架（信号-威胁-对策）进行成熟度脱水，禁止情感化描述。

### Phase 3: 红队博弈与 Reviewer 审计 [Mode: EXECUTION]
1. **激活 Reviewer**: 必须调用 `activate_skill(name='logic-adversary')`。
2. **趋势伪证**: 针对选中的核心论文，展开对抗性分析：
   - 质疑实验数据的“真实世界”适配性。
   - 推演该技术在 DRG 2.0 语境下的成本黑洞。
   - 记录对抗产生的矛盾点于 `[Adversarial_Audit]` 区块。

### Phase 4: 战略推演与格式锻造 (Generator) [Mode: EXECUTION]
1. **底座映射**: 将科研成果映射至卫宁 MSL / ACE 底座或 WiNEX 产品线。
2. **洗稿优化**: 调用 `text-forger` 剔除学术冗余与“AI 味”。

### Phase 5: 认知蒸馏与自愈 (Self-Healing) [Mode: EXECUTION]
1. **知识入湖**: 调用 `vector-lake/cli.py sync` 同步至逻辑湖。
2. **技能自愈**: 若本次侦察发现模型在识别“伪创新”或“重复信号”上存在缺陷，必须将修正逻辑写回本文件末尾的 `## Gotchas` 区域。

## 3. 输出格式铁律 (Formatting Ironballs)

```markdown
# 医疗数字化前沿侦察周报 - [YYYYMMDD]
> **本周核心信号**：[一句话冷峻总结，如：医疗 AI 正从实验室 Demo 转向真实工作流信任赤字。]

## 🎯 情报速递 (Top Signals)
| 刊物 | 核心标题 | TRL等级 | 战略概述 | 链接 |
|:---|:---|:---|:---|:---|
| [Nature等] | [Title] | [1-9] | [1句话本质提取] | [URL] |

## 🔬 深度解剖：[核心现象]
### A. 逻辑解构
- [数据对比/物理边界/底层归因]
### B. 卫宁战略支点映射
- [MSL/ACE 底座启示]
- [WiNEX 防御性布局]

## ⚔️ 指挥官指令 (Directives)
- **建议动作**：[具体研发/战略调整建议]
```

## 4. 归档路径
- 路径: `C:\Users\shich\.gemini\MEMORY\DigitalHealthLecturesScout`
- 文件名: `Weekly_DigitalHealth_[YYYYMMDD].md`

## 5. 历史失效先验 (Gotchas)
- DO NOT report pure algorithmic improvements without clinical context.
- ALWAYS check for 2nd order effects (e.g., increased clinician documentation burden).
- ELIMINATE "Game-changing" or "Revolutionary" labels; USE "Incremental" or "Disruptive" with evidence.
