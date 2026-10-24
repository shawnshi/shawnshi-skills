---
name: hit-weekly-brief
description: 汇总指定周期内数字健康、医疗政策、医疗AI与信息化动态，默认面向中国医疗机构管理层及医疗IT经营决策者，生成带来源周报或速览。适用于周度综合研判，不以纯论文扫描或单条新闻解读触发正式周报；当前信息须联网核验，区分事实、来源主张、分析和不确定性；正式周报验证后默认自动归档，速览及预览不保存。
---

# 数字健康与医疗信息化周报（HIT Weekly Brief）

## 1. 职责边界与模式路由

1. **核心定位**：面向中国医疗机构管理层与医疗 IT 经营决策者，按自然周（周一至周日，或显式授权的自定义周期）汇总研判**医疗政策与医保支付、医院数字化转型、临床 AI 落地与国内外厂商战略动态**。
   - 项目级招投标与竞对事件扫描交 `hit-industry-radar`；学术论文与预印本侦察交 `hit-lectures-scout`；每日跨技术与医疗简报交 `personal-intelligence-hub`。
2. **输出模式**：
   - `formal_weekly`（默认）：生成完整 8 章节管理层周报，通过 `validate_weekly_brief.py` 校验后自动调用 `shared/scripts/report_archive.py` 归档至 `C:\Users\shich\MEMORY\raw\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`。
   - `quick_digest`（用户明确要求速览/预览/不保存）：输出核心判断、关键事件简表与来源，不写盘。
   - `single_event_readout`（单条政策/事件解读）：直接交付事实、传导机制与建议动作，不写盘。
   - 正式周报默认自动归档。若用户明确要求预览或不保存，则只在答复交付，不落盘报告。

---

## 2. Pi `codemode` 四面并发取证与历史去重

详见 `references/research-workflow.md`。在 `formal_weekly` 模式下：

1. **前置历史去重检查（只读）**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\hit-weekly-brief\scripts\inspect_report_headers.py C:\Users\shich\MEMORY\raw\DigitalHealthWeeklyBrief --limit 4
   ```
   核对近期已出刊周期，避免重复收录往期已报道的旧事件。
2. **四大维度并发检索（`codemode` + `Promise.allSettled`）**：
   - **政策与支付面（`assets/Task_policy.md`）**：国家卫健委、国家医保局（DRG/DIP、医疗服务价格立项指南、医保基金监管）、国家数据局及省级医改政策；
   - **行业与厂商战略面（`assets/Task_strategy.md`）**：公立医院高质量发展、三甲评审（互联互通五乙、电子病历六级）、国内外头部 HIT 与医疗 AI 企业重大合作与财报信号（可结合 `mcp__Reson_KnowWeave_mcp__search_timeline` 核对基线）；
   - **技术架构与临床 AI 面（`assets/Task_tech.md`）**：院内多智能体（Agentic Workflow）、核心系统信创替代与微服务解耦、临床决策支持（CDSS）真实世界落地验证；
   - **跨界机制参考面（`assets/Task_serendipity.md`）**：金融风控、工业高可靠系统、基础大模型工程演进对医疗 IT 的可迁移启示。
   - **工具组合**：在 `codemode` 中并发调用 `google_search`、`web_search(queries=[...])` 与 `fetch_content(urls=[...])` 获取一手原始页面与准确发布/事件日期。

---

## 3. 正式周报结构契约（内联速查，详见 `references/formal-report.md` 与 `references/template.md`）

### 3.1 标题与头部元数据（H1 与第一个 `##` 之间，精确单次出现）
- **标题格式（`canonical_title`）**：
  - 同年同月：`# 数字健康周报｜YYYY年M月D日—D日`
  - 同年跨月：`# 数字健康周报｜YYYY年M月D日—M月D日`
  - 跨年：`# 数字健康周报｜YYYY年M月D日—YYYY年M月D日`
- **头部元数据字段**：
  ```markdown
  报告周期：YYYY-MM-DD 至 YYYY-MM-DD（默认周一至周日，7 个日历日）
  出刊日期：YYYY-MM-DD（必须等于 period_end）
  生成时点：YYYY-MM-DDTHH:MM:SS+08:00
  报告时区：Asia/Shanghai
  地区：中国（兼顾全球对标）
  受众：医疗机构管理层与医疗信息化决策者
  ```

### 3.2 八大必选二级章节与固定表头
1. `## 本周结论`：分三条明确列出 `- **已核实事实**：...`、`- **来源主张**：...`、`- **分析判断**：...`。
2. `## 关键事件与来源`（无事件时写独行 `本周期未发现符合纳入标准的事件`；有事件时使用固定 6 列表头）：
   `| 事件日期 | 主体与已核实动作 | 事实或来源主张 | 分析判断 | 证据强度 | 直接来源 |`
   - `事件日期`：必须在 `[period_start, period_end]` 窗口内，支持 `YYYY-MM-DD` 或 `M月D日`；
   - `证据强度`：`高 / 中 / 低`；
   - `直接来源`：**必须包含完整 HTTP(S) 原始链接或 Markdown 链接 `[S1](https://...)`**（不能只写纯文本 `S1`）。
3. `## 政策和市场影响`：阐明政策/采购变化的传导机制、适用地区与生效节点。
4. `## 技术落地信号与证据限制`：区分真实临床生产落地与实验室/厂商基准宣传。
5. `## 对医疗信息化业务的传导影响`：针对 HIS/EMR 解耦、集成平台、数据治理与 AI 智能体产品线给出具体传导推演。
6. `## 建议动作与验证节点`：按责任角色、触发条件与可核验指标给出行动建议。
7. `## 信息缺口`：如实披露检索边界、受阻渠道与待核事项。
8. `## 来源清单`（固定 7 列表头）：
   `| 编号 | 标题 | 发布机构 | 发布日期 | 事件日期 | 访问日期 | URL |`

---

## 4. 一键校验与事务归档流程

1. **执行结构与日期门禁校验**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\hit-weekly-brief\scripts\validate_weekly_brief.py --file <draft.md> --period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD> --issue-date <YYYY-MM-DD> --cutoff <ISO-8601> --report-timezone Asia/Shanghai --json
   ```
2. **原子归档发布（`status=VALID` 时执行）**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py validate --source <draft.md> --target C:\Users\shich\MEMORY\raw\DigitalHealthWeeklyBrief\DHWB-<YYYYMMDD>.md --skill hit-weekly-brief
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py commit --plan <plan.json> --target C:\Users\shich\MEMORY\raw\DigitalHealthWeeklyBrief\DHWB-<YYYYMMDD>.md
   ```
