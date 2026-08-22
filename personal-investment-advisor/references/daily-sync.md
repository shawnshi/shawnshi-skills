# Daily Sync 只读协议

## 目的与边界

Daily Sync 核验持仓身份、行情覆盖、时效和已确认观察边界。它不执行订单、不改写组合、不自动建立观察阈值，也不能在没有事件证据时宣布 Thesis 安全。

## 运行步骤

1. 用 `portfolio_loader.py` 的契约验证组合，列出所有 `quantity > 0` 的非现金标的。
2. 运行 `yf.py <代码...> --daily-sync --positions-file <portfolio.json> --cache-dir <task-dir>/yfinance-cache`，把标准输出保存到本任务隔离目录中的 `quotes.json`。该模式只取当前报价与身份字段，不计算历史技术指标或新闻，并默认以 2 个工作线程并发拉取独立标的；可用 `--daily-sync-workers 1..4` 调整。确定性的 TLS、证书或协议配置错误不做同参数重试；在尚无成功结果时，同批次连续出现相同系统性传输错误会熔断尚未提交的标的，并为每个标的保留显式失败记录，熔断不得计作行情成功。批次审计必须携带活动持仓规范化摘要，字段固定为 `symbol`、`quantity`、`currency`、`market`、`asset_type`，并以 SHA-256 绑定。未显式提供缓存目录时，Daily Sync 使用当前工作目录下的 `tmp/pia-yfinance-cache`，避免不可写的用户级 SQLite 缓存导致整批重试。
3. 行情包必须是一个对象，顶层只含本批次的 `records` 与单一 `portfolio_batch_audit`。列表根、每条记录内嵌审计、部分结果、重复代码、遗漏、额外代码、行情错误或身份冲突均失败关闭。
4. 运行 `daily_sync.py --positions-file <portfolio.json> --quotes-file <quotes.json> [--thesis-evidence-file <evidence.json>]` 做独立离线重放。当前输出契约为 `pia_daily_sync_offline_v3`，同时绑定持仓快照、输入行情包、派生 `quote_snapshot` 以及可选事件证据包；缺少行情绑定的旧报告只能作为档案查看，不能供当前权重或历史重放计算使用。

`yf.py` 批次审计与重放结果的 `completeness.complete` 必须同时为真。请求数、返回数、有效报价数、身份匹配数和预期活动持仓数必须相等，所有缺失、额外、重复、失败、陈旧和未匹配清单必须为空。

## 行情与观察边界

逐项核对代码、交易所、币种、资产类型、报价时间和市场状态。时效阈值以 `yf.py` 输出的结构化 freshness policy 为准：`REGULAR` 为 900 秒，`PRE`、`PREPRE`、`POST`、`POSTPOST` 为 86400 秒，`CLOSED` 为 259200 秒。市场状态缺失或未知、报价超过允许的未来偏差、超过对应状态上限均失败关闭。不得用成本价、默认汇率、零值或其他标的价格补位。

先运行 `dashboard_catalog.py`，仅通过 `dashboard_index.json` 定位最新 Dashboard JSON。索引缺失、越界、损坏、代码不匹配或门禁失败均返回数据不足；不得搜索旧 Markdown 补位。

观察边界只接受用户明确确认、带来源定位且 `decision_scope=observation_only` 的 `monitoring_boundaries`。从本次 `quote_snapshot` 为每个标的生成临时行情对象，再运行 `watchlist_gate.py`。临时对象至少包含 `symbol`、`current_price`、`currency`、`as_of`、`source` 和 `market_state`。

不得读取归档 Dashboard 的旧价格作为当前行情，不得自动创建或迁移边界，也不得使用默认接近百分比。输出只描述已越界、接近、未越界、未定义或证据不足，不给方向、数量或订单。

## Thesis 红队

没有 `--thesis-evidence-file` 时，离线 `daily_sync.py` 把 Thesis 阶段标记为 `not_assessed/insufficient_evidence`，因此即使行情批次闭合，顶层仍为 `incomplete`。完成事件判断时，先批量读取发行人、交易所、监管机构和官方产品披露列表，只对窗口内新增且命中证伪条件的材料深读；再按 [thesis_red_team_schema.json](thesis_red_team_schema.json) 形成证据包。

证据包必须绑定同一持仓快照，窗口结束时间距评估时点不超过一小时，逐标的覆盖全部活动非现金持仓，并闭合宏观、板块和监管三个范围。每条证据必须是公开一手 URL、带发布时间、获取时间、内容 SHA-256 和可核查主张。门禁只验证包结构、时间、覆盖、引用和绑定，不替代对来源真实性与语义判断的独立复核。存在 `fatal_breach` 不代表流程失败：只要证据覆盖闭合，工作流可为 `complete`，同时由 `fatal_event_status=fatal_breach_detected` 明确报警。

没有新闻不能升级为“未发现致命事件”，股价变化也不能单独证明 Thesis 失效。最终报告必须把行情闭合度与 Thesis 证据状态分开呈现。
