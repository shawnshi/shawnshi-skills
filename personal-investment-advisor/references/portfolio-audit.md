# 组合审计与情景分析

## 持仓契约

仅对明确标记的假设资产标签与用户提供的权重做算术时，核验权重有限、非负、单位与口径一致、合计为 1（或 100%），不自动归一化；注明输入来源与假设范围，不要求真实持仓 Schema、行情或数量成本，不得声称当前权重或当前组合审计完成。此范围不适用下述真实持仓当前权重重算要求，也不得用于绕过情景脚本、分配实验或主动研究门禁。真实持仓组合必须通过 `portfolio_schema.json` v3.0，行情、来源与授权门保持不变。每条记录显式提供：

- `symbol`、`quantity`、`avg_cost`、`currency`；
- `market`：`CN`、`HK`、`US` 或 `CASH`；
- `asset_type`：`stock`、`etf`、`fund`、`index`、`cash` 或 `other`。

旧 `market_type` 只能作为被忽略的展示字段，不能满足或覆盖身份。现金身份必须同时满足 `CASH` 或 `CASH_*` 代码、`market=CASH` 和 `asset_type=cash`。

`quantity > 0` 才是活动持仓；零数量记录保留供审计，但排除市值、权重、风险、观察边界和情景计算。负数、非有限数字以及零数量配正权重必须失败关闭。现有旧组合不能根据代码或名称自动推断新字段，迁移前应逐项确认。

持仓文件中的旧 `current_weight` 只作为陈旧派生字段留痕，加载时会被剥离，不参与集中度、市场暴露或约束判断。当前权重必须由本次通过门禁的行情与汇率重新计算。

真实持仓导入是独立数据维护任务，不属于 advisory 参数建议的执行步骤；用户另行明确授权导入券商 CSV 后才运行 `broker_sync.py`。每行须由来源提供上述六个字段；任一关键字段缺失或无效时整批拒绝并保持原文件不变。验证通过后的快照通过唯一同目录临时文件、`fsync` 和原子替换提交，避免并发导入共享固定临时文件或中断写入截断原快照。

