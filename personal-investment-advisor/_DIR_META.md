---
title: Yahoo Finance Data Engine
date: 2026-03-08
status: active
author: shawnshi
---

# _DIR_META.md

## Architecture Vision
提供确定性、结构化的全球金融市场数据访问。
作为 Gemini 的"语义金融层"，将自然语言查询（如公司名）转化为精确的代码与数据，支持历史趋势分析（含日内K线）、基本面核查及新闻聚合。内置超时、重试与结构化错误报告。

## Member Index
- `SKILL.md`: [Required] 技能核心指令、触发逻辑、使用示例及 Agent 最佳实践。
- `README.md`: 技能概述与快速上手指引。
- `scripts/`: [Bundled Resources] 存放确定性执行脚本。
  - `yf.py`: 基于 yfinance 的核心数据提取引擎 (v2.0)。包含 MACD/RSI 等机构级指标预计算。
  - `akshare_fetcher.py`: A 股增强数据获取器（量比、换手率、振幅、筹码分布），被 `yf.py` 条件触发调用。
  - `save_dashboard.py`: 研报落盘脚本，将 JSON 格式的决策仪表盘保存为 Markdown。
  - `requirements.txt`: Python 依赖清单。
- `agents/`: [Recommended] 存放 Agent 配置。
  - `gemini.yaml`: UI 适配与提示词配置。
  - `stock_analyzer.yaml`: 投研分析师 Agent，支持 A 股/美股/港股多市场路由。
- `resources/`: 存放结构化模板。
  - `dashboard_schema.json`: 决策仪表盘 JSON Schema。
- `examples/`: 使用示例集。
  - `examples.md`: CLI 与 Agent 唤醒指令示例。

> ⚠️ **Protocol**: 当 API 架构、依赖项（yfinance）或脚本路径变更时，必须同步更新此文件。
