---
name: personal-investment-advisor
description: 顶级金融量化引擎 (V8.0 Dehydrated)。用于股票、ETF、行情与基本面查询，以及基于结构化 schema 的决策仪表盘分析。
---

# Personal Investment Advisor (V8.0: Frictionless Pipeline)

> **Vision**: 本技能过去高达 134 行，包含了大量的跨脚本调用（获取行情、加载持仓、跑 JSON 门控、跑数学门控、落盘建议等）。现已被底层 `run_investment_advisor.py` 统接管，大模型彻底从繁琐的 JSON schema 对齐与 API 报错中解放。

## Workflow

你只需根据用户的核心诉求，触发相应的后台战车：

### 1. 个股/ETF 深度研报 (Deep Analysis)
当用户询问某只股票（如 AAPL、腾讯）或要求出具研报：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/personal-investment-advisor/scripts/run_investment_advisor.py" --action "analyze" --symbol "AAPL" --mode "trading"
```
- **Mode**: 可选 `trading` (短线波段) 或 `thesis` (长线逻辑)。
- **交付**: 脚本会在后台静默完成抓取、研报 JSON 生成、数学一致性审计与落盘。你只需要在执行完后，读取 `~/.gemini/MEMORY/raw/stocks/` 下最新生成的 Markdown 报告，向用户简要宣读“买入/观望结论”、“止损位”与“持仓/空仓视角”。

### 2. 投资结果回溯与同步 (Portfolio Sync)
当用户要求“同步复盘日志”、“更新投资 outcome”、“跑一下策略校准”：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/personal-investment-advisor/scripts/run_investment_advisor.py" --action "sync"
```
- 脚本会自动更新 `advice_journal.jsonl`，比对当时的推荐价格与现价，生成红黑榜。你只需读取生成的校准结果并向用户汇报。
