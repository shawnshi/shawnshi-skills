# 命令目录

运行前先检查 `scripts/requirements.txt` 与命令 `--help`。不要自动安装依赖或修改全局环境。默认遵循 [free-data-policy.md](free-data-policy.md)，不把付费终端或机构数据库设为前置条件。

## 稳定入口

优先运行 `python scripts/pia.py --help` 查看稳定子命令。该入口只做参数路由和状态归一，不绕过底层业务门禁。若某个子命令尚未接通，必须返回非零和结构化未完成状态。

## 直接门禁与分析命令

- 证券身份：`instrument_gate.py`
- 美股实时证据：`live_evidence_probe.py`
- 美股免费点时年度财务：`pia.py edgar-fundamentals <代码...> --as-of <ISO 日期> [--user-agent <含真实邮箱的说明>]`；底层为 `sec_edgar_fundamentals.py`，只选取 `filed <= as_of` 的 SEC `companyfacts` 事实，不获取价格
- 研究 Brief：`research_brief_gate.py`
- 财务筛选：`quality_screener.py`
- 通用行情与财务：`yf.py`
- 即期外汇：`yf.py CNY=X --price-only --period 5d --lean --json --cache-dir <task-cache>`；使用带日期的外汇序列，并从最后一个有效观测构造 USD/CNY 快照
- A 股补充数据：`akshare_fetcher.py`
- ETF 历史完整性：`history_integrity_gate.py`
- 管理层承诺：`management_claim_tracker.py`
- Dashboard 结构与数学：`dashboard_gate.py`、`dashboard_math_gate.py`
- Dashboard 目录：`dashboard_catalog.py`
- 观察边界：`watchlist_gate.py`
- 组合情景：`portfolio_scenario_analyzer.py`
- 分配实验：`rebalance_weights.py`
- Alpha 推广门禁：`pia.py alpha-validate <alpha-package> --policy-file <promotion-policy>`
- 主动机会扫描：`pia.py alpha-scan <alpha-package> --validation-report <validation-report> --policy-file <scan-policy>`
- 风险平价与稳健主动候选：`pia.py portfolio-construct <scan-report> --policy-file <construction-policy>`
- 非执行再平衡研究提案：`pia.py rebalance-proposal <construction-report> --policy-file <proposal-policy>`
- 券商 CSV 导入：`broker_sync.py`，仅在用户明确授权时运行
- Daily Sync：`yf.py --daily-sync --cache-dir <task-cache> [--daily-sync-workers 1..4]` 后接 `daily_sync.py`；完成事件红队时传入 `--thesis-evidence-file`
- 研究日记与结果同步：`advice_journal.py`、`sync_outcomes.py`、`decision_outcome_report.py`
- Dashboard 归档：`save_dashboard.py`，仅在用户另行批准持久化时运行

需要精确参数时以对应 `--help` 为准；文档中的示例不得覆盖脚本当前契约。

`yf.py` 的所有联网模式都必须先绑定可写 SQLite 缓存。显式 `--cache-dir` 优先，其次使用 `PIA_YFINANCE_CACHE_DIR`，否则落到当前工作目录的 `tmp/pia-yfinance-cache`。缓存目录即使已经存在也要通过实际写入探针；权限、只读文件系统或 SQLite 打开失败属于永久本地错误，同参数不得退避重试。

`scenario --output` 不得解析为组合或假设输入文件；`calibrate --output-path` 不得解析为研究日记。所有整文件写出路径（情景结果、校准报告、券商快照、管理层承诺跟踪和研究日记结果更新）均使用唯一的同目录临时文件、`fsync` 与原子替换，冲突或写出失败时保留原文件。研究日记的追加和读改写还使用跨进程独占锁；锁等待超过 5 秒时失败关闭，不覆盖其他写入者的结果。
