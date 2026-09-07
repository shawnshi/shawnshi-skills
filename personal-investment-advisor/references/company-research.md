# 公司研究工作流

## 1. 锁定身份与时间点

仅摘要用户所供文档且不声称最新、当前或已外部核验时，不要求实时行情探针；仍须注明材料中的发行人、来源归因与原文位置、发布日期、报告期间、单位和未核验限制，不得将材料身份当作已核验的当前证券身份。

超出上述限定摘要范围时，先运行 `instrument_gate.py`，显式给出代码、市场和资产类型；任何当前身份、价格或估值结论仍须适用的身份、时间与实时证据门。美股公司股票再运行 `live_evidence_probe.py`，交叉核对实时行情、Nasdaq 身份、SEC CIK、交易所关联和 EDGAR 最新披露。若 SEC ticker 映射端点不可用，可传入已由用户或原始材料确认的 `--cik`，探针会直接访问 submissions 并反向核对代码、交易所和 CIK；不得猜测 CIK。Yahoo chart 未返回 `marketState` 时，只能从其 `currentTradingPeriod` 推导并显式标注来源，时效阈值仍失败关闭。正式 SEC 请求必须设置包含真实联系邮箱的 `PIA_SEC_USER_AGENT`；测试占位地址不得进入正式研究。

自动探针不覆盖 ETF、基金、ADR 边界案例及中港股。这些标的须改用交易所、监管机构和发行人原始披露，并保留证券代码、交易所、币种、资产类型、来源定位、发布日期和获取时间。

## 2. 按任务范围建立研究契约

基础事实、披露摘要与描述性筛选按身份、原始来源、截止日及实际覆盖验收，不要求预测、Brief 或公司估值；明确未评估项，不得称为完整深度研究。以下 Brief 与预期差步骤仅用于深度 Thesis / 估值和完整 Dashboard；ETF 的完整 Dashboard 使用第 5 节 NAV 分支。

按 `research_brief_schema.json` 创建输入，再运行 `research_brief_gate.py`。Brief 至少闭合：

- `as_of_date`、投资期限、基准、市场与资产类型；
- 带指标、数值、单位、期间、来源定位和日期的市场共识或公开参考代理；
- 可计算的独立判断与预期差；
- 核心假设、证伪运算符、阈值、截止日期和关键变量；
- 数据来源截止日期不得晚于研究截止日期，也不得写入未来日期。

缺少任一核心项时停止深度研究，返回证据不足；不得用叙述性占位文字替代结构化数值。默认不要求付费卖方一致预期；无法从免费公开来源取得一致预期时，可使用明确标记的公司指引、已报告事实、行业公开中位数或市场隐含代理作为比较基准，不得称为卖方共识。若连公开代理也无法构造，则只做事实研究，不伪造预期差。

## 3. 选择方法并采集数据

从 `method_profiles.json` 选择与市场、资产类型和行业匹配的方法。阈值属于可替换假设，不是通用事实。正式输出记录配置名、版本、适用范围和研究截止日期；没有匹配配置时返回证据不足。

`quality_screener.py` 是描述性财务筛选，不是已验证 Alpha 模型。当前历史质量分析至少需要三个年度期间；现金流、利息保障和平均权益口径必须保留原始观测。银行和保险采用专用证据配置；ETF 的财务质量筛选为不适用，转而核验指数、方法、费率、复制方式、规模、流动性、NAV 折溢价、跟踪差异、集中度和份额变化。

历史 `as_of_date` 请求只有在能够取得点时快照时才可运行。美股年度财务优先使用 `pia.py edgar-fundamentals <代码...> --as-of <日期>`，按 SEC `companyfacts` 的真实 `filed` 日期选择当时已披露值；当前 Yahoo 基本面快照不得回填为历史事实。A/H 股历史点时研究须绑定官方公告日期及原文，Akshare 当前或重述后字段不能单独证明历史可得性。无法取得时返回 `point_in_time_snapshot_unavailable`。

数据入口：

