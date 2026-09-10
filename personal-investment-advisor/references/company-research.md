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

## 6. Dashboard 7.2 显式新契约（不迁移旧原件）

上述 7.1 / stock2.0 / ETF1.0 是保留的旧分支；7.2 不是给旧原始数据换标签。新语义必须设置顶层 `dashboard_contract_version="7.2"`，Brief `source_policy.timing_contract_version="1.0"`、`cutoff_at`（含时区和秒，UTC 日期等于 `cutoff_date`）。目录容器/解析器为 7.2，显式接受 7.0/7.1/7.2；旧未显式标记的有效输入仍标记 7.1，不因解析器升级而升级记录。不可变 JSON/Markdown/哈希不改动。

### stock3.0 普通股权益

`scenario_analysis.valuation_contract_version="3.0"`；方法为 `enterprise_value_bridge`、`DDM` 或 `FCFE`。币种必须与 Brief 一致，不做隐式换汇或百万/亿单位缩放。每情景 `ordinary_equity_bridge` 必须恰含六项：`enterprise_value`、`net_debt`、`nonoperating_assets`、`noncontrolling_interest`、`preferred_claims`、`other_senior_claims`。桥公式：EV − 真净债务 + 非经营资产 − 少数股东权益 − 优先股索偿 − 其他优先索偿。净债务仅为债务减现金，可为负，绝不能吸收少数股东、投资资产或优先股；其他桥金额非负。

每项为 `{value,status,unit,currency,as_of_date,evidence_index,value_type,measurement_basis,rationale,claim_ids}`：`unit="currency"` 表示未缩放的币种总额；来源索引从 0 开始，绑定一手证据。`status="included"` 时须为有限数值；`reported_fact` 仅在确为报告事实时使用；不确定经济价值用 `analyst_estimate` + `measurement_basis="estimated_economic_fair_value"` 和明确估算依据/局限。经济调整不得把 `reported_amount` 当市场值（真净债务及股数可用报告金额）；直接报告的市场值为 `reported_market_value`。账面参考可写在依据中，不自动等于市场值。

不适用不是缺失/未知：调整须显式 `status="not_applicable",value=null,value_type="not_applicable",measurement_basis="not_applicable",claim_ids=[]`，并保留日期、来源、币种、单位及理由。EV 与净债务在桥方法中必须给数值，不可省略或默认零。`claim_ids` 使用经济工具唯一标识，不是文档 ID；每情景分子与股数间都不得重复，不得给同一工具改名规避审计。

`share_basis={basis,as_of_date,ordinary_shares,incremental_shares}`；`basis` 为 `current_diluted` 或 `hypothetical_as_converted`，股数分项用同一来源组件形状但 `unit="shares"`，全部同一股数日期。显式空增量列表表示无增量；假设转换必须列出增量。普通股数加增量重算 `diluted_shares`，`equity_value/diluted_shares` 重算每股值。不得既扣减同一优先索偿又把其假设转换加入分母；实际与假设稀释必须分开说明。标识只能发现结构重复，不能自动识别同一工具的不同别名，独立研究复核仍必须核对经济实质。

DDM/FCFE 不虚构企业价值或净债务：六个公司桥组件均为有来源的不适用项，情景顶层 `enterprise_value`、`net_debt` 为字符串 `not_applicable`；`ordinary_equity_cashflows` 为非空组件列表，增加 `cash_flow_kind`、`years>0`、`discount_rate`（比例且 0<r<1）。DDM 用 `dividend`，FCFE 用 `fcfe`（允许负现金流），终值用 `terminal_ordinary_equity`。重算普通股权益为 Σ value/(1+r)^years；最多一个终值，不早于最后显式现金流，终值不得再次包含该期显式分配。每项的 value 为未来普通股现金流/普通股终值的透明模型假设，绝不视为已报告未来事实。敏感性、三情景与证伪条件仍保留。

### precision-aware public source timing1.0

7.2 的一手非报价证据显式带 `timing_contract_version="1.0"`、`publication_precision`、`published_at`、`availability_observed_at`、`valuation_date`、`source_capture_receipt`。`exact` 的 published_at 必须是真实含时区发布时间且不晚于观测；`day` 则 published_at=null，另有 `publication_date` 和 `publication_utc_offset`；`unknown` 则 published_at=null，不捏造发布日期。day 仅给日级披露信息，不能把午夜当首次发布，更不能自动满足该日较早的日内 cutoff。

一手公开内容在 cutoff 前实际捕获可用于当前研究，不强求来源没有公布的首次发布时间秒数；须满足 `valuation_date <= observed availability (UTC date)` 和 `observed <= retrieved <= cutoff_at`，所有时刻不在未来。NAV 的 valuation_date 同时绑定 NAV 估值日，tracking 绑定 period_end。identity/fees/所有已声明其他 ETF 观测同样适用，不仅 NAV。二手来源不能借此替代一手不明发布时间；旧式二手证据在 7.2 必须用实际精确 publication/retrieval <= cutoff。报价仍走实际 observed_at/retrieved_at + 市场状态秒级时效门，不能用 availability_observed_at 更新陈旧报价。

ETF 新分支为 `etf_research.contract_version="1.1"` 与 `valuation_contract_version="etf_nav1.1"`；`premium_discount_basis="quote_vs_observed_nav"` 不声称最近已知首次公布 NAV 或同时点公允价值。NAV、身份、total_expense_ratio 和 tracking 核心门及 5 个日历日 NAV 窗口不变；不以价格代 NAV、管理费代 TER。旧 ETF1.0 的精确 published_at 语义不改变。

### 原件重验与小型回执（新建/发布必做）

`source_timing_contract.verify_source_capture(raw_path, source_locator=..., availability_observed_at=..., retrieved_at=..., expected_sha256=..., expected_receipt=...)` 仅打开调用者显式授权的本地非空普通文件（非符号链接、最大 32 MiB），不扫描、不联网。先以真实取证日志提供 URL/观测/获取时刻，再对完整原件 bytes 重算 SHA；不可从 mtime 或本次重验时刻反推过去观测。回执含 `contract_version="1.0"`、`verification_method="sha256_raw_bytes_v1"`、`raw_artifact`、`source_locator`、`content_sha256`、`byte_count`、`availability_observed_at`、`retrieved_at`、`verified_at`。Dashboard 保存同一 content_sha256 和精确匹配的 URL/观测/获取时刻；回执只是结构链，原件不复制进 JSON。片段指纹不得冒充完整原件指纹。

复验时显式传入实际文件、预期 SHA 和已有回执，源 bytes/定位/时刻绑定不符即失败；`verified_at` 为本次重验时间，允许晚于研究 cutoff，但不扩大历史可得窗口。Dashboard/save/catalog 不自动解引用 raw_artifact；离线旧档无需原件仍可读取。**单独结构双门通过不证明来源真实、内容语义正确或历史可得。新建/发布方必须实际运行原件复验并独立核对原始取证记录与引用内容**。取得观测时刻的可信性依赖取证日志，不由 hash 自动证明。

最小可运行合成构建例见 `scripts/test_dashboard_v72_contract.py` 的 `synthetic_stock` / `synthetic_timed_etf`，其中所有数值、来源内容和主体均为隔离测试，不是实际投资证据。
