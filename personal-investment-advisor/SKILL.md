---
name: personal-investment-advisor
version: 11.0.0
tier: action-allowed
description: '顶级金融量化与价值挖掘引擎 (Berkshire Edition)。内置去劣漏斗、四大师并发辛迪加、财报测谎仪及对抗性风控门禁。'
triggers: ["股票调研", "量化分析", "持仓审计", "查看行情", "分析美股", "分析A股", "查看港股", "批量筛选", "财报测谎"]
---

<strategy-gene>
Keywords: 三级火箭漏斗, 伯克希尔辛迪加, 财报测谎, 逻辑记忆锚, 对抗性审计
Summary: 基于伯克希尔价值框架与量化沙盒的资管中枢，实现从【全景去劣】到【多维会诊】再到【风控硬锁】的闭环。
Strategy:
1. 1. 批量去劣 (Quality Screener)：使用漏斗脚本前置拦截不达标资产，禁止对劣质资产进行深研。
2. 2. 伯克希尔辛迪加 (Berkshire Syndicate)：深度调研必须拉起“巴、芒、段、李”四个子代理极端视角并发，主代理仅作 PM 冲突裁决。
3. 3. 财报测谎：针对财报解读，必须跨期追踪管理层承诺兑现率与语气诚实度。
4. 4. 持久化锚点：分析前必须读取或初始化 thesis.md。
5. 5. 组合级硬门：落盘前强制运行 sandbox_dashboard.py 进行数学压测与排雷。
AVOID: 严禁不经过滤直接深研垃圾股；禁止在合并多智能体研报时抹平看空矛盾；禁止绕过风控直接提供加仓建议。
</strategy-gene>

# Personal Investment Advisor (顶级金融多智能体量化引擎 V11.0 Berkshire Edition)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (执行 quality_screener.py 进行大范围过滤扫描)
2. `view_file` (读取存活标的过往的 thesis.md 与 portfolio_positions.json)
3. `run_command` (执行 yf.py 获取结构化行据)
4. `invoke_subagent` (拉起巴/芒/段/李 4个子分析师并发收集极端情报)
5. `write_to_file` (基于 schema 写入 dashboard_draft.json，保留致命攻击点)
6. `run_command` (执行 save_dashboard.py 进行组合风控、数学校验与落盘)
7. `run_command` (可选：执行 rebalance_optimizer.py 或 rebalance_weights.py 进行组合层审查)

**[BRANCH_EARNINGS]** 当触发词包含“财报测谎”、“深度审计财报”时，必须在常规步骤 4 和 5 之间插入以下拦截器：
4.5. `run_command` (执行 earnings_truth_serum.py 进行 MD&A 承诺对撞与语气审查)
（注：主代理需将脚本输出的 `management_truth_serum` 对象严格组装进标准 dashboard JSON 的顶层节点，再执行后续的 `write_to_file` 和 `save_dashboard.py` 步骤。）

## 1. 核心流程与多智能体架构 (The Three-Stage Funnel)

### Phase 0: 第一级火箭 - 全景去劣漏斗 (Quality Screener)
当用户给出一批股票、一个行业或试图挖掘新机会时，**严禁直接进行深度分析**。必须先启动漏斗脚本，过滤掉不合格的资产。
- **执行命令**: 
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\quality_screener.py" --tickers AAPL MSFT ...
   ```
- 脚本将基于 7 项硬指标（ROE、FCF、利息覆盖、毛利等）及 3 项豁免规则，自动打印 Markdown 筛选报告。
- **主代理任务**: 仅将状态为 `✅ Pass` 或 `⚠️ Pass (Exempt)` 的公司送入下一级深研阶段。

### Phase 1: 原质抓取 (Fetch)
对于存活标的或已有持仓，调用数据获取脚本（务必挂载编码锁）：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\yf.py" ... --json --with-portfolio
   ```
*追加 `--with-portfolio` 将自动读取全局持仓上下文并连同历史演化锚定日志 (`thesis_context`) 一并封装。*