- 美股点时年度财务：`sec_edgar_fundamentals.py` 或稳定入口 `pia.py edgar-fundamentals`；正式 SEC 请求必须使用真实联系邮箱；
- 通用行情与当前描述性财务：`yf.py`；请求历史序列时同时传入 `--market` 与 `--asset-type`，或通过已验证组合绑定同等身份；
- A 股补充：`akshare_fetcher.py`；
- 管理层承诺：`management_claim_tracker.py`；
- ETF 历史完整性：先运行 `history_integrity_gate.py`，再通过 `yf.py --history-integrity-file` 绑定同一历史序列。

A 股增强数据超时或连接失败必须结束子进程并返回数据不足，不得改写主进程代理环境或用旧值补齐。历史来源选择为 `akshare` 时失败关闭；只有显式选择 `auto` 才允许回退 Yahoo。

ETF 技术指标仅在 `history_integrity.detail_status=series_bound_verified` 且 `technical_metrics_allowed=true` 时生成。证券身份、公司行动、时区日期、截止日、数据提供方、来源定位或复权方式任一不闭合，就停止历史衍生指标；当前原始报价仍可单独用于身份匹配。

## 4. 形成预期差与反证

对每个关键变量分别记录市场共识、公司指引或已报告事实、独立估计、数值差异、估值影响和证伪条件。新闻数量、情绪或股价变化不能单独证明 Thesis 成立或失效。

管理层承诺只根据可定位的原始材料输出 `met`、`missed` 或 `insufficient_evidence`，不得推断主观动机。测试夹具必须标记 `test_mode`，不得进入正式 Dashboard。

## 5. 估值与 Dashboard

新建深度公司 Dashboard 使用结构化基础、乐观和悲观三种估值情景。每个情景记录方法、日期、币种、显式假设、企业价值、净债务、股权价值、稀释股数、每股结果和证伪条件；敏感性区间必须包围基础情景。`dashboard_math_gate.py` 重算企业价值到股权价值、每股价值、情景排序和敏感性排序；它不从 DCF、倍数或其他方法假设重新推导企业价值，因此该上游估值仍需单独复核。

### ETF：NAV 证据与压力情景

Schema 7.1 增加 `etf_research.contract_version="1.0"` 与 `scenario_analysis.valuation_contract_version="etf_nav1.0"`。只有 `market_type="ETF"`、Brief 的 `instrument.asset_type="etf"` 和 `method_profile="etf_research"` 三者匹配才能使用；还须由一手来源的结构化身份观测绑定代码、市场、币种与 ETF 类型。标签与指纹不能证明真实外部身份，正式研究仍需重新核对发行人或交易所原文。

`etf_research` 中 `identity`、`nav`、`fees`、`tracking` 用 `{"evidence_index": 1}` 引用从 0 开始的 `evidence_items` 索引。被引证据除既有来源/时间/指纹字段外，含 `etf_observation`：

- 共用：`kind` 与引用名相同，`symbol`、`market`、`currency` 与 Brief 相同；一手来源、已知可得性、时区化 `published_at`/`retrieved_at`。
- `identity`：`asset_type="etf"`、`benchmark`、`replication_method`。
- `nav`：正数 `value`、`unit="currency_per_unit"`、`valuation_date`。配置默认允许 NAV 距研究截止日最多 **5 个日历日**，要求估值日 ≤ 公布日 ≤ 获取日 ≤ 截止日；不是交易日历保证。周末、T+1 可在此窗口内闭合，超期或可得性未知则停止 NAV 相关结论，仅保留已核验事实。
- `fees`：`fee_basis="total_expense_ratio"`、`unit="ratio_per_year"`、`value` 为 [0,1) 的年费率，不把单项管理费冒充总费率。
- `tracking`：`tracking_type="tracking_difference"` 或 `"tracking_error"`、`value`、`unit="ratio"`、`period_start`、`period_end`、匹配的 `benchmark` 与明确 `methodology`（收益/年化/币种口径）；误差非负，期间结束不晚于公布日。

