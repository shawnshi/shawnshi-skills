# 用户确认的风险预算：离线比较

只有用户明确提供期限策略（有限天数或明确不设上限）、下行损失预算、单一非现金标的上限和最低现金占比时，才运行 `python -B scripts/personal_risk_budget.py <scenario_report.json> <budget.json>`。不读取账户、净资产、券商或目录中的其他文件；不替用户推断风险承受能力。报告必须是完整的 `portfolio_scenario_analyzer.py` v2 结果（`valid=true`、`status=ok`），不能以部分覆盖的风险诊断或旧档案代替。每个场景必须有**成本后**组合收益，缺少任何一项即失败关闭。

预算须有 `schema_version="pia_personal_risk_budget_v1"`、`source_type="user_confirmed"` 和带时区的 `confirmed_at`。有限期限使用正整数 `horizon_days`（兼容旧输入，默认 `horizon_policy="finite"`）；明确不设期限上限时必须写 `horizon_policy="unbounded"` 且 `horizon_days=null`，不得擅自换算为一年或其他天数。其余字段包括 `max_loss_fraction`、`max_single_non_cash_weight`、`minimum_cash_weight`（均为 0–1 的比例）、与报告场景恰好相等的 `required_scenarios`，以及对报告完整原始字节算出的 `scenario_report_sha256`。先由用户确认预算和场景集，再生成预算输入；脚本不保存、更改或补造预算。

结果只比较**已提供场景**的最差成本后收益、已核验快照的最大非现金标的权重和现金占比，并列出每项约束是否越界。不设持有期限上限不代表模型已覆盖所有时间跨度的损失。`status=complete` 不是风险已充分覆盖；`budget_status=within_supplied_scenarios` 不证明未建模损失、行业共振或家庭现金需求可控。报告快照的时间与“当前”分开，当前组合主张还须通过 Daily Sync 的时效与身份门。脚本不提供目标仓位或交易方向；行业／风格、真实流动性和个人负债仍未测量。输入中仅包含完成本任务所必需的最小用户确认字段，不自动调用公开搜索服务传输私人金额。
