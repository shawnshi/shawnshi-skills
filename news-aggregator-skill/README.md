# news-aggregator-skill
<!-- Input: Source selection (HN, GitHub, 36Kr, etc.), keywords. -->
<!-- Output: Real-time intelligence reports, trend synthesis. -->
<!-- Pos: Intelligence Gathering Layer (The Hub). -->
<!-- Maintenance Protocol: Update 'scripts/fetch_news.py' if source scrapers fail (403/404). -->

## 核心功能
实时监测全球科技、医疗与金融动态的情报中枢。通过多源采集与二阶深度解析，产出具备跨领域趋势总结的战略报告。

## 战略契约
1. **深度提取**: 严禁仅罗列标题，必须使用 `--deep` 模式提取正文执行语义分析。
2. **二阶洞察**: 报告末尾必须提供 2-3 句话的趋势合成，识别非显见的技术/政策交汇点。
3. **溯源透明**: 所有的情报条目必须保留原文链接，确保信息的可验证性。
