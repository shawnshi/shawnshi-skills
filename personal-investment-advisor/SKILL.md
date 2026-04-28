---
name: personal-investment-advisor
description: 顶级金融量化引擎。用于股票、ETF、港股、美股、A股行情与基本面查询，以及基于结构化 schema 的决策仪表盘分析。数据抓取必须走 `scripts/yf.py`，持仓上下文必须走 `scripts/portfolio_loader.py`，深度分析必须遵循 `resources/dashboard_schema.json`，落盘前必须通过 `scripts/dashboard_gate.py`。
---

<strategy-gene>
Keywords: 股票调研, 量化分析, 持仓审计, 决策仪表盘
Summary: 采用 Yahoo + Akshare 驱动的量化引擎，将行情与持仓上下文转化为具备数学硬锁的决策资产。
Strategy:
1. 数据分离：yf.py 仅抓取原始事实，禁止在 LLM 侧重新计算 MA/RSI 等预计算指标。
2. 角色分流：结论必须区分“空仓视角”与“持仓视角”，给出显式的成本、浮盈及动作触发条件。
3. 数学硬门：落盘前必须通过 math_gate 校验，确保止损位、支持位无逻辑冲突。
AVOID: 严禁将定性话术伪装成确定性建议；禁止在非 A 股上编造筹码数据；禁止漏掉止损/止盈硬价格点。
</strategy-gene>

# Personal Investment Advisor (V4.0)

## 0. 核心约束
- **数据层与分析层分离**: `yf.py` 只负责确定性数据抓取；`portfolio_loader.py` 只负责持仓上下文；深度投研 JSON 由 `stock_analyzer` 负责；落盘由 `save_dashboard.py` 负责。
- **Schema 硬门**: 深度分析输出必须满足 [dashboard_schema.json](<C:/Users/shich/.codex/skills/personal-investment-advisor/resources/dashboard_schema.json:1>)，且先通过 [dashboard_gate.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/dashboard_gate.py:1>)。
- **市场分流**:
  - A股: Yahoo + Akshare/Efinance 增强
  - 港股: Yahoo 主导，筹码字段默认不适用
  - 美股: Yahoo 主导，筹码字段默认不适用
- **数据缺口显式化**: 任何增强字段缺失时，必须进入 `data_gaps`，不得伪装成正常值。
- **持仓感知建议**: 若存在持仓文件并匹配到标的，分析必须同时回答“空仓者视角”和“持仓者视角”，并显式给出相对成本、浮盈浮亏与动作触发条件。
- **数学校验门**: 深度分析除了 schema gate，还必须通过 `dashboard_math_gate.py` 的数值一致性校验。
- **组合视角**: 当启用持仓上下文时，必须同时输出 `portfolio_summary / portfolio_risk / portfolio_fit`，不再只看单票。
- **反馈闭环**: 所有已归档建议都应写入 `advice_journal.jsonl`，后续通过 `decision_outcome_report.py` 反推策略校准。
- **研究模式分流**: 支持 `trading_mode` 与 `thesis_mode`。后者必须补 `earnings_snapshot`、`catalyst_map` 与 watchlist 监控线索。

## 1. 运行资产
- **Data CLI**: [yf.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/yf.py:1>)
- **A-share Enhancer**: [akshare_fetcher.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/akshare_fetcher.py:1>)
- **Portfolio Context Loader**: [portfolio_loader.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/portfolio_loader.py:1>)
- **Math Gate**: [dashboard_math_gate.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/dashboard_math_gate.py:1>)
- **Dashboard Contract**: [dashboard_schema.json](<C:/Users/shich/.codex/skills/personal-investment-advisor/resources/dashboard_schema.json:1>)
- **Portfolio Contract**: [portfolio_schema.json](<C:/Users/shich/.codex/skills/personal-investment-advisor/resources/portfolio_schema.json:1>)
- **Dashboard Gate**: [dashboard_gate.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/dashboard_gate.py:1>)
- **Archive Writer**: [save_dashboard.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/save_dashboard.py:1>)
- **Advice Journal**: [advice_journal.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/advice_journal.py:1>)
- **Outcome Review**: [decision_outcome_report.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/decision_outcome_report.py:1>)
- **Watchlist Gate**: [watchlist_gate.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/watchlist_gate.py:1>)
- **Portfolio Example**: [portfolio_positions.example.json](<C:/Users/shich/.codex/skills/personal-investment-advisor/resources/portfolio_positions.example.json:1>)

