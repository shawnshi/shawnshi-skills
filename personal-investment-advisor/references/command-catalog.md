# 命令目录（Command Catalog）

统一入口：`python -X utf8 scripts/pia.py <subcommand> [options]`。
运行前可通过 `--help` 查看精确参数。默认遵循免费公开数据源策略（[free-data-policy.md](free-data-policy.md)），所有输出包装为统一状态信封（`status_contract.py`）。暴露 `--decision-scope` 的命令默认采用 `advisory`，纯研究场景显式传 `research_only`。

---

## 一、 Daily Sync 与日常运行编排

1. **一键日常同步（`daily-run`）**
   ```powershell
   python -X utf8 scripts/pia.py daily-run --positions-file <positions.json> --task-dir <run_dir> [--analysis-scope all|held_only] [--dashboard-root <dir>] [--risk-bounds-policy <file>] [--thesis-evidence-file <file>] [--holiday-calendar-file <table>] [--skip-watchlist] [--reuse-artifacts] [--force] [--record] [--render-report]
   ```
   - 固定单一评估时点，串行执行：未购观察清单分析（当 `all` 且含零股）$\rightarrow$ `refresh`（隔离 FX 刷新）$\rightarrow$ `quotes`（主源 Yahoo + 标注二级源 fallback）$\rightarrow$ `daily_sync` $\rightarrow$ `weights`（支持主源与二级源无缝权重重算）$\rightarrow$ `watchlist` 边界核验 $\rightarrow$ 可选 `scenario` / `risk-diagnostic` / `actionability-gate` / `readiness` $\rightarrow$ 可选 `--render-report` 自动生成 `out/report.md`。
2. **一手披露证据采集（`collect-evidence`）**
   ```powershell
   python -X utf8 scripts/pia.py collect-evidence --task-dir <run_dir> --symbols <SYM...> --window-start <ISO> --window-end <ISO> [--scope-source <macro|sector|regulatory>=<url>@<published_at>]
   ```
3. **报告渲染与就绪汇总（`report` / `readiness` / `history`）**
   - 确定性报告渲染：`pia.py report --run-dir <run_dir> [--out <report.md>] [--expect-scope research_only|advisory|actionable]`
   - 可执行性就绪裁决：`pia.py readiness --run-dir <run_dir> [--out <rollup.json>]`
   - 跨运行索引与差分：`pia.py history {index,diff} --task-root <root> [--sections weights,boundaries,quotes]`

---

## 二、 个股/ETF 深度投研与数据采集

1. **实时身份与披露探针（`research`）**
   ```powershell
   python -X utf8 scripts/pia.py research --symbol <SYM> [--cik <CIK>] [--allow-foreign-issuer]
   ```
   - 支持美股普通股（`10-K/10-Q/8-K`）及开启 `--allow-foreign-issuer` 后的中概/外资发行人（`20-F/40-F/6-K`）。
2. **SEC EDGAR 点时财务快照（`edgar-fundamentals`）**
   ```powershell
   python -X utf8 scripts/pia.py edgar-fundamentals <SYM...> --as-of <YYYY-MM-DD> [--artifact-dir <dir>]
   ```
3. **P1/P2 结构化财务投影与诊断流**（详见 [p1p2-research-workflow.md](p1p2-research-workflow.md)）
   - `pia.py fact-prepare --input-file <in.json> --evidence-root <root> --task-dir <dir>`
   - `pia.py fundamental-diagnostic --input-file <in.json> --evidence-root <root>`
   - `pia.py expectation-feedback --input-file <in.json> --evidence-root <root>`
   - `pia.py research-workflow --input-file <spec.json> --evidence-root <root> --task-dir <dir>`
4. **多市场行情与 ETF 工具**
   - 通用行情与基本面：`python -X utf8 scripts/yf.py <SYM...> --cache-dir <dir> --json`
   - ETF 历史完整性包：`pia.py etf-packet --evidence-file <ev.json> --task-dir <dir>`
   - Dashboard 校验与保存：`dashboard_gate.py`、`dashboard_math_gate.py`、`save_dashboard.py`

---

## 三、 主动研究四阶段交接链（Active Research / Rank & Yank）

`alpha-validate`、`alpha-scan`、`portfolio-construct`、`rebalance-proposal` 均支持 `--output <file>` 写出原始 `result` 对象。以下标准 Python 交接脚本可在已授权任务目录中串行执行四阶段并在未达标时自动停止：

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

---

## 四、 持仓审计、风险诊断与台账管理

- **部分组合风险与汇率腿诊断**：`pia.py risk-diagnostic --weights-file <weights.json> --history <SYM=file.json>... [--fx-history <PAIR=file.json>]`
- **A 股股本变动（稀释/增厚）评估**：`pia.py dilution --symbol <SYM> --as-of-date <YYYY-MM-DD> [--out <file.json>]`
- **情景压力测试**：`pia.py scenario --portfolio <file> --assumptions <file> [--output <out.json>]`
- **判断复盘与校准**：`pia.py calibrate --journal-path <jsonl> --output-path <out.md>`
- **台账与门禁辅助**：`pia.py build {scenario,inverse-vol,thesis-pack,dataset-manifest}`、`pia.py trigger-ledger {append,list,due,close}`、`pia.py thesis-ledger {init,append,show,list}`、`pia.py calendar {build,closed}`、`pia.py labels {vocab,check}`、`pia.py review-pack`。
