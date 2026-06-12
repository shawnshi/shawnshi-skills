---
name: personal-investment-advisor
version: 8.1.0
description: 顶级金融量化引擎。用于股票、ETF、港股、美股、A股行情与基本面查询，以及基于结构化 schema 的决策仪表盘分析。数据抓取必须走 `scripts/yf.py`，持仓上下文必须走 `scripts/portfolio_loader.py`，深度分析必须遵循 `resources/dashboard_schema.json`，落盘前必须通过 `scripts/dashboard_gate.py`。
triggers: ["股票调研", "量化分析", "持仓审计", "查看行情", "分析美股", "分析A股", "查看港股"]
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

# Personal Investment Advisor (顶级金融量化引擎 V8.1 Native)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Fetch (数据抓取) [Mode: PLANNING]
1. 主代理必须使用原生的 `run_command` 工具调用内部脚本获取结构化数据，且必须挂载编码锁：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\yf.py" ... --json`
2. 若仅需行情/基本面/新闻，优先使用：`--price-only` / `--info-only` / `--news-only`。
3. 长时间跨度优先加 `--lean`，避免历史 K 线挤爆上下文。
4. 若希望输出持仓者建议，追加 `--with-portfolio`；系统默认从绝对路径读取持仓文件：`C:\Users\shich\.gemini\MEMORY\raw\stocks\portfolio_positions.json`。

### Phase 2: Analyze (逻辑诊断) [Mode: PLANNING]
1. 非 A 股时，筹码结构（`chip_structure`）不得由大模型伪造幻觉，必须明确标记 `不适用(非A股)`。
2. 若输入包含 `portfolio_context.has_position=true`，主代理必须区分视角回答：不仅要有单票诊断，还必须同时输出针对“空仓者视角”和“持仓者视角”的建议。
3. 必须显式给出相对成本、当前浮盈浮亏状况以及动作触发条件。所有的结论必须有对应的 Evidence items 支撑。

### Phase 3: Gate & Archive (数学校验与落盘) [Mode: EXECUTION]
1. 任何要落盘的深度决策 JSON，必须由大模型自主确保其符合 `dashboard_schema.json` 契约，并通过相关的 Python 校验逻辑（如 `dashboard_gate.py`、`dashboard_math_gate.py`）。
2. **强制命名与落盘规范**：通过校验后，生成的所有 Markdown 诊断报告必须使用原生 `write_to_file` 工具绝对物理落盘至：
   `C:\Users\shich\.gemini\MEMORY\raw\stocks\{股票名称股票代码}_{YYYYMMDD}.md` （例如：`高端制造ETF562910_20260419.md`）。严禁使用默认泛化名称。
3. `save_dashboard.py` 落盘成功后会自动追加建议日志到 `advice_journal.jsonl`，用于后期的战略反思与校准（Reconcile 阶段）。

## 2. <Contracts> (输出与交付契约)
- **Schema 硬性约束**: 深度分析输出必须绝对贴合内部规定的 JSON Schema。
- **持仓必答**: 持仓者建议至少覆盖：相对成本浮盈浮亏、当前应该进行何种动作（加/持/减/观望）、动作触发的确切价位或条件，以及主要的风险来源（趋势破坏/估值过高/仓位过重）。
- **Telemetry 记录**: 任务执行完成后，必须使用原生的 `write_to_file` 工具将本次执行的元数据以 JSON 格式绝对物理落盘至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
  结构示例：`{"skill_name": "personal-investment-advisor", "status": "success", "mode": "dashboard", "market_type": "A股", "gate_passed": true, "has_position": true}`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **幻觉工具调用 (Tool Hallucination)**：严禁使用 `write_file`，必须使用原生 `write_to_file`。严禁在 Windows 环境下使用含 `~` 或缺少斜杠的非法伪路径（如 `~/.gemini/MEMORY/...` 或 `{SKILL_DIR}`）。
- **执行栈崩溃 (Execution Deadlock)**：在调用 Python 数据脚本时，必须附加跨平台数据流保护锁 `$env:PYTHONIOENCODING="utf-8"` 并使用绝对物理路径。
- **无脑重新计算 (Compute Hallucination)**：严禁大模型自行计算 MA/MACD/RSI。优先读取脚本 `summary` 吐出的预计算指标，不要充当计算器。
- **观望门 (Watch Lock)**：若给出的建议是“观望 (Wait & See)”，必须包含一个明确的“向上突破或向下破位”的硬触发条件，否则该建议视为无效废话，必须被系统拦截。
- **止损逻辑倒错 (Stop-Loss Inversion)**：止损位必须严格且在逻辑上合理地低于当前市价。若出现止损位高于现价的荒谬计算，视为严重幻觉。
- **定性伪装定量 (Qualitative Camouflage)**：金融分析属于高风险输出，严禁将“未来可能向好”等定性话术伪装成具有操作性的确定性定量建议。
