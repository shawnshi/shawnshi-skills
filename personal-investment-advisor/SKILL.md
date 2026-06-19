---
name: personal-investment-advisor
version: 9.0.0
tier: action-allowed
description: '顶级金融量化引擎。支持多市场股票/ETF行情查询及决策仪表盘分析。强制使用原生抓取脚本、沙盒渲染与落盘网关。禁止直接写入 Markdown，禁止伪造定量指标。'
triggers: ["股票调研", "量化分析", "持仓审计", "查看行情", "分析美股", "分析A股", "查看港股"]
---

<strategy-gene>
Keywords: 股票调研, 量化分析, 持仓审计, 决策仪表盘
Summary: 采用 Yahoo + Akshare 驱动的量化引擎，将行情与持仓上下文转化为具备数学硬锁的决策资产。
Strategy:
1. 1. 数据分离：yf.py 仅抓取原始事实，禁止在 LLM 侧重新计算 MA/RSI 等预计算指标。
2. 2. 角色分流：结论必须区分“空仓视角”与“持仓视角”，给出显式的成本、浮盈及动作触发条件。
3. 3. 数学硬门：落盘前必须通过 math_gate 校验，确保止损位、支持位无逻辑冲突。
AVOID: 严禁将定性话术伪装成确定性建议；禁止在非 A 股上编造筹码数据；禁止漏掉止损/止盈硬价格点。
</strategy-gene>

# Personal Investment Advisor (顶级金融量化引擎 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. 
2. un_command (执行 yf.py 获取结构化行据)
3. write_to_file (基于 schema 将诊断结论写入沙盒 JSON)
4. 
5. un_command (执行 save_dashboard.py 进行数学校验与渲染落盘)
6. write_to_file (写入遥测数据)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Fetch (数据抓取)
1. 必须使用原生的 
un_command 工具调用内部脚本获取结构化数据，且必须挂载编码锁：
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\yf.py" ... --json
2. 若仅需行情/基本面/新闻，优先使用：--price-only / --info-only / --news-only。
3. 长时间跨度优先加 --lean，避免历史 K 线挤爆上下文。
4. 若希望输出持仓者建议，追加 --with-portfolio；系统默认从绝对路径读取持仓文件：C:\Users\shich\.gemini\MEMORY\raw\stocks\portfolio_positions.json。

### Phase 2: Analyze (逻辑诊断)
1. 非 A 股时，筹码结构（chip_structure）不得由大模型伪造，必须明确标记 不适用(非A股)。
2. 若输入包含 portfolio_context.has_position=true，主代理必须区分视角回答：必须同时输出针对“空仓者视角”和“持仓者视角”的建议。
3. 必须显式给出相对成本、当前浮盈浮亏状况以及动作触发条件。所有的结论必须有 Evidence items 支撑。

### Phase 3: Gate & Archive (数学校验与落盘)
由于 Markdown 拼接由后端的 Python 脚本全权接管，**主代理绝不可以手工编写 Markdown**。必须遵循以下两步沙盒协议：
1. 大模型根据 
esources/dashboard_schema.json 结构化诊断结论，并将完整的 JSON 使用 write_to_file 物理落盘至沙盒：
   C:\Users\shich\.gemini\MEMORY\scratch\dashboard_draft_{股票代码}.json。**严禁**将 JSON 直接写在技能目录下。
2. 运行落盘与网关拦截器（务必挂载编码锁）：
   `powershell
   utf-8="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\save_dashboard.py" --stock "<股票名称或代码>" --file "C:\Users\shich\.gemini\MEMORY\scratch\dashboard_draft_{股票代码}.json"
   `
3. 脚本会自动进行 dashboard_gate 校验并物理落盘至 MEMORY\raw\stocks\，**不需要主代理再手动执行任何 Markdown 落盘动作**。
4. 若门检失败退出（Exit 1），主代理必须根据控制台报错修改沙盒里的 JSON 并重试。

## 2. <Contracts> (输出与交付契约)
- **Schema 硬性约束**: 深度分析输出必须绝对贴合内部规定的 JSON Schema。
- **持仓必答**: 持仓者建议至少覆盖：相对成本浮盈浮亏、当前应进行动作（加/持/减/观望）、确切价位或条件、以及主要风险来源。
- **Telemetry 记录**: 任务执行完成后，使用 write_to_file 将元数据保存至：
  C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json
  结构示例：{"skill_name": "personal-investment-advisor", "status": "success", "mode": "dashboard", "market_type": "A股", "gate_passed": true, "has_position": true}

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **手工造车 (Manual Markdown)**：大模型严禁自己使用 write_to_file 书写带格式的 Markdown，必须生成纯 JSON 交给 save_dashboard.py 渲染。
- **沙盒污染 (Sandbox Pollution)**：严禁把临时文件写在 config/skills/... 目录。必须写在 MEMORY/scratch/。
- **幻觉工具调用 (Tool Hallucination)**：严禁使用 write_file，必须使用原生 write_to_file。严禁非法伪路径（如 ~/.gemini/...）。
- **执行栈崩溃 (Execution Deadlock)**：调用 Python 脚本时，必须附加保护锁 $env:PYTHONIOENCODING="utf-8" 并使用绝对物理路径。
- **无脑重新计算 (Compute Hallucination)**：严禁自行计算 MA/MACD/RSI。优先读取脚本吐出的预计算指标。
- **观望门 (Watch Lock)**：若建议为“观望”，必须包含明确的“向上突破或向下破位”硬触发条件，否则无效。
- **止损逻辑倒错 (Stop-Loss Inversion)**：止损位必须严格低于当前市价。若出现止损位高于现价的计算，视为严重幻觉。
- **定性伪装定量 (Qualitative Camouflage)**：严禁将“未来可能向好”等定性话术伪装成具有操作性的定量建议。
