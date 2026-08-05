# 组合审计与情景分析

## 持仓契约

组合必须通过 `portfolio_schema.json` v3.0。每条记录显式提供：

- `symbol`、`quantity`、`avg_cost`、`currency`；
- `market`：`CN`、`HK`、`US` 或 `CASH`；
- `asset_type`：`stock`、`etf`、`fund`、`index`、`cash` 或 `other`。

旧 `market_type` 只能作为被忽略的展示字段，不能满足或覆盖身份。现金身份必须同时满足 `CASH` 或 `CASH_*` 代码、`market=CASH` 和 `asset_type=cash`。

`quantity > 0` 才是活动持仓；零数量记录保留供审计，但排除市值、权重、风险、观察边界和情景计算。负数、非有限数字以及零数量配正权重必须失败关闭。现有旧组合不能根据代码或名称自动推断新字段，迁移前应逐项确认。

持仓文件中的旧 `current_weight` 只作为陈旧派生字段留痕，加载时会被剥离，不参与集中度、市场暴露或约束判断。当前权重必须由本次通过门禁的行情与汇率重新计算。

用户明确授权导入券商 CSV 后才运行 `broker_sync.py`。每行须由来源提供上述六个字段；任一关键字段缺失或无效时整批拒绝并保持原文件不变。

组合根不得内嵌 `rebalance_policy`；分配实验策略必须使用独立、显式版本的 policy 文件。用户自行提供的 `target_weight` 或 `max_weight` 只作为输入约束供观察，不得由脚本生成、重分配或写回。

## 当前权重与汇率

当前权重只能使用通过严格身份、覆盖和时效检查的 `pia_daily_sync_offline_v3` 报告；报告生成时间距本次计算超过 15 分钟时不再视为当前证据。计算端会重新读取并核对报告所绑定的持仓文件与原始行情包，按消费时点和 `market_state` 重算每条行情的实际年龄，不接受报告自报的空陈旧清单代替计算。持仓数量或身份字段在同一路径发生变化、原始行情包被改写、市场状态缺失或未知时均失败关闭。显式历史重放也执行相同绑定和时效核对，并标记为 `explicit_point_in_time_replay`，不得写成当前权重。

跨币种计算还必须有带 `pair`、`as_of`、`source`、`source_locator` 和 `retrieved_at` 的汇率快照；当前上限为 72 小时。旧平面汇率标记为 `undated_static`，陈旧或无法定位的快照不得据此声称得到当前权重。

组合模块只报告原始权重、集中度、流动性数据缺口和约束状态。没有显式 `risk_profile` 时风险等级保持未知；不得把约束状态改写为组合动作。

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

分配计算始终是 `research_only` 实验：不得执行交易，不得把实验结果写回持仓，不得生成订单、止损止盈或默认仓位上限。策略遵循 `inverse_volatility_policy_schema.json`，结构参考 `inverse_volatility_policy.example.json`；具体离线参数和失败条件以 `rebalance_weights.py --help` 及专属测试为准。没有显式策略、已验证行情包、完整分桶和必要汇率时不计算。

当前方法名为 `inverse_volatility_allocation`。它忽略相关性，不能称为风险平价；波动率观测必须带期间、样本数、日期、来源和定位。实验输出使用 `experimental_weight`，不等于目标权重或操作建议。