### Phase 2: 第二级火箭 - 伯克希尔辛迪加 (The Berkshire Syndicate)
对于深度调研，必须使用 `invoke_subagent` 并发拉起 **四大师** 子代理阵列进行极致交叉拷问：
1. **Duan Analyst (段永平视角)**：专注商业模式本质、产品护城河与管理层“本分”。
2. **Buffett Analyst (巴菲特视角)**：专注财务严谨性、估值安全边际与自由现金流。
3. **Munger Analyst (芒格反向视角)**：扮演极度悲观的“黑子”，负责推演该公司的“死法”与最大的潜在雷区。
4. **Li Lu Analyst (李录视角)**：将标的置于 20 年长周期的“文明级趋势”下审视天花板。
主代理 (PM) 将负责回收 4 份报告，并在合并时**绝对不能掩盖冲突**，必须在 JSON 草稿的 `blind_spot_warning` 中保留芒格的致命攻击点。

*(特例) 财报测谎仪模式 (Management Truth Serum)*
如果用户指令是“解读最新财报”，必须增加针对 MD&A（管理层讨论与分析）的查证：追踪上一期财报承诺在本期的兑现率，识别语气中的“闪烁其词”并明确标注。

### Phase 3: 第三级火箭 - 对抗性风控与落盘 (Adversarial Gate & Archive)
由于 Markdown 渲染与风控由 Python 接管，**主代理禁止手工编写研报 MD**。
1. 将诊断结论根据 Schema 物理落盘至沙盒：`C:\Users\shich\.gemini\MEMORY\scratch\dashboard_draft_{股票代码}.json`。
2. **网关拦截**：运行组合级风控拦截器（务必挂载编码锁）：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\save_dashboard.py" --stock "<代码>" --file "<沙盒路径>"
   ```
3. 若风控拦截器报错（Exit 1），主代理必须修改沙盒 JSON 并重试。

### Phase 4: 全局量化再平衡与压力测试 (Portfolio Rebalancing & Stress Test)
1. **宏观压测与持仓排雷**: 当用户要求“持仓审查”或“进行组合复盘”时，必须运行压测脚本输出 Rank & Yank 及黑天鹅回撤报告：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\rebalance_optimizer.py"
   ```
2. **动态平价重分配**: 当用户明确要求“重新计算目标权重”或“整合新的配置比例”时，执行量化沙盒重分配：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-investment-advisor\scripts\rebalance_weights.py"
   ```
   该脚本将基于 80% A股 / 20% 美股的物理隔离约束，执行波动率倒数平价与相关性惩罚，并物理覆盖持仓目标权重。

## 2. <Contracts> (输出与交付契约)
- **逻辑锚增量契约**: 如果是持仓股票，输出的诊断必须明确说明是对历史 `thesis.md` 逻辑的“强化”、“弱化”还是“证伪”。
- **组合级风控底线**: 若计算出加仓会导致单只股票仓位超限，必须拒绝加仓建议。
- **Telemetry 记录**: 任务执行完成后，保存遥测至 `skill_audit/telemetry/`，附加字段示例：`"subagents_used": true`, `"thesis_updated": true`。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **记忆断层 (Memory Amnesia)**：明明是持仓股却不去读 `thesis.md` 凭空瞎编逻辑，视为严重幻觉。
- **盲目合并 (Uncritical Aggregation)**：主代理在汇聚多智能体报告时，对“基本面极度低估 vs 技术面全面破位”的冲突不作裁决直接缝合，视为失效。
- **手工造车 (Manual Markdown)**：大模型自己使用 write_to_file 书写带格式的 Markdown，跳过网关，将被封禁。
- **定性伪装定量 (Qualitative Camouflage)**：用“未来向好”等虚词替代“向上突破某价格”的定量操作阈值。
- **风控击穿 (Guardrail Bypass)**：止损位高于现价，或触发了组合回撤警告仍建议重仓，均属于致命逻辑倒错。
