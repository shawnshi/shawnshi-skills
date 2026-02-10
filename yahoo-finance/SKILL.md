---
name: yahoo-finance
description: 获取股票价格、基本面、新闻及历史趋势。支持多代码查询、自然语言日期解析及 JSON 输出。当用户询问“XX股价是多少”、“查看XX公司的最新新闻”或“分析XX过去一年的表现”时触发。
---

# Yahoo Finance Skill

提供全球金融市场数据的确定性访问入口。

## Capabilities

- **Market Data**: 历史价格数据（Open, High, Low, Close, Volume）。
- **Company Info**: 基本面、行业分类、币种及公司概况。
- **News Aggregation**: 关联特定代码的最新新闻。
- **Smart Resolution**: 自动将公司名（如 "Apple"）解析为 Ticker（"AAPL"）。
- **Flexible Output**: 支持人类友好的表格输出及机器可读的 JSON（推荐）。

## Usage

### 核心指令
```bash
uv run C:\Users\shich\.gemini\skills\yahoo-finance\scripts\yf.py [SYMBOLS...] [OPTIONS]
```

### Options

| Flag | Description |
| :--- | :--- |
| `SYMBOLS` | 代码（AAPL）或公司名（"Tesla"）列表。 |
| `--period` | 快捷范围：`1d`, `5d`, `1mo` (默认), `3mo`, `1y`, `ytd`, `max`。 |
| `--start` | 开始日期 (YYYY-MM-DD 或 "1 week ago")。 |
| `--end` | 结束日期 (YYYY-MM-DD)。 |
| `--json` | **Agent 推荐使用**：输出结构化 JSON 数据。 |
| `--info-only` | 仅获取公司基本面。 |
| `--price-only` | 仅获取历史价格。 |
| `--news-only` | 仅获取相关新闻。 |

## Best Practices for Agents

1.  **数据分析优先 JSON**: 涉及对比、总结或计算任务时，务必使用 `--json` 参数以保证解析的确定性。
2.  **颗粒度控制**: 
    *   仅需股价时使用 `--price-only`。
    *   仅需新闻时使用 `--news-only`。
    *   这能有效减少上下文熵值（Token 消耗）。
3.  **异常处理**: 若返回 JSON 包含 `error` 字段，应告知用户无法识别该实体。
4.  **时间灵活性**: 脚本支持自然语言日期（如 "yesterday"），无需 Agent 手动转换。

## Troubleshooting

- **Symbol Not Found**: 尝试使用公司全名而非代码。
- **No Data**: 检查是否为周末或节假日。
- **Rate Limiting**: 若请求失败，请稍后重试。

> !!! 维护协议：修改 `yf.py` 的逻辑时，需同步更新此文档中的示例。
