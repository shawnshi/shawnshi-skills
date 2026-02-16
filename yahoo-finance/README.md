# Yahoo Finance: 金融先知中枢

<!-- 
@Input: Company Names, Tickers, Historical Ranges
@Output: Structured Market Data (JSON), News Timelines, Fundamental Profiles
@Pos: [ACE Layer: Perception] | [MSL Segment: Market Intelligence]
@Maintenance: Update ticker resolution logic & financial metric mappings.
@Axioms: JSON-Priority | Data Freshness | Zero-Guesswork
-->

> **核心内核**：全球市场接入点。提供确定性的结构化金融数据，消除市场噪音，直达核心指标。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 金融数据接入器，负责将模糊的公司查询转化为精确的市场事实与财务数据包。
- **反向定义**: 它不是一个投资理财顾问，而是一个客观事实的提供商。
- **费曼比喻**: 它像是一个全天候守在证券交易所门口的播报员，不仅能告诉你现在的价格，还能把这家公司的所有底细翻出来给你看。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“证券实体”、“价格序列”、“财务指标”等标准化实体。
- **ACE 角色**: 作为系统的 **Market Sensor (市场感知器)**。

## 2. 逻辑机制 (Mechanism)
- [Symbol Resolution] -> [Parallel Fetching] -> [Structured Normalization] -> [Analysis Feed]

## 3. 策略协议 (Strategic Protocols)
- **JSON 确定性原则**：任何数据分析任务前必须强制调用 --json 模式，确保机器可读性。
- **时效性约束**：必须自动标注数据的时间戳，并识别当前市场的开闭盘状态。
