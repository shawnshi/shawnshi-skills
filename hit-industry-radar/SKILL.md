---
name: hit-industry-radar
description: 检索指定周期的医疗IT政策、厂商及采购项目阶段事件，生成带来源、事件日期和影响判断的行业雷达。适用于竞对监测、项目阶段追踪和事件扫描；管理层综合周刊、论文证据侦察、基线优先日简报分别由对应技能处理，模糊请求先确定交付物。需要当前信息时必须联网核验，不把旧闻改写成新事件；正式行业雷达生成后默认自动归档。
---

# 医疗 IT 行业雷达（HIT Industry Radar）

## 1. 职责边界与模式路由

1. **核心定位**：针对指定周期内的**医疗 IT 政策监管、医院采购与招投标项目阶段、国内外厂商产品与合作事件**开展结构化扫描与竞争影响研判。
   - 综合管理层周报交 `hit-weekly-brief`；学术论文与预印本侦察交 `hit-lectures-scout`；每日跨领域简报交 `personal-intelligence-hub`；单一医院客户拜访包交 `hit-customer-analyst`。
2. **输出模式**：
   - `formal_radar`（默认）：生成完整行业雷达，通过 `validate_industry_radar.py` 校验后自动调用 `shared/scripts/report_archive.py` 归档至 `C:\Users\shich\MEMORY\raw\HealthcareIndustryRadar\DHWB-Radar-YYYYMMDD.md`（仅当 `检索状态` 为 `complete` 或 `partial` 时归档；`blocked` 仅输出诊断不归档）。
   - `quick_scan`（用户明确要求速览/不保存）：输出精简信号表与来源，不写盘。
   - `single_claim_check`（单条传闻/中标核实）：直接输出核验结论、项目阶段与原始证据链，不写盘。
   - 正式行业雷达默认自动归档。若用户明确要求速览或不保存，则只在答复交付，不落盘报告。

---

## 2. Pi `codemode` 并发取证与知识源协同

在 `formal_radar` 模式下，优先使用 Pi **`codemode`** 在单回合内并发完成四大检索面的公开取证，并按需联动内部知识库（詳见 `references/research_contract.md` 与 `assets/intelligence_targets.json`）：

1. **四大检索面并发编排（`codemode` + `Promise.allSettled`）**：
   - **政策与监管面（`assets/Task_china_hit.md`）**：国家卫健委、国家医保局、国家疾控局、药监局及省级集采/电子病历评级/互联互通政策；
   - **招采与项目阶段面**：中国政府采购网、各省市公共资源交易中心医院 HIS/EMR/集成平台/医保 DRG/医疗 AI 招标、中标与合同公告；
   - **国内厂商与基线面（`assets/Task_winning_baseline.md`）**：卫宁健康（WiNEX / WiNGPT）、东软集团、创业慧康、东华医为、嘉和美康、惠每科技、讯飞医疗等产品发布与大单动态（可结合 `mcp__Reson_KnowWeave_mcp__search_timeline` 核对历史演进）；
   - **全球医疗 IT 对标面（`assets/Task_global_hit.md`）**：Epic、Oracle Health、Meditech、InterSystems、FDA/ONC/CMS 最新动态。
   - **工具组合**：在 `codemode` 中组合 `google_search`（实时时间线核验）、`web_search(queries=[...])`（多角度并发检索）与 `fetch_content(urls=[...])`（提取招标公告/政策原文日期与金额）。
2. **硬性事实与反伪造纪律**：
   - **严格区分采购阶段**：必须根据公告原文区分 `意向公开 / 预算立项 / 招标采购 / 中标成交 / 合同签署 / 上线验收`，严禁将预算或招标写成“已中标/已签单”；
   - **严格区分日期**：`事件日期`（实际发生/签署/成文日）与 `发布日期`（网页刊发日）均须落在 `[period_start, period_end]` 窗口内，不得把旧闻重发当作本期新事件。

---

## 3. 正式报告结构契约（内联速查，详见 `references/report_schema.md`）

### 3.1 标题与头部元数据（H1 与第一个 `##` 之间，精确单次出现）
```markdown
# 医疗行业雷达｜YYYY-MM-DD 至 YYYY-MM-DD

报告周期：YYYY-MM-DD 至 YYYY-MM-DD
窗口模式：rolling7 | natural_week | explicit
出刊日期：YYYY-MM-DD（必须等于 period_end）
生成时点：YYYY-MM-DDTHH:MM:SS+08:00（精确运行完成时点）
报告时区：Asia/Shanghai
报告范围：[如：中国医疗 IT；医院核心系统招采与竞对动态]
检索状态：complete | partial | blocked
```

### 3.2 六大必选二级章节与固定表头
1. `## 核心判断`：总结本期已验证信号与竞争格局变化。若 `检索状态：partial`，本节必须显式包含字面声明：`本报告为部分覆盖（partial）：受阻检索面见“检索覆盖与缺口”，不得将未检索到事件解释为市场无事件。`
2. `## 关键事件`（无事件时写独行 `本周期未发现符合纳入标准的事件`；有事件时使用固定 10 列表头）：
   `| 事件日期 | 发布日期 | 主体 | 阶段 | 事件概述 | 事实依据 | 竞争与客户影响 | 置信度 | 验证状态 | 来源 |`
   - `阶段` 枚举：`政策发布 / 监管通报 / 融资并购 / 产品发布 / 采购招标 / 中标成交 / 合同签署 / 试点上线 / 生态合作 / 其它已验证阶段`
   - `置信度` 枚举：`高 / 中 / 低`；`验证状态` 枚举：`一手验证 / 多源印证 / 单源待核`；`来源` 填 `S1`、`S1, S2`。
3. `## 竞争与项目阶段解读`：结合 `references/stc_framework.md` 分析技术、架构与商务传导。
4. `## 建议行动`：按目标对象、触发条件与验证动作列出可执行建议。
5. `## 检索覆盖与缺口`：逐面说明已覆盖渠道、停止原因及对结论的限制。
6. `## 来源`（固定 5 列表头，所有被引用 `S#` 必须在此定义）：
   `| 编号 | 标题 | 机构 | 发布日期 | 链接 |`

---

## 4. 一键校验与事务归档流程

1. **写入草稿并执行结构与日期门禁校验**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\hit-industry-radar\scripts\validate_industry_radar.py --file <draft.md> --period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD> --window-mode <rolling7|natural_week|explicit> --issue-date <YYYY-MM-DD> --cutoff <ISO-8601> --report-timezone Asia/Shanghai --json
   ```
2. **原子归档发布（`status=VALID` 且 `检索状态` 为 `complete` 或 `partial` 时执行）**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py validate --source <draft.md> --target C:\Users\shich\MEMORY\raw\HealthcareIndustryRadar\DHWB-Radar-<YYYYMMDD>.md --skill hit-industry-radar
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py commit --plan <plan.json> --target C:\Users\shich\MEMORY\raw\HealthcareIndustryRadar\DHWB-Radar-<YYYYMMDD>.md
   ```