## 2. 执行协议

### Phase 1: Fetch
1. 使用 `uv run {SKILL_DIR}/scripts/yf.py ... --json` 获取结构化数据。
2. 若仅需行情/基本面/新闻，优先使用：
   - `--price-only`
   - `--info-only`
   - `--news-only`
3. 长时间跨度优先加 `--lean`，避免历史K线挤爆上下文。
4. 若希望输出持仓者建议，追加 `--with-portfolio`；持仓文件默认读取 `~/.gemini/MEMORY/raw/stocks/portfolio_positions.json`，可通过 `PIA_POSITIONS_FILE` 或 `--positions-file` 覆盖。
5. 需要 thesis 级研究时，优先补充 `earnings_snapshot` 与新闻催化，再交由 `stock_analyzer` 走 `thesis_mode`。

### Phase 2: Analyze
1. 深度诊断必须遵循 `stock_analyzer` 路由。
2. 输出必须严格贴合 [dashboard_schema.json](<C:/Users/shich/.codex/skills/personal-investment-advisor/resources/dashboard_schema.json:1>)。
3. 非 A 股时，`chip_structure` 不得伪造，必须明确标记 `不适用(非A股)`。
4. 若输入包含 `portfolio_context.has_position=true`，必须额外输出：
   - `portfolio_context`
   - `position_advice`
   - `dashboard.core_conclusion.position_advice`
5. 持仓者建议至少覆盖：
   - 相对成本是浮盈还是浮亏
   - 当前更像加仓、持有、减仓还是观察
   - 触发动作的价位或条件
   - 风险来自趋势破坏、估值过高还是仓位过重
6. 所有高等级结论必须有 `evidence_items`，每条都含 `fact / connection / deduction / freshness / confidence`。
7. `confidence_level` 不能只凭语气判断，必须由 `confidence_details.score` 支撑。

### Phase 3: Gate
1. 任何要落盘的深度 JSON，必须先通过 [dashboard_gate.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/dashboard_gate.py:1>)。
2. Gate 失败时，不得继续调用 `save_dashboard.py`。
3. 若 `portfolio_context.has_position=true`，缺少 `position_advice` 或缺少 `unrealized_pnl_pct` 时必须熔断。
4. 任何出现算术不一致、止损/止盈逻辑冲突、支持位/压力位反转的 JSON，必须被 math gate 拦截。

### Phase 4: Archive
1. 通过 gate 后，使用 [save_dashboard.py](<C:/Users/shich/.codex/skills/personal-investment-advisor/scripts/save_dashboard.py:1>) 或 `write_file` 落盘。
2. **[强制命名规范]**：生成的所有 Markdown 诊断报告必须严格采用 `股票名称股票代码_日期.md` 的格式命名（例如：`高端制造ETF562910_20260419.md`），严禁使用泛化的默认名称（如 `stock_analyzer_xxx.md`）。
3. 落盘目录允许通过环境变量覆盖，默认仍写入 `~/.gemini/MEMORY/raw/stocks`。
4. `save_dashboard.py` 落盘成功后会自动追加建议日志到 `advice_journal.jsonl`。
5. 定期使用 `decision_outcome_report.py` 生成 `strategy_calibration.md`。

## 3. Best Practices
- 涉及长历史周期时，优先 `--json --lean`。
- 不要让大模型重新计算 MA/MACD/RSI，优先读取 `summary` 里的预计算指标。
- A 股增强层失败时，必须查看 `data_gaps` 和 `data_sources`，而不是默认字段为零。
- 持仓文件属于运行态资产，不要写进 skill 包；建议维护在 `~/.gemini/MEMORY/raw/stocks/portfolio_positions.json`。
- `stock_analyzer` 的结论必须区分“如果你没有仓位”和“如果你当前持有该标的”。
- 组合分析优先级高于单票分析。当组合集中度过高时，单票再好也不应直接加仓。
- `thesis_mode` 不是把字写长，而是把财报、估值、催化和 thesis 破坏条件说清。
- watchlist 监控优先盯 4 条：止损、止盈、支撑/压力突破、催化窗口。
- 金融分析属于高风险输出，不能把定性话术伪装成确定性建议。

## 4. Telemetry
- 如具备 `write_file` 能力，可记录 telemetry。
- 推荐结构：
```json
{"skill_name":"personal-investment-advisor","status":"success","mode":"dashboard","market_type":"A股","gate_passed":true,"has_position":true}
```
