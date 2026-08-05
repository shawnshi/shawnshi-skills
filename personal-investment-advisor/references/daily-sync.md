# Daily Sync 只读协议

## 目的与边界

Daily Sync 核验持仓身份、行情覆盖、时效和已确认观察边界。它不执行订单、不改写组合、不自动建立观察阈值，也不能在没有事件证据时宣布 Thesis 安全。

## 运行步骤

1. 用 `portfolio_loader.py` 的契约验证组合，列出所有 `quantity > 0` 的非现金标的。
2. 运行 `yf.py <代码...> --daily-sync --positions-file <portfolio.json>`，把标准输出保存到本任务隔离目录中的 `quotes.json`。该模式只取当前报价与身份字段，不计算历史技术指标或新闻。批次审计必须携带活动持仓规范化摘要，字段固定为 `symbol`、`quantity`、`currency`、`market`、`asset_type`，并以 SHA-256 绑定。
3. 行情包必须是一个对象，顶层只含本批次的 `records` 与单一 `portfolio_batch_audit`。列表根、每条记录内嵌审计、部分结果、重复代码、遗漏、额外代码、行情错误或身份冲突均失败关闭。
4. 运行 `daily_sync.py --positions-file <portfolio.json> --quotes-file <quotes.json>` 做独立离线重放。当前输出契约为 `pia_daily_sync_offline_v3`，同时绑定持仓快照、输入行情包与派生 `quote_snapshot`；缺少任一绑定的旧报告只能作为档案查看，不能供当前权重或历史重放计算使用。

`yf.py` 批次审计与重放结果的 `completeness.complete` 必须同时为真。请求数、返回数、有效报价数、身份匹配数和预期活动持仓数必须相等，所有缺失、额外、重复、失败、陈旧和未匹配清单必须为空。

## 行情与观察边界

逐项核对代码、交易所、币种、资产类型、报价时间和市场状态。时效阈值以 `yf.py` 输出的结构化 freshness policy 为准：`REGULAR` 为 900 秒，`PRE`、`PREPRE`、`POST`、`POSTPOST` 为 86400 秒，`CLOSED` 为 259200 秒。市场状态缺失或未知、报价超过允许的未来偏差、超过对应状态上限均失败关闭。不得用成本价、默认汇率、零值或其他标的价格补位。

先运行 `dashboard_catalog.py`，仅通过 `dashboard_index.json` 定位最新 Dashboard JSON。索引缺失、越界、损坏、代码不匹配或门禁失败均返回数据不足；不得搜索旧 Markdown 补位。

观察边界只接受用户明确确认、带来源定位且 `decision_scope=observation_only` 的 `monitoring_boundaries`。从本次 `quote_snapshot` 为每个标的生成临时行情对象，再运行 `watchlist_gate.py`。临时对象至少包含 `symbol`、`current_price`、`currency`、`as_of`、`source` 和 `market_state`。

不得读取归档 Dashboard 的旧价格作为当前行情，不得自动创建或迁移边界，也不得使用默认接近百分比。输出只描述已越界、接近、未越界、未定义或证据不足，不给方向、数量或订单。

## Thesis 红队

离线 `daily_sync.py` 固定把 Thesis 阶段标记为 `not_assessed/insufficient_evidence`，因此即使行情批次闭合，顶层仍为 `incomplete`。要完成事件判断，必须另行检索公司、行业、监管和宏观原始材料，并逐条映射历史 Thesis 的证伪条件。

没有新闻不能升级为“未发现致命事件”，股价变化也不能单独证明 Thesis 失效。最终报告必须把行情闭合度与 Thesis 证据状态分开呈现。
