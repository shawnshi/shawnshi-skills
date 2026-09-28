# A 股非金融经营公司：经营驱动估值

本切片补上旧 Dashboard 算术门**上游 EV 生成链**，不修改 Dashboard 7.2/Stock 3.0 格式；仅适用于 CN 普通股、经营公司、CNY 企业价值桥。银行、保险、ETF、DDM、FCFE、周期企业或其他估值方法须独立选适配方法，不以本模型强行覆盖。

明确授权读取模型与 Dashboard 两个文件后，运行 `python -B scripts/cn_valuation_drivers.py <model.json> <dashboard.json>`。如需把收入锚点与已复核公告事实连接，另显式指定 `--filing-package <facts.json> --verify-filing-raw`；这会按公告包列出的路径读取原件，逐份复核哈希与更正链，再核对证券代码、时点、选中事实、数值、尺度和来源哈希。未显式授权原件读取时不得传这组参数。无联网、无自动写入；每份输入最多 32 MiB。模型版本 `pia_cn_operating_dcf_v1`，`as_of_date` 的未来日期校验按 Asia/Shanghai 自然日进行；含 `instrument: {symbol, market: "CN", asset_type: "stock", industry_type: "operating_company", currency: "CNY"}`、`as_of_date`、未缩放人民币 `base_revenue_cny`、`revenue_anchor: {fact_id, value, scale, source_locator, content_sha256, reviewed_page}` 和恰好三场景 `cases: {base,bull,bear}`。锚点应来自已逐项人工核实的公告事实，`value*scale=base_revenue_cny`；字段和页码自报不证明原件真实或口径正确。

每个场景给出 `discount_rate`、`terminal_growth` 及连续的 `years`（1 至 10 年），每年显式填 `year`、`revenue_growth`、`operating_margin`、`cash_tax_rate`、`depreciation_amortization_cny`、`capital_expenditure_cny`、`change_in_working_capital_cny`。现金流公式为 `FCF = revenue*(1+growth)*margin*(1-tax)+D&A-capex-ΔNWC`；每年收入承接上一年。折现各年 FCF，并以末年 FCF 计算永续终值 `FCF_N*(1+g)/(r-g)`；`-1<g<r<1` 且末年 FCF 必须为正。脚本复算三个 EV，并逐一核对 Dashboard Stock 3.0 的 `scenario_analysis.<case>.enterprise_value`；基础、乐观、悲观的排序、桥中索偿和每股价值仍由原 `dashboard_gate.py --strict-current-contract` 与 `dashboard_math_gate.py` 验证。

**研究判断不得由算术门代替**：所有预测变量是分析师假设，须给出原始证据、历史基准率／同业、复核人、情景间差异和最强反方；终值占比与贴现率敏感性单列。`status=complete` 仅表示给定假设的 EV 算术与 Dashboard 一致；另看 `source_anchor_status`：`self_report_only` 为未连公告原件，`raw_capture_bound_semantics_unverified` 为收入锚点已与复核原件的所选事实绑定，但人工摘录语义及全量更正覆盖仍未证实。这些状态不表示折现率合理、现金流可以兑现、股权价值有安全边际、已通过原双门，或此资产值得买入。数据缺口不可用随意乘数填补。
