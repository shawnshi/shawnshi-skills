# 公司研究工作流

## 1. 锁定身份与时间点

先运行 `instrument_gate.py`，显式给出代码、市场和资产类型。美股公司股票再运行 `live_evidence_probe.py`，交叉核对实时行情、Nasdaq 身份、SEC CIK、交易所关联和 EDGAR 最新披露。若 SEC ticker 映射端点不可用，可传入已由用户或原始材料确认的 `--cik`，探针会直接访问 submissions 并反向核对代码、交易所和 CIK；不得猜测 CIK。Yahoo chart 未返回 `marketState` 时，只能从其 `currentTradingPeriod` 推导并显式标注来源，时效阈值仍失败关闭。正式 SEC 请求必须设置包含真实联系邮箱的 `PIA_SEC_USER_AGENT`；测试占位地址不得进入正式研究。

自动探针不覆盖 ETF、基金、ADR 边界案例及中港股。这些标的须改用交易所、监管机构和发行人原始披露，并保留证券代码、交易所、币种、资产类型、来源定位、发布日期和获取时间。

## 2. 建立研究 Brief

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

新建研究使用结构化基础、乐观和悲观三种估值情景。每个情景记录方法、日期、币种、显式假设、企业价值、净债务、股权价值、稀释股数、每股结果和证伪条件；敏感性区间必须包围基础情景。`dashboard_math_gate.py` 重算企业价值到股权价值、每股价值、情景排序和敏感性排序；它不从 DCF、倍数或其他方法假设重新推导企业价值，因此该上游估值仍需单独复核。

按 `dashboard_schema.json` 生成 `research_only` Dashboard，并依次运行：

1. `dashboard_gate.py <dashboard.json> --strict-current-contract`
2. `dashboard_math_gate.py <dashboard.json>`

Dashboard 必须绑定已通过门禁的同代码 Research Brief，且证据层级、市场和资产类型闭合。旧版本归档只可兼容读取；兼容通过不代表符合当前新建契约。

严格当前契约不接受段落说明、测试域名或本机地址充当 `source_locator`。定位必须是可解析的公开 HTTP(S) URL、规范 SEC accession/CIK 标识，或属于已登记命名空间的 `dataset://` URI；每项证据和估值输入还须提供时区化 `retrieved_at` 与小写 `content_sha256`。摘要字段只证明已声明内容具有稳定指纹，无法替代对原文的重新获取和比对。

`freshness_flags` 使用由证据覆盖派生的状态，不再使用四个自报布尔值。行情证据闭合时为 `fresh`；历史披露保持 `historical`；没有新闻扫描时为 `not_assessed`；没有持仓上下文时为 `not_applicable`。声明状态与证据、日期或持仓输入不一致时，Dashboard 门禁失败关闭。

只有用户另行批准持久化，才运行 `save_dashboard.py`。JSON 是规范输入，Markdown 只供阅读。发布必须使用不可变 generation 和带 SHA-256 的索引提交点；索引失败、latest 未前进或输入身份变化时命令失败，不得让未索引文件进入 Daily Sync。
