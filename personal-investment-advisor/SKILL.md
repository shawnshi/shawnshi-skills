---
name: personal-investment-advisor
description: 基于当前行情、公司原始披露、财务数据和用户明确提供的持仓，执行证券身份核验、研究任务约束、方法化筛选、公司研究、估值情景、组合风险审计和研究复盘。用于“股票调研”“分析财报”“持仓审计”“批量筛选”“情景压力测试”“复盘投资判断”等请求；仅输出 research_only 研究支持，不生成交易指令，也不替代持牌投资、税务或法律意见。
---

# 投资研究与组合分析

## 边界

- 明确证券市场、资产类型、估值日期、投资期限、基准、币种和用户目标。涉及个人持仓时，只读取用户提供或明确授权的文件。
- 对当前价格、财报、监管信息和公司事件进行联网核验并标注数据时间。优先公司公告、交易所、监管文件和审计财报。
- 不承诺收益，不把模型结果写成确定价格目标，不因组合容量或技术信号直接推导买卖动作。
- 所有 Dashboard 和归档报告固定为 `research_only`。不得生成方向、仓位、进出场、止损止盈、订单或其他可直接执行的交易指令。
- 不执行订单、登录券商、同步账户或改变组合。券商数据访问、日志写入和任何持久化均需单独明确授权。
- 对缺失、冲突或无法定位到原始材料的数据不得用零值、默认通过或模拟内容替代。研究与观察门禁的顶层状态统一为 `ok`、`not_applicable`、`insufficient_evidence`、`insufficient_data`、`data_error` 或 `invalid`，业务细分放入 `detail_status`；Daily Sync 批次编排另用 `complete`、`incomplete`、`invalid_input` 表示流程闭合度。自然语言中的 `unknown` 与 `data_gap` 只能作为结论强度或缺口说明，不能替代机器状态。

## 环境与输入

- 使用脚本前检查 `scripts/requirements.txt` 和对应 `--help`；不要自动安装依赖或修改全局环境。
- 美股公司股票线上核验需要设置 `PIA_SEC_USER_AGENT`，使用包含真实联系邮箱的描述性 SEC User-Agent；不得把测试占位地址用于正式研究。
- 使用 `references/research_brief_schema.json` 定义研究任务；使用 `references/method_profiles.json` 选择方法配置。
- `method_profiles.json` 中的阈值是可替换的方法假设，不是普遍业务事实。正式筛选必须记录所选配置、版本、适用资产类型和研究截止日期；没有匹配配置时返回 `insufficient_evidence`。
- 组合文件必须符合 `references/portfolio_schema.json`。`references/portfolio_positions.example.json` 只是结构示例，不代表用户持仓。
- 组合文件中 `quantity > 0` 才是有效持仓；`quantity == 0` 是保留供审计的非活动记录，必须报告但不得纳入市值、权重、风险、观察边界或情景计算；负数量、非有限数值以及零数量配正权重必须硬失败。
- 跨币种实时权重必须使用带 `pair`、`as_of`、`source` 和 `retrieved_at` 的汇率快照。旧平面汇率只能标为 `undated_static`，不得据此声称已按最新汇率完成市值或权重计算。
- 只有用户明确授权导入券商 CSV 时才运行 `scripts/broker_sync.py`。每行必须由来源提供 `symbol`、`quantity`、`avg_cost`、`currency` 和 `market_type`；任一关键字段缺失或无效时整批拒绝且不写入，非关键字段缺失时保持未知或省略。

## 工作流

