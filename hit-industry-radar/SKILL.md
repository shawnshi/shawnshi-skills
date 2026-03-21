---
name: hit-industry-radar
description: 医疗行业战略雷达 (V5.0)。当用户询问“卫宁动态”、“东软/创业中标”、“Epic/Cerner异动”或“医疗IT大事件”时，务必激活。该技能基于《龙虾教程》五层价值链重构，集成 SemHash 物理去重、Weaver 二跳推理与 Global Blackboard 协作，输出高信噪比的实战战报。
triggers: ["卫宁健康最新动向", "东软近期中标", "Epic行业新闻", "调用雷达扫描", "扫描竞争对手新闻", "HIT市场动态", "本周医疗IT战报"]
---

# SKILL.md: HIT Industry Radar (医疗行业雷达) V5.0

> **Version**: 5.0 (Lobster Architecture x Blackboard Pattern)
> **Vision**: 消除竞对追踪中的“跨周失忆”与“孤立事件堆砌”。系统不再是单向流，而是基于“数字黑板”的多角色情报组装机。

## 0. 核心架构约束 (The 5-Layer Value Chain)
1.  **感知层 (Sense)**: 强制集成 `history_manager.py`，执行 **SemHash (语义哈希)** 去重，拦截跨周复读的 PR 稿。
2.  **过滤层 (Filter)**: 引入 **Arbiter (仲裁者)** 角色。执行 5D 评分（Evidence, Source, Novelty, Consistency, Recency），无具体金额或技术参数的通稿直接抛弃。
3.  **关联层 (Connect)**: 激活 **Weaver (织者)**。寻找不同厂商、不同标段之间的二跳推理信号（如：A厂商降价 + B省医保预算缩减 = 区域价格战预警）。
4.  **架构编排**: 废弃严格的线性 Pipeline，采用 **Global Blackboard (全局黑板)** 模式。
5.  **激活层 (Activate)**: 采用 Format Stack，顶部强制注入 10s 紧急预警模块。

## 1. 触发逻辑 (Trigger)
- **时间范围**: 严格限定在**本周之内（周一至周日）**。
- **弹性机制**: 若无重大异动，针对目标厂商的存量优势执行“模拟攻击推演”。

## 2. 核心工作流 (Blackboard Protocol)

### Phase 1: 多维度并发侦察与 SemHash 去重 (Sense) [Mode: PLANNING]
1. **Initialize Blackboard**: 将本周的搜索意图写入数字黑板。
2. **并发调度 (Sentinel)**:
   - `global_hit_scout`: Epic, Oracle 等海外巨头的降维技术或并购。
   - `china_hit_scout`: 国内友商的中标、专利、人事及大模型试点。
   - `winning_baseline`: 卫宁健康自身的最新动作，建立防御基石。
3. **SemHash 拦截**: 将抓取到的信息与 `personal-intelligence-hub` 的历史指纹库对比。

### Phase 2: 五维仲裁与织网 (Filter & Connect) [Mode: EXECUTION]
1. **黑板清洗 (Arbiter)**: 对黑板上的原始 Fact 逐一执行 Evidence-Check。
2. **二跳推理 (Weaver)**: 扫描清洗后的事实，提取高度凝练的“隐含供应链共振”或“暗中价格战”主题词，补充到黑板的 `Insights` 区域。

### Phase 3: S-T-C 对抗与红队审计 (Reviewer) [Mode: VERIFICATION]
1. **战略推演**: 
   - **Fact (最新资讯)**: 绝对脱水，仅保留专有名词、时间、金额。
   - **Insight (解读分析)**: 基于 Weaver 的结论，使用系统动力学词汇（护城河、止血、算力房东）。
2. **红队辩论 (Advocate)**: 让魔鬼代言人对 Weaver 提出的共识进行反向攻击，将分歧点记录在案。
3. **Binary Eval (二元硬审计)**: 最终交付前自检：
   - [ ] 事实部分是否剔除了所有主观形容词？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售/研发话术价值？ [Yes/No]

### Phase 4: 激活与分层归档 (Activate & Self-Healing) [Mode: EXECUTION]
1. **Format Stack 渲染**: 按照下方的输出铁律生成战报。
2. **物理路径**: `{root}\MEMORY\HealthcareIndustryRadar\DHWB-Radar-YYYYMMDD.md`。
3. **技能自愈**: 若本次审计发现模型存在“算法谄媚”或“逻辑复读”，必须将修正逻辑回写至 `## Gotchas`。

## 3. 输出格式铁律 (Format Stack)

```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[威胁定性]**: [防御或进攻动作]

## 一、 国际巨头：[国际战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[日期] [精确动作]
- **解读分析 (Insight)**：[商业本质标签]

## 二、 中国军团：[国内战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[关键动作]
- **解读分析 (Insight)**：[防御性分析]

## 三、 织者洞察 (Weaver's View)：[核心公式]
1. [系统级规律 1]
2. [系统级规律 2]

## 🎯 下钻建议 (Commander's Hook)
- [极具张力的深度对比建议]
```

## 4. 历史失效先验 (Gotchas)
- DO NOT use adjectives in the Fact section (e.g., avoid "significant", "innovative").
- ALWAYS translate international trends into specific defensive suggestions for the WiNEX platform.
- ELIMINATE marketing fluff; MAINTAIN a cold, surgical narrative tone.
- **[CRITICAL]** NEVER repeat an identical event from a previous week. ALWAYS cross-reference with Vector Lake or `history_manager.py` before adding to the blackboard.
- **[CRITICAL]** DO NOT proceed past Arbiter phase if the Fact lacks concrete metrics (amounts, versions, dates). "Announced a strategic partnership" is NOISE without details.
