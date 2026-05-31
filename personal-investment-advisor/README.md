---
title: Yahoo Finance Skill README
date: 2026-03-02
status: active
author: shawnshi
---

# 雅虎金融数据引擎 (yahoo-finance)

全球金融市场数据的确定性访问工具。支持股价追溯、基本面核查、新闻聚合，输出结构化 JSON 或 Rich 表格。


## 🚀 核心能力 (Core Capabilities)
- **市场数据 (Market Data)**: 历史价格数据（OHLCV）加专业机构级摘要统计（绝对收益率、**最大回撤**、**相比最高点回撤**、波动率等）。支持日内K线间隔（`1m` ~ `1mo`），满足日间与日内交易分析需求。
- **深度基本面分析 (Company Info)**: 深度聚焦核心估值与风控因子（市值、PE、**ROE**、**PB**、**营业利润率**、Beta 等）。支持 `--full-info` 获取全量数据。
- **上下文降噪设计 (Context Optimization)**: 强推 `--lean` 模式，智能截断冗长历史K线，保留首尾关键节点。针对日内高频 K 线加入了动态等距抽样，在为大模型减负（最高压缩 90% Context）的同时维持盘感。
- **新闻聚合 (News Aggregation)**: 关联特定 Ticker 的最新商业新闻。
- **智能解析 (Smart Resolution)**: 模糊输入公司名 (如 "Apple") 自动解析为 `AAPL`，已知 Ticker 直连跳过搜索 API。
- **灵活输出 (Flexible Output)**: 支持人类友好的 Rich 表格输出及大模型友好的结构化 JSON（推荐）。
- **工程健壮性 (Robust Execution)**: 内置超时控制、指数退避重试、结构化错误报告及退出码规范。
- **深度投研诊断 (Deep Dive Analysis)**: 结合专属 `stock_analyzer` Agent 身份，从数据流升维到投资洞察，出具机构级诊断研报。

## 💡 使用场景 (Use Cases)
*   **诊断排雷**: "诊断某公司过去一年的回撤风险与基本面健康度"
*   **因子对比**: "对比多家公司的 ROE 与 PB 等核心交易因子"
*   **新闻追踪**: "获取近期与该公司相关的新闻"
*   **高频复盘**: "分析过去5天的1小时K线数据"
*   **智能研报**: "@stock_analyzer 请对特斯拉出具一份投资价值与诊断研报"

## 🛠️ 最佳实践 (Best Practices for Agents)
1.  **数据分析优先 JSON + Lean**: 长跨度分析务必使用 `--json --lean` 防止 Token 爆炸，同时保留趋势盘感。
2.  **细粒度控制**: 善用 `--price-only`, `--news-only`, `--info-only` 减少无关数据摄入。
3.  **复用现成指标**: JSON 的 `summary` 字段已包含 `ma5/10/20`、乖离率、最大回撤等机构级统计，**切勿自行让大模型通过截断数据重新计算**。
4.  **自然语言日期**: 脚本支持 "yesterday", "3 months ago"，无需预先转换日期格式。
5.  **动静结合补充**: `stock_analyzer` 需采用 "单股深度验证 + 网页搜索补全" 模式，在雅虎数据颗粒度不足时通过 Web Search 补充突发事件与政策影响。

*(欲了解所有 API 参数及具体调用方式，请参阅 [`SKILL.md`](./SKILL.md) 与 `examples/` 文件夹。)*