1. **核验证券身份**：运行 `python scripts/instrument_gate.py --symbol <代码> --market <CN|HK|US> --asset-type <类型>`。对美股公司股票继续运行 `python scripts/live_evidence_probe.py --symbol <代码> --market US --asset-type stock`，只有实时行情、Nasdaq 身份、SEC 代码与交易所关联、EDGAR 最新披露四项交叉核对均通过时才进入研究。该自动探针不适用于 ETF、基金、ADR 边界案例及中港股；这些标的必须改用对应交易所、监管机构和发行人原始披露，并保留同等字段的来源定位。
2. **锁定研究契约**：创建研究 Brief，运行 `python scripts/research_brief_gate.py <brief.json>`。没有期限、基准、市场共识、核心假设、证伪条件、关键变量和来源截止日期时，不进入深度研究。
3. **选择研究方法**：按任务选择方法配置。运行 `python scripts/quality_screener.py --tickers <代码...> --profile <profile> --market <CN|HK|US> --asset-type <stock|etf|fund|index> --as-of-date <YYYY-MM-DD> --format json`；银行和保险另加 `--industry-type <bank|insurance>`。筛选结果只表示通过当前方法的初筛；`insufficient_data` 不得视为通过。ETF 使用 `etf_research` 证据型档案，财务质量筛选必须返回 `not_applicable`，再转为核验身份、跟踪指数与方法、费率、复制方式、规模与流动性、NAV 折溢价、跟踪差异、持仓集中和份额调整；不得把空财务阈值解释为通过。
4. **采集带时间点的数据**：
   - 通用行情与财务：`python scripts/yf.py <代码...> --json`
   - A股补充数据：`python scripts/akshare_fetcher.py --symbol <六位代码> --mode <enhanced|history> [--start YYYY-MM-DD --end YYYY-MM-DD]`；增强行情和筹码供应商在可终止子进程中运行，超时或连接失败必须回收子进程并输出 `insufficient_data`，不得修改主进程代理环境或用旧值补齐。
   - A股历史来源切换：`python scripts/yf.py <代码...> --json --a-share-history-source <akshare|auto|yahoo>`；`akshare` 失败关闭，`auto` 才允许显式回退 Yahoo。
   保存原始响应或明确其来源定位、发布日期、获取日期和研究截止日期。核对币种、复权、一次性项目、股本变化、会计期间和数据缺口。ETF 在计算收益、回撤、均线、RSI 或 ATR 前，先运行 `python scripts/history_integrity_gate.py <packet.json>`，以交易所或基金管理人公司行动覆盖结果核对数据提供方事件；该独立命令只验证证据包并输出 `packet_verified`，即使退出码为0也不授权任何未绑定序列的技术指标。随后必须把同一证据包通过 `yf.py --history-integrity-file <packet.json>` 绑定到本次实际历史序列；只有 `history_integrity.detail_status=series_bound_verified` 且 `technical_metrics_allowed=true` 才可输出衍生指标。官方覆盖的带时区获取日期不得早于研究截止日期，任何纳入比对的公司行动生效日不得晚于研究截止日期；包内截止日期不得早于实际序列末日，数据提供方、来源定位和复权方式必须逐项一致。没有包、零结果但无非零控制查询、事件冲突、时间不闭合、运行时序列绑定失败或证券身份未知时停止输出全部历史衍生技术指标，当前原始报价仍可单独参加持仓匹配。
5. **建立预期差账本**：对关键变量分别记录市场预期、公司指引或实际结果、独立研究判断、差异、估值影响及可能推翻结论的证据。新闻数量或措辞不能单独构成 thesis 成立或破坏。
6. **分析管理层承诺**：仅使用有来源定位的原始材料运行 `python scripts/management_claim_tracker.py <input.json>`，比较历史承诺与实际结果。只输出 `met`、`missed` 或 `insufficient_evidence`，不得推断诚实、欺诈或主观动机。测试夹具必须显式设置 `test_mode`，其结果不得进入正式 Dashboard。
7. **建立情景与组合约束**：对公司研究建立基础、乐观和悲观情景，列出估值方法、关键假设及敏感性。组合压力测试只使用用户显式提供的情景收益和约束，运行 `python scripts/portfolio_scenario_analyzer.py <portfolio.json> <assumptions.json>`；不得由历史涨跌幅自动生成预期收益。旧版组合情景包省略 `scenario_contract_version` 时按 `1.0` 读取并要求 `base`、`bull`、`bear`；需要用户自定义情景名、外汇冲击、分桶政策、逐标的成本或波动率贡献诊断时，必须显式设置 `scenario_contract_version: "2.0"`。v2 还必须提供 `weight_snapshot`，以带日期、来源和定位的基础币种市值逐项覆盖全部活动持仓并与 `current_weight` 在固定容差内闭合；存在非基础币种资产时，必须同时提供有日期、来源和定位的正数即期汇率，缺失或按1:1替代均失败关闭。活动持仓权重必须在固定数值容差内合计为1，收益标的集合必须与活动持仓完全相等，不得自动归一化或忽略额外代码。数字型 `asset_returns` 始终表示已经折算为基础币种的总收益；跨币种本币收益必须改用 `local_total_return` 对象，并同时提供带日期、来源和定位的对应 `fx_returns`，按 `(1+r_local)*(1+r_fx)-1` 换算。分桶政策必须显式列出范围、排除资产及原因，不得从代码或名称推断80/20、行业或币种归类。逐标的成本按 `weight*turnover*bps/10000` 计算；没有完整显式成本时成本后收益保持未知。旧字段 `transaction_cost_estimate` 只表示兼容模式的统一成本，逐情景模型必须读取 `transaction_cost_summary.by_scenario` 及其状态，不得把旧字段的 `null` 解释为未建模。只有提供闭合、对称且半正定的显式波动率和相关矩阵时才计算波动率贡献；该诊断不得称为风险平价、优化权重或交易建议。
8. **执行双层验证**：
   - 机器层：重新计算数字，核对来源、日期、单位、币种、期间和字段完整性。
   - 判断层：检查最强反方论点、历史基准率、市场是否已定价、关键变量敏感性和 thesis 失效条件。复杂任务可把证据采集、模型计算和反方审查拆给独立子代理；保留单代理降级路径，并保留冲突。
