---
name: hit-industry-radar
description: 医疗行业战略雷达 (V4.0)。当用户询问“卫宁动态”、“东软/创业中标”、“Epic/Cerner异动”或“医疗IT大事件”时，务必激活。该技能通过并行雷达哨兵、ADK 五维补偿架构及 S-T-C 框架，输出具备商业穿透力且经过二元硬审计的实战战报。
triggers: ["卫宁健康最新动向", "东软近期中标", "Epic行业新闻", "调用雷达扫描", "扫描竞争对手新闻", "HIT市场动态", "本周医疗IT战报"]
---

# SKILL.md: HIT Industry Radar (医疗行业雷达) V4.0

> **Version**: 4.0 (ADK 5-Patterns x Self-Healing Optimized)
> **Vision**: 捕捉行业非共识信号，通过结构化补偿消除 LLM 的描述性膨胀，交付具备战略对抗价值的准军事级情报。

## 0. 核心架构约束 (Core Mandates)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (知识下锚)**: Phase 1 强制并发调用 3 个专业哨兵，禁止直接依赖模型内置知识。
- **Inversion (窗口硬锁)**: Phase 1 强制计算过去 7 天精确日期窗口，信息不足触发补位拦截。
- **Generator (Schema 绝对防御)**: 强制执行 S-T-C (Signal-Threat-Countermeasure) 框架，输出严格对齐 Markdown 铁律。
- **Pipeline (时序流转)**: 严格执行 Phase 1-4，禁止跳过逻辑对齐环节。
- **Reviewer (二元审计)**: Phase 3 引入针对“事实脱水度”与“逻辑攻击性”的二元硬核审计。

## 1. 触发逻辑 (Trigger)
- **时间范围**: 严格限定在**本周之内（周一至周日）**。
- **弹性机制**: 若无重大异动，针对目标厂商的存量优势执行“模拟攻击推演”。

## 2. 核心工作流 (The Recon Cycle)

### Phase 1: 多维度并发侦察 (Tool Wrapper & Inversion) [Mode: PLANNING]
1. **Orchestrator 并发调度**:
   - `global_hit_scout`: Epic, Oracle 等海外巨头的降维技术或并购。
   - `china_hit_scout`: 国内友商的中标、专利、人事及大模型试点。
   - `winning_baseline`: 卫宁健康自身的最新动作，建立防御基石。
2. **时间窗口校准**: 强制计算日期窗口，拒绝模糊时间。

### Phase 2: 逻辑对齐与主轴提炼 [Mode: EXECUTION]
1. **交叉验证**: 检查资讯时间戳是否在 7 天窗口内。
2. **同态映射**: 判断国内厂商是否在进行“降维模仿”。
3. **主轴定调**: 提取高度凝练的主题词（如“数据要素入表”、“环境感知爆发”）。

### Phase 3: S-T-C 推演与 Reviewer 审计 [Mode: VERIFICATION]
1. **战略推演**: 
   - **Fact (最新资讯)**: 绝对脱水，仅保留专有名词、时间、金额。
   - **Insight (解读分析)**: 使用系统动力学词汇（护城河、止血、算力房东）。
2. **Binary Eval (二元硬审计)**: 最终交付前自检：
   - [ ] 事实部分是否剔除了所有主观形容词？ [Yes/No]
   - [ ] 是否包含 3 条底层的系统级演化规律？ [Yes/No]
   - [ ] 建议动作是否具备直接的销售/研发话术价值？ [Yes/No]

### Phase 4: 归档与自愈 (Self-Healing) [Mode: EXECUTION]
1. **物理路径**: `{root}\MEMORY\HealthcareIndustryRadar\DHWB-Radar-YYYYMMDD.md`。
2. **认知蒸馏**: 将本周提取的核心规律同步至 Vector Lake。
3. **技能自愈**: 若本次审计发现模型存在“算法谄媚”或“资讯注水”，必须将修正逻辑回写至 `## Gotchas`。

## 3. 输出格式铁律 (Formatting Ironballs)

```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 一、 国际巨头：[国际战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[日期] [精确动作]
- **解读分析 (Insight)**：[商业本质标签]

## 二、 中国军团：[国内战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[关键动作]
- **解读分析 (Insight)**：[防御性分析]

## 三、 趋势纵深：[核心公式]
1. [系统级规律 1]
2. [系统级规律 2]

## 🎯 下钻建议 (Commander's Hook)
- [极具张力的深度对比建议]
```

## 4. 历史失效先验 (Gotchas)
- DO NOT use adjectives in the Fact section (e.g., avoid "significant", "innovative").
- ALWAYS translate international trends into specific defensive suggestions for the WiNEX platform.
- ELIMINATE marketing fluff; MAINTAIN a cold, surgical narrative tone.
