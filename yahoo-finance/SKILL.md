---
name: yahoo-finance
description: 获取股票价格、基本面、新闻及历史趋势。支持多代码查询、自然语言日期解析、日内K线间隔及结构化 JSON 输出。当用户询问"XX股价是多少"、"查看XX公司的最新新闻"或"分析XX过去一年的表现"时触发。
version: "2.0"
language: py
last_updated: "2026-02-21"
---

# Yahoo Finance Skill

> **Version**: 2.0 | **Last Updated**: 2026-02-21
> 提供全球金融市场数据的确定性访问入口。

## Capabilities

- **Market Data**: 历史价格数据（OHLCV）+ 自动摘要统计（涨幅%、均价、波动率等）。
- **Company Info**: 基本面、行业分类、币种及公司概况（默认精简输出，支持 `--full-info` 全量）。
- **News Aggregation**: 关联特定代码的最新新闻。
- **Smart Resolution**: 自动将公司名（如 "Apple"）解析为 Ticker（"AAPL"），已知 Ticker 跳过搜索 API。
- **Flexible Intervals**: 支持日内K线间隔（`1m` ~ `1mo`），满足日内交易分析需求。
- **Flexible Output**: 支持人类友好的 Rich 表格输出及机器可读的 JSON（推荐）。
- **Robust Execution**: 内置超时控制、指数退避重试、结构化错误报告及退出码规范。

## Usage

### 核心指令
```bash
uv run {SKILL_DIR}/scripts/yf.py [SYMBOLS...] [OPTIONS]
```
> `{SKILL_DIR}` 指代本技能根目录的绝对路径。

### Options

| Flag | Description |
| :--- | :--- |
| `SYMBOLS` | 代码（`AAPL`）或公司名（`"Tesla"`）列表。 |
| `--period` | 快捷范围：`1d`, `5d`, `1mo` (默认), `3mo`, `6mo`, `1y`, `2y`, `5y`, `ytd`, `max`。 |
| `--interval` | 数据间隔：`1m`, `5m`, `15m`, `30m`, `1h`, `1d` (默认), `1wk`, `1mo` 等。 |
| `--start` | 开始日期 (YYYY-MM-DD 或 `"1 week ago"`)。 |
| `--end` | 结束日期 (YYYY-MM-DD 或 `"yesterday"`)。 |
| `--json` | **Agent 推荐使用**：输出结构化 JSON 数据到 stdout。 |
| `--info-only` | 仅获取公司基本面。 |
| `--price-only` | 仅获取历史价格。 |
| `--news-only` | 仅获取相关新闻。 |
| `--full-info` | JSON 模式下输出完整 info 字段（默认仅核心子集）。 |
| `--version` | 显示版本号。 |

### Exit Codes

| Code | Meaning |
| :--- | :--- |
| `0` | 全部查询成功 |
| `1` | 部分查询失败 |
| `2` | 全部查询失败 |

## Examples

### 单股查询 (JSON)
```bash
uv run {SKILL_DIR}/scripts/yf.py AAPL --json --period 5d
```

### 多股对比 (仅基本面)
```bash
uv run {SKILL_DIR}/scripts/yf.py AAPL MSFT GOOG --json --info-only
```

### 自然语言日期范围
```bash
uv run {SKILL_DIR}/scripts/yf.py "Tesla" --json --start "3 months ago" --end "yesterday"
```

### 日内K线 (1小时间隔)
```bash
uv run {SKILL_DIR}/scripts/yf.py 0700.HK --json --price-only --period 5d --interval 1h
```

### 仅获取新闻
```bash
uv run {SKILL_DIR}/scripts/yf.py MSFT --json --news-only
```

## Best Practices for Agents

1.  **数据分析优先 JSON**: 涉及对比、总结或计算任务时，务必使用 `--json` 参数以保证解析的确定性。
2.  **颗粒度控制**:
    *   仅需股价时使用 `--price-only`。
    *   仅需新闻时使用 `--news-only`。
    *   仅需基本面时使用 `--info-only`。
    *   这能有效减少 Token 消耗。
3.  **利用摘要统计**: JSON 输出中的 `summary` 字段已包含 `period_return_pct`, `avg_close`, `volatility_std` 等指标，无需自行计算。
4.  **异常处理**: 若返回 JSON 包含 `error` 或 `errors` 字段，应告知用户问题原因。检查退出码以判断整体执行状态。
5.  **时间灵活性**: 脚本支持自然语言日期（如 "yesterday", "3 months ago"），无需 Agent 手动转换。
6.  **精简 info**: 默认 JSON 输出仅包含核心基本面字段，需要全量数据时使用 `--full-info`。

## Troubleshooting

- **Symbol Not Found**: 尝试使用公司全名而非代码。
- **No Data**: 检查是否为周末或节假日，或 `--interval` 与 `--period` 组合是否合法。
- **Rate Limiting**: 脚本内置自动重试（最多2次指数退避），若仍然失败请稍后重试。
- **Exit Code 2**: 所有查询均失败，通常为网络问题或 API 不可用。

> !!! 维护协议：修改 `yf.py` 的逻辑时，需同步更新此文档中的示例。
