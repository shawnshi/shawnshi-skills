---
name: hit-lectures-scout
description: 检索、筛选和解释医疗AI、数字医疗与临床信息学论文及预印本，按研究类型评估证据质量，并将学术信号转化为可验证的研发、产品或市场假设。用于医疗AI论文扫描、临床文献追踪、前沿研究周报、专题证据综述或数字医疗研究发现；必须标明同行评审状态、来源与局限，不能把预印本或探索性结果写成临床定论；正式侦察报告生成后默认自动归档。
---

# 医疗数字化文献侦察（HIT Lectures Scout）

## 1. 职责边界与模式路由

1. **核心定位**：针对指定周期内的**医疗 AI、临床信息学与数字健康学术文献（同行评审期刊 + 预印本）**开展系统侦察、方法学与证据强度审查，并提炼可验证的研发与产品假设。
   - 深入精读单篇指定论文交 `academic-paper-reader`；综合管理层周报交 `hit-weekly-brief`；政策与招投标事件扫描交 `hit-industry-radar`。
2. **输出模式**：
   - `formal_scout`（默认）：生成完整文献侦察报告，通过 `validate_lectures_scout.py` 校验后自动调用 `shared/scripts/report_archive.py` 归档至 `C:\Users\shich\MEMORY\raw\DigitalHealthLecturesScout\DHLS-YYYYMMDD.md`。
   - `topic_brief`（专题文献速览）：针对特定临床 AI 方向（如大模型临床决策、电子病历生成、医学影像或路径质控）输出结构化证据简报，不自动归档。
   - `single_study_check`（单篇核验）：快速核验单篇论文发表状态、样本量、终点指标与局限，不自动归档。
   - 正式文献侦察报告默认自动归档。若用户明确要求预览或不保存，则只在答复交付，不落盘报告。

---

## 2. 双轨自动化侦察工作流（`deepxiv` 脚本 + Pi `codemode` 并发）

详见 `references/research-workflow.md`。在 `formal_scout` 模式下，通过 `codemode` 并行调度以下三条证据轨道：

1. **轨道一：arXiv 预印本自动化侦察（`assets/deepxiv_preprints_scout.py`）**
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\hit-lectures-scout\assets\deepxiv_preprints_scout.py --window <DAYS> --output <temp_preprints.md>
   ```
   - 当 `deepxiv-sdk` 可用时直接获取候选预印本结构化草稿；若通道受阻则按 `assets/task_preprints_fallback.md` 使用 Pi `web_search` / `google_search` 检索 arXiv / medRxiv / bioRxiv。
2. **轨道二：国际同行评审期刊并发检索（`codemode` + `assets/task_journals_en.md`）**
   - 在 `codemode` 中并发调用 `google_search` 与 `web_search(queries=[...])`，扫描 *Nature Medicine*、*npj Digital Medicine*、*The Lancet Digital Health*、*NEJM AI*、*JAMIA* 在 `[period_start, period_end]` 窗口内发表的临床 AI 与医疗信息化研究，并用 `fetch_content` 提取 DOI、发表日、研究设计与核心指标。
3. **轨道三：中文权威期刊与规范指南检索（`codemode` + `assets/task_journals_cn.md`）**
   - 扫描《中华医学杂志》《中国数字医学》《中国医院管理》及国家卫健委/医疗信息学会发布的医疗 AI 临床应用规范、评测标准与多中心研究。
4. **证据分层铁律**：
   - 严格区分 `已同行评审` 与 `预印本`；预印本及回顾性单中心模型基准测试**严禁**表述为“已证实临床有效性”或“可直接用于临床诊断”；
   - 每项入选研究的研发/产品转化建议必须表述为**可验证假设**（含验证指标与证伪条件）。

---

## 3. 正式报告结构契约（内联速查，详见 `references/formal-report.md` 与 `assets/report_template.md`）

### 3.1 标题与头部元数据（H1 与第一个 `##` 之间，精确单次出现）
```markdown
# 医疗数字化文献侦察报告 - YYYY-MM-DD

报告周期：YYYY-MM-DD 至 YYYY-MM-DD
出刊日期：YYYY-MM-DD（explicit 模式下等于 period_end；generated 模式下等于生成时点所在时区日期）
生成时点：YYYY-MM-DDTHH:MM:SS+08:00
报告时区：Asia/Shanghai
命名依据：explicit | generated
主题范围：[如：医疗大模型临床决策支持、电子病历质控与多中心评测]
```

### 3.2 必选二级章节与固定表头
1. `## 执行摘要`：提炼本期核心学术信号、证据强度分布与主要方法学趋势。
2. `## 本期研究`（无符合标准研究时写独行 `本周期未发现符合纳入标准的研究`；有研究时先输出固定 6 列汇总表，再按 `### R1 ...` 展开详情）：
   - **汇总表头**：`| 研究编号 | 发表日期 | 类型与评审状态 | 研究主题 | 证据强度 | 来源 |`
     - `研究编号`：`R1`、`R2`...（按递增顺序）；
     - `类型与评审状态`：必须同时包含 `已同行评审` 或 `预印本` 标记及具体研究设计（如 `已同行评审 / 多中心随机对照试验`、`预印本 / 回顾性多任务基准研究`）；
     - `来源`：填 `S1`、`S1, S2`。
   - **逐项研究卡片（每个 `R#` 必须对应一个 `### R# [标题]` 小节）**：
     - **事实与方法**：研究设计、数据来源、样本规模、核心结果数字（标注 `[S#]`）；
     - **局限与外推风险**：单中心偏差、基准泄漏、缺乏前瞻性临床结局等限制；
     - **可验证转化假设**：面向 HIS/EMR/CDSS 或临床智能体的工程验证方案与验收指标。
3. `## 转化假设与建议动作`：汇总研发预研、产品评测与客户沟通层面的验证路线。
4. `## 检索覆盖与证据缺口`：说明检索轨道覆盖情况、排除原因与未闭合缺口。
5. `## 来源`（固定 2 列表头，所有被引用 `S#` 必须在此定义，且第 2 列必须包含真实 HTTP(S) 链接或 DOI 链接）：
   `| 来源编号 | 来源信息 |`

---

## 4. 一键校验与事务归档流程

1. **执行结构与日期门禁校验**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\hit-lectures-scout\scripts\validate_lectures_scout.py --file <draft.md> --period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD> --issue-date <YYYY-MM-DD> --cutoff <ISO-8601> --report-timezone Asia/Shanghai --window-mode <explicit|generated> --json
   ```
2. **原子归档发布（`status=VALID` 时执行）**：
   ```powershell
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py validate --source <draft.md> --target C:\Users\shich\MEMORY\raw\DigitalHealthLecturesScout\DHLS-<YYYYMMDD>.md --skill hit-lectures-scout
   python -X utf8 C:\Users\shich\.pi\agent\skills\shared\scripts\report_archive.py commit --plan <plan.json> --target C:\Users\shich\MEMORY\raw\DigitalHealthLecturesScout\DHLS-<YYYYMMDD>.md
   ```