9. **生成并验证报告**：按 `references/dashboard_schema.json` 组织 `research_only` 输出。新生成 Dashboard 必须包含三情景估值、显式假设、敏感性与证伪条件，并运行 `python scripts/dashboard_gate.py <dashboard.json> --strict-current-contract` 和 `python scripts/dashboard_math_gate.py <dashboard.json>`；已有 v6.1 归档可用兼容模式只读复核，但兼容通过不等于符合当前新建合同。每份 Dashboard 都必须携带已经通过门禁且 `decision_scope=research_only` 的 `research_brief`；证券代码必须一致，A股、港股、美股的市场与 `stock` 类型以及 ETF 的 `etf` 类型必须与 Brief 闭合，`其他` 只接受 `fund`、`index` 或 `other`；只输出证据核验、证伪检查和观察指标。只有用户另行批准持久化时，才运行 `python scripts/save_dashboard.py --stock <证券代码> --file <dashboard.json> --output-dir <归档根目录>`，且 `--stock` 只能匹配 `dashboard.stock_code`。脚本先在同一父目录内将 JSON 与 Markdown 作为一个不可变 generation 原子发布，再独立原子更新 `dashboard_index.json`；索引是后续读取的唯一提交点，必须记录两份文件的 SHA-256，读取时复核哈希及 Markdown 内嵌的规范 JSON。latest 指针和索引顶层更新时间只能单调前进；只有本次 generation 成为 latest 且索引确实更新时，CLI 才能成功。索引提交失败或因单调性规则保留旧指针时，命令必须失败并保留输入草稿；完整但未索引的 generation 可留待人工核验与处置，却不得被 Daily Sync 扫描或替代旧指针。`--delete-input` 只允许清理归档根目录之外、归档期间身份未变化的临时草稿；不得删除任何已归档 generation。JSON 是后续门禁的规范输入，Markdown 仅供阅读；不得只保留 Markdown，也不得在归档时迁移旧交易字段。
10. **检查持仓约束**：组合模块只报告权重、集中度、流动性数据缺口和约束状态，不把约束状态转写为组合动作。没有显式 `risk_profile` 时只计算可复核的原始指标，风险等级保持 `未知`。
11. **可选再平衡计算**：`scripts/rebalance_weights.py` 只有在提供显式再平衡策略时才计算目标权重。策略必须给出分桶、桶目标、最大权重缓冲、历史窗口和最少样本；无策略时只尝试更新当前市值权重，不生成目标权重或默认 5% 上限。

### Daily Sync（只读刷新）