`quote_evidence_index` 绑定同标的 `market_data` 报价，保留原有市场状态秒级时效门；ETF 允许报价观测日早于研究日，但获取日仍等于研究日。`premium_discount = price / NAV - 1` 使用比例单位，`premium_discount_basis` 固定 `quote_vs_last_published_nav`：必须展示报价时刻、NAV 估值日与公布时刻，不称为同时点公允价值。显示价格必须等于所绑定报价。

`coverage_scope` 说明实际完成范围。`holdings_concentration`、`liquidity`、`assets`、`share_changes`、`corporate_actions` 各项必须选择 `status="evidenced"` 加证据索引（同名观测含限定范围的 `summary`），或 `status="gap"` 加 `reason`，并将 `字段名: reason` 同步列入 `data_gaps`。缺口不阻断独立核心指标，也不得宣称该缺口已完成；持仓集中度的摘要必须注明持仓日期和覆盖份额，流动性摘要注明指标及观察期间。

ETF 三情景方法固定 `nav_index_currency_stress`，币种等于 Brief；`enterprise_value`、`net_debt`、`equity_value`、`diluted_shares` 在每个情景均为字符串 `not_applicable`，不得填零。`nav_per_unit` 等于证据 NAV；`assumptions` 恰含 `index_return` 与 `currency_return` 两个带来源、日期、指纹的显式比例假设（均 > -1），重算 `per_share_value = nav_per_unit * (1 + index_return) * (1 + currency_return)`，并核验 bear ≤ base ≤ bull；敏感性区间必须包围同名基础假设。该公式仅为 NAV 压力映射，不模拟全部跟踪、费率或溢价变化，也不生成目标价格/交易指令。Brief 的数值比较可用明确标记 `reference_type="reported_nav"` 的已公布 NAV；独立估计明确是假设，不冒充卖方共识。

归档目录显式接受索引头和条目的 `dashboard_contract_version` 为字符串 `7.0` 或 `7.1`，分别校验，不接受其他版本或数字强转。追加严格通过的新记录使用 `7.1`；发生索引提交时，仅容器头更新为当前契约，保留条目的真实版本、不可变 JSON / Markdown 和哈希不变。最新记录仍按归档时间与 generation ID 排序，不按版本高低选择。解析结果中每个有效条目报告自身版本；顶层版本表示解析器当前契约，不表示旧记录通过当前深度研究门。

迁移边界：股票估值 2.0、无版本旧情景与旧归档读取不变；旧 ETF 企业估值归档仅可非严格读取，不代表当前完成。新 ETF 必须重建来源与 NAV 契约，不能机械改版本号；本次不迁移任何真实归档。离线合成样本见 `scripts/test_stage4a_etf.py`，不是正式研究证据。

### 双门与保存

按 `dashboard_schema.json` 生成 `research_only` Dashboard，并依次运行：

1. `dashboard_gate.py <dashboard.json> --strict-current-contract`
2. `dashboard_math_gate.py <dashboard.json>`

Dashboard 必须绑定已通过门禁的同代码 Research Brief，且证据层级、市场和资产类型闭合。旧版本归档只可兼容读取；兼容通过不代表符合当前新建契约。

严格当前契约不接受段落说明、测试域名或本机地址充当 `source_locator`。定位必须是可解析的公开 HTTP(S) URL、规范 SEC accession/CIK 标识，或属于已登记命名空间的 `dataset://` URI；每项证据和估值输入还须提供时区化 `retrieved_at` 与小写 `content_sha256`。摘要字段只证明已声明内容具有稳定指纹，无法替代对原文的重新获取和比对。

`freshness_flags` 使用由证据覆盖派生的状态，不再使用四个自报布尔值。行情证据闭合时为 `fresh`；历史披露保持 `historical`；没有新闻扫描时为 `not_assessed`；没有持仓上下文时为 `not_applicable`。声明状态与证据、日期或持仓输入不一致时，Dashboard 门禁失败关闭。

只有用户另行批准持久化，才运行 `save_dashboard.py`。JSON 是规范输入，Markdown 只供阅读。发布必须使用不可变 generation 和带 SHA-256 的索引提交点；索引失败、latest 未前进或输入身份变化时命令失败，不得让未索引文件进入 Daily Sync。
