# Yahoo Finance Skill Examples

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

## Agent 唤醒与智能投研分析

本技能内置了一个专精于个股诊断的 Agent 配置文件 (`agents/stock_analyzer.yaml`)。
当在支持 Agent 的环境下发起查询时，大模型会执行标准的 **双盲印证工作流**（量化数据 + 定性资讯）。

**典型唤醒 Prompt**：
> "@yahoo-finance 切换到 stock analyzer，请深度分析特斯拉 (Tesla) 的投资价值"