组合根不得内嵌 `rebalance_policy`；分配实验策略必须使用独立、显式版本的 policy 文件。用户提供的 `target_weight` 或 `max_weight` 在计算模块中作为输入约束，计算脚本不得自动重分配或写回。`advisory` 可在独立建议制品中给出价格、数量或目标仓位指令，但不写回实际持仓文件中的数量、成本、现金、成交状态或目标／约束字段。独立风险政策的已授权维护按 [SKILL.md](../SKILL.md#advisory-下的本地修改) 执行；不能借参数输出或维护绕过证据、可行性或 P0 门禁。

## 当前权重与汇率

当前权重只能使用通过严格身份、覆盖和时效检查的 `pia_daily_sync_offline_v3` 报告；报告生成时间距本次计算超过 15 分钟时不再视为当前证据。计算端会重新读取并核对报告所绑定的持仓文件与原始行情包，按消费时点和 `market_state` 重算每条行情的实际年龄，不接受报告自报的空陈旧清单代替计算。持仓数量或身份字段在同一路径发生变化、原始行情包被改写、市场状态缺失或未知时均失败关闭。显式历史重放也执行相同绑定和时效核对，并标记为 `explicit_point_in_time_replay`，不得写成当前权重。

跨币种计算还必须有带 `pair`、`as_of`、`source`、`source_locator` 和 `retrieved_at` 的汇率快照；当前上限为 72 小时。旧平面汇率标记为 `undated_static`，陈旧或无法定位的快照不得据此声称得到当前权重。

需要刷新 USD/CNY 即期证据时，使用 `yf.py CNY=X --price-only --period 5d --lean --json --cache-dir <task-cache>`，优先使用真实 `info.regularMarketPrice` 与 `info.regularMarketTime`，字段不足才取有日期的日线 Close。保留实际观测时间和字段来源；未来或陈旧观测拒绝，不以抓取时间替代。外汇代码的 `=X` 身份可闭合为非 ETF 历史，不得套用 ETF 公司行动缺口文案。行情命令本身不授权改写持仓，当前权重实验应使用绑定同一持仓内容的隔离快照，并保留原文件哈希。

组合模块只报告原始权重、集中度、流动性数据缺口和约束状态。没有显式 `risk_profile` 时风险等级保持未知；不得把约束状态改写为组合动作。个人决策预算是**另一个由用户提供的研究输入**：仅在用户明确授权并给出投资期限、可承受损失、必要现金需求、单一行业／风格上限和情景假设时，才比较候选方案与其约束。资料不足时列出未知、保留部分风险诊断，不能把短窗口相关矩阵、已覆盖子集的归一权重或不含未测量资产的风险贡献写成全组合风险。不得为了风险预算自动读取账户号、完整净资产、其他目录或无关私人历史。仅在用户确认的上述比例预算与完整 v2 成本后情景报告均可用时，按 [personal-risk-budget.md](personal-risk-budget.md) 执行独立离线比较；只称已给场景的约束结果，不称全组合风险覆盖。

## 情景压力测试

`portfolio_scenario_analyzer.py` 只消费用户明确提供的情景收益与约束，不从历史涨跌自动生成预期收益。

当前情景计算只接受显式 `scenario_contract_version: "2.0"`。缺少版本、v1 或缺少来源化权重快照的输入只可作为旧档案查看，不得进入计算。v2 必须提供：

- 覆盖全部活动持仓的 `weight_snapshot`；其 `source_locator` 只接受公开 HTTP(S) URL、规范 SEC accession/CIK 标识或已登记的 `dataset://` 命名空间，并同时提供不晚于运行日的时区化 `retrieved_at` 与小写 `content_sha256`；
- 与活动持仓完全相等的收益标的集合；
- 跨币种资产所需的带日期、来源和定位的即期汇率；
- 显式、互斥且闭合的分桶范围和排除原因；
- 计算风险贡献时，闭合、对称、半正定的波动率与相关矩阵。

活动权重须在固定容差内合计为 1，不自动归一化。数字型 `asset_returns` 表示已经换算为基础币种的总收益；本币收益须使用 `local_total_return` 并配套 `fx_returns`，按 `(1+r_local)*(1+r_fx)-1` 换算。成本按 `weight*turnover*bps/10000` 逐项计算；成本不完整时成本后收益保持未知。波动贡献只是诊断，不得称为风险平价、优化权重或交易建议。

## 分配实验

分配计算按声明的 `decision_scope` 产出，可给出该级别允许的方向或参数；计算命令不得把实验结果自动写回持仓，也不得代客下单或路由订单。另行执行已授权的本地维护时遵守 SKILL.md 的本地修改边界；advisory 的建议数量和目标仓位只写独立方案，不直接或间接改实际持仓，未过提升门的实验权重不得写成候选或目标权重。策略遵循 `inverse_volatility_policy_schema.json`，结构参考 `inverse_volatility_policy.example.json`；具体离线参数和失败条件以 `rebalance_weights.py --help` 及专属测试为准。没有显式策略、已验证行情包、完整分桶和必要汇率时不计算。

当前方法名为 `inverse_volatility_allocation`。它忽略相关性，不能称为风险平价；波动率观测必须带期间、样本数、日期、来源和定位。实验输出使用 `experimental_weight`，不等于目标权重；提升为 `candidate_weight`/`target_weight` 必须按 `decision_scope` 声明并另行过对应门禁。免费数据无法通过主动 Alpha 门禁时，这一风险型实验仍可独立运行，不得把结果升级为 Rank/Yank、`candidate_weight` 或 `allocation_gap`。

### 现金与政策分母

默认口径要求桶成员覆盖每个活动标的（含现金），且一个现金桶恰含一个现金头寸。当已确认策略把一个以上现金头寸排除在分母外（例如用户确认的 80/20 非现金分母口径）时，可在 policy 中显式声明 `denominator: "active_non_cash_market_value"` 与 `excluded_policy_symbols`（每条必须给出非空原因）：此时 `bucket_targets` 只对非现金范围求和为 1.0、桶成员只需覆盖全部活动非现金标的，现金保留在全组合压力损益中但不出现在实验结果里；不得给现金造零波动率，也不得以事后缩放掩盖分母差异。`rebalance_weights.py --policy-file` 消费该 policy 时会把 `denominator`、`excluded_policy_symbols` 与 `scope_symbols` 原样回声，便于下游明确分母口径。

## 主动组合研究的额外门禁

若请求包含主动收益、Rank & Yank、风险平价候选权重或再平衡提案，必须另读 `active-research.md`。现有 `rebalance_weights.py` 和 `rebalance_optimizer.py` 是描述性分配实验，不构成 Alpha 验证；完整主动链路必须先通过 P0 Alpha 推广门禁，再使用完整协方差矩阵、成本、换手与单标的变化约束生成非执行研究候选；advisory 可在适用门禁闭合后另行给出供用户手动执行的具体参数方案，候选输出本身不是交易就绪证明。
