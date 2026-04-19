# Personal Investment Advisor Examples (V4.0)

这里汇总了 `yahoo-finance` 技能的常用查询命令与 Agent 唤醒指令，帮助您快速上手各种复杂的场景。

## CLI 核心脚本查询示例 (`yf.py`)

### 1. 单股深度查询 (JSON 降噪模式 - 强推)
最常用于给大模型供给数据的标准指令，带 `lean` 防止上下文爆炸。
```bash
uv run {SKILL_DIR}/scripts/yf.py AAPL --json --lean --period 1y
```

### 2. 多股对比 (仅基本面)
快速拉取多家竞争对手的估值水平。
```bash
uv run {SKILL_DIR}/scripts/yf.py AAPL MSFT GOOG --json --info-only
```

### 3. 自然语言日期范围
无需自行换算，直接传入语义日期。
```bash
uv run {SKILL_DIR}/scripts/yf.py "Tesla" --json --start "3 months ago" --end "yesterday"
```

### 4. 日内 K 线 (1 小时间隔)
高频动态趋势跟踪。
```bash
uv run {SKILL_DIR}/scripts/yf.py 0700.HK --json --price-only --period 5d --interval 1h
```

### 5. 仅获取新闻
查探近期舆情动向。
```bash
uv run {SKILL_DIR}/scripts/yf.py MSFT --json --news-only
```

### 6. A 股深度查询 (含筹码增强)
A 股代码会自动触发 efinance/akshare 数据补强（量比、换手率、振幅、筹码分布）。
```bash
uv run {SKILL_DIR}/scripts/yf.py 600519.SS --json --lean --period 1y --full-info
```

### 7. 北交所标的查询
北交所代码使用 `.BJ` 后缀。
```bash
uv run {SKILL_DIR}/scripts/yf.py 430047.BJ --json --lean --period 6mo
```

### 8. 完整基本面输出 (--full-info)
获取 yfinance 返回的全量 info 字段，用于特殊研究需求。
```bash
uv run {SKILL_DIR}/scripts/yf.py AAPL --json --info-only --full-info
```

## Agent 唤醒与智能投研分析

本技能内置了一个专精于个股诊断的 Agent 配置文件 (`agents/stock_analyzer.yaml`)。
当在支持 Agent 的环境下发起查询时，大模型会执行标准的 **双盲印证工作流**（量化数据 + 定性资讯），并根据标的所属市场自动路由分析框架。

**典型唤醒 Prompt**：

### A 股
> "@yahoo-finance 切换到 stock analyzer，请深度分析中际旭创 (300308.SZ) 的投资价值"

### 美股
> "@yahoo-finance 切换到 stock analyzer，请深度分析特斯拉 (Tesla) 的投资价值"

### 港股
> "@yahoo-finance 切换到 stock analyzer，请深度分析腾讯 (0700.HK) 的投资价值"

### 完整落盘流程
1. `stock_analyzer` 必须先生成符合 `dashboard_schema.json` 的纯 JSON。
2. JSON 必须先通过 `scripts/dashboard_gate.py`。
3. 通过后再由 `save_dashboard.py` 落盘到 `~/.gemini/MEMORY/raw/stocks/`，也可通过环境变量 `PIA_DASHBOARD_DIR` 覆盖路径。

### 持仓感知分析
1. 在 `~/.gemini/MEMORY/raw/stocks/portfolio_positions.json` 维护持仓，格式可参考 `resources/portfolio_positions.example.json`。
2. 取数时追加：
   `uv run scripts/yf.py 300308.SZ --json --lean --with-portfolio`
3. 若需要覆盖默认持仓文件路径：
   `uv run scripts/yf.py 300308.SZ --json --lean --with-portfolio --positions-file D:\\Data\\portfolio_positions.json`
4. 当 `portfolio_context.has_position=true` 时，`stock_analyzer` 必须额外输出持仓者动作建议和触发条件。

### Thesis Mode
```bash
uv run {SKILL_DIR}/scripts/yf.py NVDA --json --lean --with-portfolio
```
然后要求 `stock_analyzer` 以 `thesis_mode` 输出，并补齐 `earnings_snapshot`、`catalyst_map`、`evidence_items`。

### 建议日志回写
归档后，`save_dashboard.py` 会自动把建议写入 `advice_journal.jsonl`。

### 回放与校准
```bash
python {SKILL_DIR}/scripts/decision_outcome_report.py
```

### Watchlist 监控
```bash
python {SKILL_DIR}/scripts/watchlist_gate.py path\\to\\dashboard.json
```
