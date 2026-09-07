# 命令目录

运行前先检查 `scripts/requirements.txt` 与命令 `--help`。不要自动安装依赖或修改全局环境。默认遵循 [free-data-policy.md](free-data-policy.md)，不把付费终端或机构数据库设为前置条件。

## 稳定入口

优先运行 `python scripts/pia.py --help` 查看稳定子命令。该入口只做参数路由和状态归一，不绕过底层业务门禁。若某个子命令尚未接通，必须返回非零和结构化未完成状态。

所有显式文件或目录参数均在调用者工作目录中解析一次，再以绝对路径交给子进程；含空格或中文的路径需按 Shell 规则引用。`calibrate` 的 `PIA_ADVICE_JOURNAL` 环境路径也采用此口径。未提供的路径不触发额外输入发现。

稳定路由的子进程传输要求 Windows Python >=3.12（本轮验证为 3.13），POSIX 需实际支持非阻塞管道。启动业务子进程前用自有管道探测能力；不支持时返回 `child_transport_unavailable`，不启动业务代码，不归类为无数据。无需新增依赖或全局配置。

stdout、stderr 各限 32 MiB（33,554,432 字节，含边界），轮流以最多 64 KiB 读取；空闲等待最多 5 ms。超过任一上限即丢弃部分输出、返回 `child_output_size_limit` 并终止该子进程，不能将有效 JSON 前缀视为成功。完整有界字节读完后才按 UTF-8 解码，保留原有 `errors="replace"` 语义，分块边界不会破坏多字节字符。业务退出码、非法 JSON、报告文件是否新生成仍独立核验；JSON 报告文件也限 32 MiB，使用上限加一字节读取。

原有 300 秒执行期限不变；超时、容量超限或取消时，最多等待 1 秒终止，再最多等待 1 秒强制结束并回收直接子进程，无法回收属于错误。路由不拥有任意后代进程树；直接子进程退出后只排空当前可读字节，不等待后代持有的管道 EOF。不新增读取线程或临时传输文件。已由明确命令创建的报告可能在失败后保留，失败不授权自动归档、删除或重跑。

## 主动研究的离线交接

`pia.py` 的 stdout 是状态信封，下游输入需要信封中的原始 `result`，不能直接把整个 stdout 当作验证、扫描或构造报告。主动研究四个子命令没有 `--output`；`scenario --output` 是另一个命令的原始结果写出选项，不能用于这条链路。

以下 Python 示例在调用者工作目录中运行四阶段，输入文件名见代码。仅当用户已逐项授权读取这五个输入和创建 `validation.json`、`scan.json`、`construction.json`、`proposal.json` 时运行；示例不增加自动保存权限。可将代码用于已授权的任务脚本，以 `python handoff.py <pia.py 的绝对路径>` 运行。输出采用独占创建，已有文件不覆盖；任何失败都停止下游，保留已完成的独立阶段。写出中断可能留下不完整文件，必须检查后另行授权清理或更换输出路径，不得直接重跑覆盖。

```python
import json
import subprocess
import sys
from pathlib import Path

PIA = Path(sys.argv[1]).resolve(strict=True)


def stage(arguments, output):
    completed = subprocess.run(
        [sys.executable, "-B", str(PIA), *arguments],
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=300,
    )
    envelope = json.loads(completed.stdout)
    if (
        completed.returncode != 0
        or envelope.get("status") != "complete"
        or envelope.get("exit_code") != 0
        or envelope.get("route", {}).get("child_exit_code") != 0
        or not isinstance(envelope.get("result"), dict)
    ):
        raise RuntimeError(f"Stage stopped: {arguments[0]}: {envelope}")
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(envelope["result"], stream, ensure_ascii=False, indent=2)


stage(["alpha-validate", "package.json", "--policy-file", "promotion.json"],
      "validation.json")
stage(["alpha-scan", "package.json", "--validation-report", "validation.json",
       "--policy-file", "scan-policy.json"], "scan.json")
stage(["portfolio-construct", "scan.json", "--policy-file", "construction-policy.json"],
      "construction.json")
stage(["rebalance-proposal", "construction.json", "--policy-file", "proposal-policy.json"],
      "proposal.json")
```

每个入口对每份包、策略或上游报告只读取一次，先对实际解析对象计算规范 JSON SHA-256，再将同一对象交给计算；禁止重新加载路径取哈希或对清洗后的对象补算输入哈希。规范化保持 Unicode、按键排序、使用紧凑分隔符，因此缩进或键顺序不改变摘要。扫描核对验证报告绑定的包摘要，并记录验证报告及扫描策略摘要；构造和提案继续记录其上游报告与策略摘要。包内来源定位和证据哈希仍须由调用者核验；摘要只能绑定内容，不能证明来源真实或给予交易权限。路径在读取前已被他人替换仍可能改变输入，跨文件快照也不是事务；输入需由调用者保持不变，业务哈希门禁保持失败关闭。

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