1. 先验证组合文件，再列出全部 `quantity > 0` 的非现金标的。运行 `python scripts/yf.py <全部有效非现金代码...> --daily-sync --positions-file <portfolio.json>`，将标准输出保存到本次任务隔离的临时 `quotes.json`；该模式只请求当前报价与身份字段，不计算历史技术指标、不取新闻，并在顶层只输出一次 `portfolio_batch_audit`。随后运行 `python scripts/daily_sync.py --positions-file <portfolio.json> --quotes-file <quotes.json>` 做独立重放审计。
2. `yf.py` 顶层批次审计与 `daily_sync.py` 的 `completeness.complete` 必须同时为真。只有 `portfolio_load_status=ok`、请求数、结果记录数、有效行情数和持仓匹配数全部相等，且覆盖完整、重复/遗漏/额外请求/行情失败/持仓未匹配列表均为空，才可标记批量刷新完整。部分返回、限流、`UNKNOWN`、非活动记录、身份错配或无行情不得解释为没有风险；旧版每条记录重复携带且内容完全相同的批次审计只允许兼容读取并产生 warning。
3. 逐一核对返回的证券代码、交易所、币种、`quoteType`、行情时间和市场状态；缺少或陈旧时将对应结论标记为 `unknown`，不得以成本价、默认汇率、零值或其他标的行情替代。
4. 先运行 `python scripts/dashboard_catalog.py --root <归档根目录> --symbols <全部有效非现金代码...>`，按 `dashboard_index.json` 只读定位每个标的最新的 Dashboard v6.1 JSON。索引缺失、路径越界、文件损坏、证券代码不匹配、合同版本不符或门禁失败均返回 `insufficient_data`；不得搜索旧 Markdown 补位。只有目录结果为 `valid` 的条目，才继续运行 `python scripts/dashboard_gate.py <dashboard.json>`。
5. 观察边界只接受门禁通过的 Dashboard 中由用户明确确认、带来源定位且 `decision_scope=observation_only` 的 `monitoring_boundaries`；从 Daily Sync 的 `quote_snapshot` 为每个标的生成只存在于本次隔离临时目录的运行时行情对象，再运行 `python scripts/watchlist_gate.py <dashboard.json> --quote-snapshot <symbol_quote.json>`。运行时对象必须包含 `symbol`、`current_price`、`currency`、`as_of`、`source` 和 `market_state`。不得读取 Dashboard 内归档价格作为当前行情，不得创建缺失边界，也不得把旧字段自动迁移成有效边界。没有边界时细分状态为 `thresholds_undefined`；Dashboard 不存在或无效、行情缺失/陈旧、边界仅为 `unverified_legacy` 时返回证据或数据不足。接近规则也必须由用户明确给出，不能使用默认百分比。
6. `watchlist_gate.py` 只报告已经越界、接近边界、未越界、未定义或证据不足等观察事实，不输出方向、数量、订单或组合动作。`daily_sync.py` 固定把 Thesis 红队阶段标记为 `not_assessed/insufficient_evidence`；必须另行检索公司、行业、监管和宏观原始材料并逐条映射到历史 thesis 的证伪条件。没有新闻不能升级为“未发现致命事件”，股价变化也不能单独证明 Thesis 失效。

## 输出

- 数据截止时间、来源层级和原始定位；
- 市场共识、投资论点、预期差和反证；
- 财务质量、估值方法、假设和敏感性；
- 基础、乐观、悲观情景；
- 风险、催化剂、数据缺口和需要继续核验的问题；
- 若有持仓：集中度、相关性与流动性证据或数据缺口、下行情景和约束状态；
- 后续证据核验、证伪条件和观察指标；不得包含方向、价格或仓位指令；
- 将事实、计算、假设和观点分开。数据不足或相互冲突时降低结论强度。
- Schema、字段类型、日期、单位、币种、公式和用户显式约束可作为硬检查；关键词、是否含数字、标题措辞和疑似缺少量化只作 warning，不得单独阻断报告。

## 研究复盘与持久化

- 只有用户明确要求时才保存研究论点或证据快照；写入前展示内容和位置。
- 复盘固定期限内核心假设、证伪条件、关键变量和来源质量是否成立。标的与基准的后续表现只能作为研究校准证据，不能反向生成交易方向或操作建议。
- 用户另行提供的真实交易记录只可作为已发生事实分析，必须与本技能的研究输出隔离，不得把模拟进出场当作真实执行。
- 涉及税务、法律、杠杆、衍生品、退休资金或重大资产配置时，说明专业风险，并建议用户行动前咨询合格专业人士。
