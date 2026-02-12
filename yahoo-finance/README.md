# yahoo-finance
<!-- Input: Tickers, company names, date ranges. -->
<!-- Output: Market data JSON, financial summaries, news feeds. -->
<!-- Pos: Intelligence Gathering Layer (Market Intelligence). -->
<!-- Maintenance Protocol: Update 'yf.py' if Yahoo Finance API structures change. -->

## 核心功能
全球金融市场的确定性接入点。提供股票价格、基本面、新闻及历史趋势的结构化提取，支持多代码并行查询与自然语言日期解析。

## 战略契约
1. **确定性优先**: 涉及对比或计算任务时必须使用 `--json` 输出，确保数据解析的绝对确定性。
2. **最小熵原则**: 仅按需提取数据（如使用 `--price-only`），严禁抓取冗余信息以降低上下文干扰。
3. **智能对齐**: 自动执行公司名到 Ticker 的模糊匹配，并提供行业归属与币种的元数据说明。
