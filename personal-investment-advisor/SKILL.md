---
name: personal-investment-advisor
description: 基于当前行情、公司披露、财务数据和用户明确提供的持仓信息，执行股票筛选、公司研究、估值、持仓风险审计和情景压力测试。用于“股票调研”“查看行情”“分析财报”“持仓审计”“批量筛选”“再平衡测算”等请求；仅提供研究与决策支持，不执行交易，也不替代持牌投资、税务或法律意见。
---

# 投资研究与组合分析

## 安全与数据边界

- 明确市场、标的、估值日期、投资期限、币种和用户目标。涉及个人持仓时，只读取用户提供或明确授权的文件。
- 当前价格、财报、监管信息和公司事件必须联网或通过可靠数据源核验，并标注数据时间。优先公司公告、交易所、监管文件和审计财报。
- 不承诺收益，不把模型输出写成确定价格目标，不根据有限信息给出“必须买卖”指令。
- 不执行订单、登录券商、同步账户或改变组合。券商数据访问、日志写入和任何持久化都需要单独明确授权。

## 环境

- 使用 Python 脚本前检查 `scripts/requirements.txt` 和脚本帮助。不要自动安装依赖或修改全局环境。
- 组合文件必须符合 `resources/portfolio_schema.json`；示例位于 `resources/portfolio_positions.example.json`。不要把示例持仓当作用户真实持仓。

## 工作流程

1. 验证证券代码和市场，可运行 `python scripts/watchlist_gate.py`。
2. 按任务需要运行质量筛选，而非把单一 ROE/FCF 阈值当作普遍真理：`python scripts/quality_screener.py --tickers <...>`。
3. 获取并保存带时间戳的原始数据：
   - 通用行情与财务：`python scripts/yf.py <args> --json`
   - A 股补充数据：`python scripts/akshare_fetcher.py <args>`
4. 核对口径、币种、复权、一次性项目、股本变化和数据缺失。关键数字至少回查一个原始披露来源。
5. 建立基础、乐观和悲观情景，列出估值方法、关键假设、敏感性和可能推翻论点的证据。
6. 分析管理层陈述时，可用 `scripts/earnings_truth_serum.py` 辅助对照历史承诺，但不要据语言风格推断欺诈。
7. 仅在复杂公司或组合分析可独立拆分时使用子代理，分配不同方法或反方论证，而不是模拟名人权威。综合时保留冲突和证据差异。
8. 如需组合压力测试或再平衡测算，可运行 `scripts/rebalance_optimizer.py`、`scripts/rebalance_weights.py`。将结果标为模型建议，并说明交易成本、税务和流动性未建模项。
9. 结构化报告可按 `resources/dashboard_schema.json` 生成，并运行 `scripts/dashboard_gate.py` 与 `scripts/dashboard_math_gate.py` 校验数学和字段一致性。

## 输出

- 数据截止时间与来源
- 投资论点及反证
- 财务质量与估值假设
- 风险、催化剂和需要继续核验的问题
- 情景结果与敏感性
- 若有持仓：集中度、相关性、流动性和下行情景

清楚区分事实、计算、假设和观点。若数据不完整或相互冲突，降低结论强度。

## 持久化与升级

- 仅在用户明确要求时运行 `scripts/advice_journal.py`、`scripts/sync_outcomes.py` 或保存论点更新；写入前展示内容和位置。
- 涉及税务、法律、杠杆、衍生品、退休资金或重大资产配置时，提示相关专业风险，并建议用户在行动前咨询合格专业人士。
