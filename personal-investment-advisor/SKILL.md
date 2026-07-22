---
name: personal-investment-advisor
description: 基于当前行情、公司原始披露、财务数据和用户明确提供的持仓，执行证券身份核验、研究任务约束、方法化筛选、公司研究、估值情景、组合风险审计和结果校准。用于“股票调研”“分析财报”“持仓审计”“批量筛选”“情景压力测试”“复盘投资判断”等请求；仅提供研究与决策支持，不执行交易，也不替代持牌投资、税务或法律意见。
---

# 投资研究与组合分析

## 边界

- 明确证券市场、资产类型、估值日期、投资期限、基准、币种和用户目标。涉及个人持仓时，只读取用户提供或明确授权的文件。
- 对当前价格、财报、监管信息和公司事件进行联网核验并标注数据时间。优先公司公告、交易所、监管文件和审计财报。
- 不承诺收益，不把模型结果写成确定价格目标，不因组合容量或技术信号直接推导买卖动作。
- 不执行订单、登录券商、同步账户或改变组合。券商数据访问、日志写入和任何持久化均需单独明确授权。
- 对缺失、冲突或无法定位到原始材料的数据使用 `unknown`、`data_gap` 或 `insufficient_evidence`，不得用零值、默认通过或模拟内容替代。

## 环境与输入

- 使用脚本前检查 `scripts/requirements.txt` 和对应 `--help`；不要自动安装依赖或修改全局环境。
- 美股公司股票线上核验需要设置 `PIA_SEC_USER_AGENT`，使用包含真实联系邮箱的描述性 SEC User-Agent；不得把测试占位地址用于正式研究。
- 使用 `references/research_brief_schema.json` 定义研究任务；使用 `references/method_profiles.json` 选择方法配置。
- 组合文件必须符合 `references/portfolio_schema.json`。`references/portfolio_positions.example.json` 只是结构示例，不代表用户持仓。

## 工作流

1. **核验证券身份**：运行 `python scripts/instrument_gate.py --symbol <代码> --market <CN|HK|US> --asset-type <类型>`。对美股公司股票继续运行 `python scripts/live_evidence_probe.py --symbol <代码> --market US --asset-type stock`，只有实时行情、Nasdaq 身份、SEC 代码与交易所关联、EDGAR 最新披露四项交叉核对均通过时才进入研究。该自动探针不适用于 ETF、基金、ADR 边界案例及中港股；这些标的必须改用对应交易所、监管机构和发行人原始披露，并保留同等字段的来源定位。
2. **锁定研究契约**：创建研究 Brief，运行 `python scripts/research_brief_gate.py <brief.json>`。没有期限、基准、市场共识、核心假设、证伪条件、关键变量和来源截止日期时，不进入深度研究。
3. **选择研究方法**：按任务选择方法配置。运行 `python scripts/quality_screener.py --tickers <代码...> --profile <profile> --format json`。筛选结果只表示通过当前方法的初筛；`insufficient_data` 不得视为通过。
4. **采集带时间点的数据**：
   - 通用行情与财务：`python scripts/yf.py <代码...> --json`
   - A股补充数据：`python scripts/akshare_fetcher.py <args>`
   保存原始响应或明确其来源定位、发布日期、获取日期和研究截止日期。核对币种、复权、一次性项目、股本变化、会计期间和数据缺口。
5. **建立预期差账本**：对关键变量分别记录市场预期、公司指引或实际结果、独立研究判断、差异、估值影响及可能推翻结论的证据。新闻数量或措辞不能单独构成 thesis 成立或破坏。
6. **分析管理层承诺**：仅使用有来源定位的原始材料运行 `python scripts/management_claim_tracker.py <input.json>`，比较历史承诺与实际结果。只输出 `met`、`missed` 或 `insufficient_evidence`，不得推断诚实、欺诈或主观动机。测试夹具必须显式设置 `test_mode`，其结果不得进入正式 Dashboard。
7. **建立情景与组合约束**：对公司研究建立基础、乐观和悲观情景，列出估值方法、关键假设及敏感性。组合压力测试只使用用户显式提供的情景收益和约束，运行 `python scripts/portfolio_scenario_analyzer.py <portfolio.json> <assumptions.json>`；不得由历史涨跌幅自动生成预期收益。
8. **执行双层验证**：
   - 机器层：重新计算数字，核对来源、日期、单位、币种、期间和字段完整性。
   - 判断层：检查最强反方论点、历史基准率、市场是否已定价、关键变量敏感性和 thesis 失效条件。复杂任务可把证据采集、模型计算和反方审查拆给独立子代理；保留单代理降级路径，并保留冲突。
9. **生成并验证报告**：按 `references/dashboard_schema.json` 组织输出，运行 `python scripts/dashboard_gate.py <dashboard.json>` 和 `python scripts/dashboard_math_gate.py <dashboard.json>`。`thesis_mode` 必须携带已经通过门禁的 `research_brief`。
10. **检查持仓约束**：运行 `scripts/watchlist_gate.py` 只检查已有 Dashboard 中的止损、止盈、价格和催化提醒。组合模块只报告权重、集中度、流动性数据缺口和约束资格；是否采取动作仍需独立研究结论。

## 输出

- 数据截止时间、来源层级和原始定位；
- 市场共识、投资论点、预期差和反证；
- 财务质量、估值方法、假设和敏感性；
- 基础、乐观、悲观情景；
- 风险、催化剂、数据缺口和需要继续核验的问题；
- 若有持仓：集中度、相关性与流动性证据或数据缺口、下行情景和约束状态；
- 将事实、计算、假设和观点分开。数据不足或相互冲突时降低结论强度。

## 结果校准与持久化

- 只有用户明确要求时，才运行 `scripts/advice_journal.py`、`scripts/sync_outcomes.py`、`scripts/decision_outcome_report.py` 或保存论点；写入前展示内容和位置。
- 记录研究截止日期、方法配置、固定评价期限、基准、方向、实际执行价、`open` 或 `close` 执行时点、交易成本和证据快照。没有真实执行价或执行时点的建议不得进入收益校准。
- 校准只比较方向调整后的标的收益与同期基准收益，并扣除显式交易成本；不同期限分开统计。
- 日线同时触发止损和止盈时，先使用标的与基准的 5 分钟数据判定首个触发并对齐基准时点。盘中数据缺失或同一盘中柱仍无法判序时，默认按止损优先形成 `assumption_based_conservative` 样本；也可在研究 Brief 中将 `dual_trigger_policy` 设为 `exclude`。保守假设样本单独统计，不进入观测型校准主指标。
- 涉及税务、法律、杠杆、衍生品、退休资金或重大资产配置时，说明专业风险，并建议用户行动前咨询合格专业人士。
