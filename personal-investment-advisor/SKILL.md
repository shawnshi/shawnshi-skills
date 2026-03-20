---
name: personal-investment-advisor
description: 顶级金融量化引擎。当用户询问“股票走势”、“个股基本面”、“美股新闻”或要求“对比 ETF 数据”时，务必立即激活。该技能提供结构化量化 JSON 分析与 K 线周期解析，严禁仅使用通用知识回答金融行情。
triggers: ["查询这支股票的历史走势", "调取600718的基本面", "列出昨日收盘后的美股新闻", "比较这三只ETF的日内图表", "输出该标的原量化JSON分析"]
---

# Personal Investment Advisor Skill (Powered by Yahoo Finance)

> **Version**: 2.0 | **Last Updated**: 2026-02-21
> 提供全球金融市场数据的确定性访问入口。

## Capabilities

- **Market Data**: 历史价格数据（OHLCV）+ 专业机构级摘要统计（绝对收益率、**最大回撤**、**相比最高点回撤**、波动率、**MACD (DIF/DEA/柱状)**、**RSI-14** 等）。
- **Company Info**: 深度基本面数据（新增 **ROE**、**PB**、**营业利润率**、Beta 等核心风控与估值跳点），支持 `--full-info` 全量。
- **News Aggregation**: 关联特定代码的最新新闻。
- **Deep Dive Analysis**: 结合专设的 `stock_analyzer` Agent 提供从“数据流”到“投资洞察”的升维体验（见下文 Agent 用法）。
- **Smart Resolution**: 自动将公司名（如 "Apple"）解析为 Ticker（"AAPL"），已知 Ticker 跳过搜索 API。
- **Flexible Intervals**: 支持日内K线间隔（`1m` ~ `1mo`），满足日内交易分析需求。
- **Context Optimization**: 新增 `--lean` 模式，智能截断冗长历史K线，保留首尾关键节点。特别针对日内高频 K 线加入了动态等距抽样，防止趋势失真，在为大模型减负（最高压缩 90% Context）的同时维持盘感。
- **Flexible Output**: 支持人类友好的 Rich 表格输出及机器可读的 JSON（推荐）。
- **Robust Execution**: 内置超时控制、指数退避重试、结构化错误报告及退出码规范。

## Usage

### 核心指令
```bash
uv run {SKILL_DIR}/scripts/yf.py [SYMBOLS...] [OPTIONS]
```
> `{SKILL_DIR}` 指代本技能根目录的绝对路径。

### Agent 路由指引 (Agent Routing)
为解决大模型在面临多个 Agent 设定时的混乱，请严格遵守以下分机号拨打原则：
1. **获取原始数据与新闻**: 直接使用 CLI 命令，不需要切换 Agent。
2. **深度投资诊断与决策**: 必须使用 `@yahoo-finance 切换到 stock analyzer` 或 `@stock_analyzer`，告诉大模型使用该专属身份来聚合数据并输出决策仪表盘。

### Options

| Flag           | Description                                                                                                |
|:---------------|:-----------------------------------------------------------------------------------------------------------|
| `SYMBOLS`      | 代码（`AAPL`）或公司名（`"Tesla"`）列表。                                                                  |
| `--period`     | 快捷范围：`1d`, `5d`, `1mo` (默认), `3mo`, `6mo`, `1y`, `2y`, `5y`, `ytd`, `max`。                         |
| `--interval`   | 数据间隔：`1m`, `5m`, `15m`, `30m`, `1h`, `1d` (默认), `1wk`, `1mo` 等。                                   |
| `--start`      | 开始日期 (YYYY-MM-DD 或 `"1 week ago"`)。                                                                  |
| `--end`        | 结束日期 (YYYY-MM-DD 或 `"yesterday"`)。                                                                   |
| `--json`       | **Agent 推荐使用**：输出结构化 JSON 数据到 stdout。                                                        |
| `--lean`       | **强推 Agent 使用**：上下文降噪模式，截断中间历史数据，保留完整 Summary 实战验证极大幅消除大模型幻觉负担。 |
| `--info-only`  | 仅获取公司基本面。                                                                                         |
| `--price-only` | 仅获取历史价格。                                                                                           |
| `--news-only`  | 仅获取相关新闻。                                                                                           |
| `--full-info`  | JSON 模式下输出完整 info 字段（默认仅核心估值与风控子集）。                                                |
| `--version`    | 显示版本号。                                                                                               |

### Exit Codes

| Code | Meaning      |
|:-----|:-------------|
| `0`  | 全部查询成功 |
| `1`  | 部分查询失败 |
| `2`  | 全部查询失败 |

## Examples

由于场景丰富，我们在 `examples` 文件夹中提供了独立的示例档：

- 请参阅 [`examples/examples.md`](./examples/examples.md) 获取包括 CLI 高频查询组合、及 `stock_analyzer` 的双引擎投研指令在内的所有使用方式与最佳场景。

## Best Practices for Agents

1.  **数据分析优先 JSON + Lean**: 涉及长时间跨度时，务必联合使用 `--json --lean` 参数以保证解析的确定性，同时防止 Token 爆炸。`--lean` 模式已自动支持日间与日内（Intraday）的动态不同截断逻辑。
2.  **颗粒度控制**:
    *   仅需股价时使用 `--price-only`。
    *   仅需新闻时使用 `--news-only`。
    *   仅需基本面时使用 `--info-only`。
    *   这能有效减少 Token 消耗。
3.  **利用机构级摘要统计**: JSON 输出中的 `summary` 字段已包含 `ma5`, `ma10`, `ma20`, `bias_ma5_pct`(乖离率), `max_drawdown_pct`(最大回撤), `dd_from_high_pct`(高点距离), `avg_close`(均价), `macd_dif`, `macd_dea`, `macd_hist`(MACD), `rsi_14`(RSI) 等指标，**切勿自行让大模型通过截断的历史数据进行复杂计算**。
4.  **异常处理**: 若返回 JSON 包含 `error` 或 `errors` 字段，应告知用户问题原因。检查退出码以判断整体执行状态。
5.  **时间灵活性**: 脚本支持自然语言日期（如 "yesterday", "3 months ago"），无需 Agent 手动转换。
6.  **结构化基本面**: 默认 JSON 输出已包含 ROE、PB 等核心机构研判指标。仅在特殊需要时使用 `--full-info`。
7.  **协议遵守**: 使用此技能前先明确验证 `interval` 与 `period` 等参数约束。不要臆造未提供的参数组合。
8.  **动静结合 (Dynamic Supplemental Search)**: `stock_analyzer` Agent 被要求采用 "单股深度验证 + 网页搜索补全" 双引擎模式。当雅虎数据在突发事件、研报深度解读及核心政策影响上颗粒度不足时，应当自然流转到 `google_web_search` 获取交叉验证。

## Troubleshooting

- **Symbol Not Found**: 尝试使用公司全名而非代码。
- **No Data**: 检查是否为周末或节假日，或 `--interval` 与 `--period` 组合是否合法。
- **Rate Limiting**: 脚本内置自动重试（最多2次指数退避），若仍然失败请稍后重试。
- **Exit Code 2**: 所有查询均失败，通常为网络问题或 API 不可用。

> !!! 维护协议：修改 `yf.py` 的逻辑时，需同步更新此文档中的示例。
