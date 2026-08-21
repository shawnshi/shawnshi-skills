# 命令目录

运行前先检查 `scripts/requirements.txt` 与命令 `--help`。不要自动安装依赖或修改全局环境。

## 稳定入口

优先运行 `python scripts/pia.py --help` 查看稳定子命令。该入口只做参数路由和状态归一，不绕过底层业务门禁。若某个子命令尚未接通，必须返回非零和结构化未完成状态。

## 直接门禁与分析命令

- 证券身份：`instrument_gate.py`
- 美股实时证据：`live_evidence_probe.py`
- 研究 Brief：`research_brief_gate.py`
- 财务筛选：`quality_screener.py`
- 通用行情与财务：`yf.py`
- A 股补充数据：`akshare_fetcher.py`
- ETF 历史完整性：`history_integrity_gate.py`
- 管理层承诺：`management_claim_tracker.py`
- Dashboard 结构与数学：`dashboard_gate.py`、`dashboard_math_gate.py`
- Dashboard 目录：`dashboard_catalog.py`
- 观察边界：`watchlist_gate.py`
- 组合情景：`portfolio_scenario_analyzer.py`
- 分配实验：`rebalance_weights.py`
- 券商 CSV 导入：`broker_sync.py`，仅在用户明确授权时运行
- Daily Sync：`yf.py --daily-sync --cache-dir <task-cache> [--daily-sync-workers 1..4]` 后接 `daily_sync.py`；完成事件红队时传入 `--thesis-evidence-file`
- 研究日记与结果同步：`advice_journal.py`、`sync_outcomes.py`、`decision_outcome_report.py`
- Dashboard 归档：`save_dashboard.py`，仅在用户另行批准持久化时运行

需要精确参数时以对应 `--help` 为准；文档中的示例不得覆盖脚本当前契约。

`scenario --output` 不得解析为组合或假设输入文件；`calibrate --output-path` 不得解析为研究日记。两个写出命令均使用同目录临时文件完成后再原子替换，冲突或写出失败时保留输入文件。
