# SKILL.md: HIT Weekly Brief (行业战区周报) V3.0 (Assault Edition)

---
name: hit-weekly-brief
description: 医疗行业战区研报中枢。当用户询问“本周麦肯锡研报”、“数字医疗白皮书”或需要“生成周报”时，务必激活。该技能通过 S-I-A 战略推演，将噪音降维为高管视角的抗幻觉决策资产。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

## 1. 启动序列与边界 (Boot Sequence & Bounds)
- **触发指令**: 接收到检索医疗研报或生成数字健康周报的指令时触发。
- **时间锚点 (Time Anchor)**: 默认计算**过去 7 天 (滑动窗口)** 的日期区间 (YYYY-MM-DD)。若7 天内无核心智库/政务发文，则自动回溯至过去 14天，确保输出高信噪比的情报资产。
- **宁缺毋滥的平衡**: 优先保证时效性，但若核心资讯不足 5 条，必须启动“战略补位 (Strategic Backfill)”逻辑。

## 2. 核心工作流 (The V3.0 Deterministic Workflow)

### Phase 2: 分层异步侦察与横向扩展 (Parallel Recon & Lateral Sensing)
利用 Gemini 并行函数调用机制，同时触发以下 3 个 Subagents。要求其不仅搜索新发布的 PDF/报告，还要搜索正在进行的**政策咨询、智库观点文章及行业研讨会纪要**。
- `{root}\tmp\recon_strategy.md` (调用 `strategy_consulting_scout`)
- `{root}\tmp\recon_tech.md` (调用 `tech_advisory_scout`)
- `{root}\tmp\recon_policy.md` (调用 `macro_policy_scout`)

### Phase 3: 主轴提炼与降维解析 (Thematic Synthesis & 3D Parsing)
在收集完情报后，必须执行以下认知处理：
1. **主轴定调**: 用一句话概括本周全球智库释放的最核心共识（如：“代理式AI的实战化”或“基层医疗的资本回归”）。
2. **三维降维**: 将所有碎片情报强制归类到三个高阶商业维度：[技术演进]、[安全与合规]、[资本与政策/治理]。

## 3. 输出格式铁律 (The Formatting Ironballs)

**必须完全放弃外部模板，严格按照以下 Markdown 结构输出，不准有任何格式偏离：**

```markdown
# 全球数字健康智库周报 - [日期 YYYY-MM-DD 至 YYYY-MM-DD]
> **本周战略主轴**：[用一段极具统摄力的话，总结本周全球咨询机构与权威组织释放的最强共识。]

## I. 全球核心咨询报告与权威动态一览
*(必须提取至少 5-7 份顶级报告，以高密度表格呈现)*

| 机构 (Institution) | 报告名称 / 最新资讯 | 核心摘要 (1句话) |
|:---|:---|:---|
| [如：McKinsey/WHO] | [报告/资讯标题] | [高度浓缩的商业实质，如：转向代理式AI缩减闭环] |

## II. 行业深度解读：[提取本周核心驱动力，如：HIMSS 26驱动的范式转移]
*(根据 Phase 3 的降维结果，输出 3 个维度的深度剖析)*

### 1. 技术演进：[提炼技术趋势，如：从生成式AI到代理式AI]
- **现象 (Fact)**：[数据支撑或权威宣告的客观事实]
- **解读 (Insight)**：[穿透表象的底层逻辑]
- **场景映射 (临床/运营)**：[说明技术在具体医疗环节的改变，如接管RCM或临床辅助]

### 2. 安全与架构：[提炼底座趋势，如：零信任的强制化]
- **现象 (Fact)**：[勒索数据或合规要求]
- **解读 (Insight)**：[为什么原有的模式崩溃]
- **动作映射**：[行业标杆的做法，如微隔离]

### 3.资本与政策：[提炼宏观趋势，如：基层回归与去援助依赖]
- **现象 (Fact)**：[世行/WHO等宏观机构的数据事实]
- **解读 (Insight)**：[解释资本流向的转变逻辑]
- **投资逻辑**：[当前的避险资产或高ROI领域]

## III. 战略教练建议与下一步行动 (Strategic Recommendation)
*作为寻求“手术刀精度”的战略教练，针对本周情报，给出 3 条对卫宁健康高管/销售线的直接话术或产品打法建议：*
- **产品叙事/销售话术**：[例如：停止谈“大模型赋能”，改谈“自动执行代理（Agents）”]
- **战略规划/预算争夺**：[针对紧缩周期的项目立项建议]
- **[其它高阶动作]**：[具体落地的商业建议]

> **🎯 Next Step 深度下钻建议 (Commander's Hook)**
> *鉴于本周情报，您是否需要我为您梳理一份：《[极具诱惑力的深度战术清单或复刻指南]》？*
```

### Phase 4: 物理归档 (Archiving)
1. 将最终成品移动至红区目录 `{root}\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`。

---
*SYS_CHECK: Digital Health Weekly Brief Subsystem (V3.0 Assault Architecture) - Ready.*
