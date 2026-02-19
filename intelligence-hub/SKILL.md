---
name: intelligence-hub
description: 战略情报作战中枢。整合全球多源新闻抓取与二阶深度情报精炼，构建统一的个人‘逻辑湖’。
---

# SKILL.md: Intelligence Hub (情报侦察与分析中枢)

## 1. 触发逻辑 (Trigger)
- 当用户要求“获取最新情报”、“分析行业趋势”、“扫描技术新闻”或“生成每日简报”时激活。

## 2. 核心架构 (Modes)
本技能提供两种作战模式：
- **扫描模式 (--scan)**: 调用 fetch_news.py。高通量并行抓取（HN, GitHub, 36Kr 等），输出结构化 JSON 或初步列表。
- **简报模式 (--digest)**: 调用 digest.ts 并结合 thought-refiner。对精选源进行二阶推演，生成具备战略穿透力的深度简报。

## 3. 核心 SOP

### 第一阶段：情报侦察 (Reconnaissance)
1. **多源抓取**：根据需求执行模式选择。
   - `python scripts/fetch_news.py --source all`
2. **信号过滤**：基于 memory.md 中的“年度战役”关键字进行高增益滤波。

### 第二阶段：深度精炼 (Refinement)
1. **二阶推演**：Agent 必须针对抓取到的 10 条核心信息进行“So What?”审计。
2. **趋势建模**：识别非显见的技术/政策交汇点。

### 第三阶段：结构化输出
1. **统一格式**：所有报告必须遵循 [问题-论点-结论-推荐理由] 结构。
2. **分类锚定**：必须包含 [AI/ML]、[架构/工程]、[战略/观点] 三大分类。

### 第四阶段：物理归档 (The Logic Lake)
1. **强制持久化**：所有报告必须保存至以下路径，命名规范为 `intelligence_YYYYMMDD_briefing.md`。
2. **结构要求**：归档文件必须严格包含以下模块：
   - **[二阶推演 (Digest)]**: 关联 memory.md 的战略分析。
   - **[核心判词 (Punchline)]**: 提炼当次情报的最高纲领。
   - **[带简介的原始信号清单 (Raw Signals & Abstracts)]**: 必须包含 标题、链接 及 30-50 字的核心内容摘要。
3. **路径锚定**: `C:\Users\shich\.gemini\MEMORY\news\`

## 4. 维护与资源
- **采集引擎**: scripts/fetch_news.py.
- **分析引擎**: scripts/digest.ts.
- **输出模板**: references/responses.md.
