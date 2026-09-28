# A 股行动级输出：可行性探针

`actionable` 研究可能包含方向、价格或仓位参数，但任何机器计算都**不授权下单**。当准备给出可执行的 A 股方向、数量和价格时，应先核验交易所当日规则、标的状态及用户授权提供的可用资源，再运行 `python -B scripts/cn_actionability_gate.py <assessment.json>`。该脚本离线只读、不会连接券商或写入订单；最大输入 1 MiB。仅作研究参数的**当前快照可行性探针**，不生成建议。

输入 `schema_version: "pia_cn_actionability_v1"`。非交易日可仅给 `instrument` 并显式传 `--holiday-calendar-file <已捕获交易所公告的休市表>`：脚本重新核验对应交易所与年份的官方原件后输出 `status=market_closed`、`actionability=not_actionable`（退出码 2），不要求构造不存在的盘中报价或交易条款；来源/年份缺失时拒绝。开市日仍须提供以下全部快照，不能据日历推断个股可交易。`instrument` 必须包含 CN stock、CNY、代码、`exchange`（SSE/SZSE/BSE）。`quote` 含相同代码、REGULAR 状态、人民币报价、当日成交量、带时区秒级 `as_of`/`retrieved_at`、来源 URL 与完整原件 SHA-256；报价不得超过 900 秒。`rules` 含相同标的与交易所、当日 `trading_date`、来源 URL/hash/获取时刻、`trading_allowed=true`、当日适用的价格上下限（没有日限价时两者为 null 且需官方原因）、`minimum_buy_lot` 与 `buy_increment`。不得把其他板块的单位或涨跌幅限制当默认值。

`terms` 含 `side: buy|sell`、正整数 `quantity` 和 `price_cny`；还需显式提供 `max_volume_participation` 与 `cost_bps: {commission,spread,impact,sell_tax}`。买入需经用户授权的 `available_cash_cny` 覆盖名义金额及估算成本；卖出需经用户确认的当日 `available_sell_quantity`（已经排除尚不可卖数量）。系统不得从账户号、同目录文件或旧快照推断这些字段。停牌／非连续交易状态、过期报价、休市日、价限、买入单位、可卖量、现金、成交量参与率或费用缺口一律不能标为可行。价格界限与费率随交易日、板块、特别状态和政策调整，必须以该日适用原件重验。

`status=complete` 只表示**所给输入之间**通过算术和时效约束，输出仍为 `human_review_required_no_order`。脚本并不证明交易所规则原件真实、持仓 T+1 可卖余额正确、盘中成交可能性或冲击成本准确；人工复核及交易执行完全在本技能外。对交易所规则来源或真实行情无法核实时，不升级至可执行参数，改交付 `advisory`／`research_only` 的证据化判断。
