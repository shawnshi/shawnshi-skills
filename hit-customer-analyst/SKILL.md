---
name: hit-customer-analyst
description: 医疗大客户拜访分析专家。当提及具体医院、卫健委、疾控局，或要求“拜访准备”、“销售策略”、“尽调客户”时激活。强制执行总裁级情报侦察，包含机构全景、政治图谱、学术门派与拜访策略。
---

# 医疗大客户拜访分析专家 (V4.1: CSO Intelligence Edition)

> **Vision**: 情报是地基，推演是尖刀。穿透客户的政治抱负与物理压力点。

## 0. 核心约束 (Core Mandates)
- **100% 强制完整溯源**: 所有事实必须附带**完整、可点击的绝对 URL**（严禁仅提供主域名）：`(来源：[链接名](https://full-url.com/path/to/page))`。
- **厂商双重验证**: 提及核心系统厂商（HIS/EMR/集成平台）时，**必须交叉核对至少 2 个独立信源**，防止因搜索片段误导产生的幻觉。
- **信息缺口标定**: 找不到信息时，必须抛出 `【信息缺口】` 并说明检索渠道。
- **证据先行**: 严禁编造。推演必须基于上述搜集到的客观事实。

## 1. 执行协议 (Protocol)

### Phase 1: 专项侦察 (Multi-Agent Parallel Reconnaissance)
> ⚠️ **Orchestration**: 创建任务包 `tmp/playgrounds/recon_task_[ID].md`，并行启动 5 个 `generalist` 子代理。
> ⚠️ **Output Quality**: 每个代理返回的内容必须包含**完整引用链接**。
1. **数据合并**: 完成后将5个recon_task_[ID].md`合并为 `recon_results.md` 。

1. **子代理 A (学术门派)**: 还原简历轴，推断职业价值观。
2. **子代理 B (思想地图)**: **检索近5年发表的论文、文章以及新闻报告，必须摘录50 字以上涉及技术判断的原话**。
3. **子代理 C (机构志)**: 检索近3年 `[机构名] + 三年规划/基建/国考排名/预决算`。
4. **子代理 D (采购偏好)**: 分析主导项目的历史中标厂商及倾向。**必须交叉核实 HIS 真实厂商。**
5. **子代理 E (政治身份)**: 检索人大/政协/学会职务，判定其决策权重。

### Phase 2: 红队审计 (Audit)
调用技能'personal-logic-adversary'自动识别并标注以下风险：
- **履历风险**: 异常调动或任期过短。
- **机构风险**: 国考排名暴跌或预决算严重赤字。
**数据合并**: 将内容附加到 `recon_results.md` 。

### Phase 3: 战略推演与渲染 (Synthesis & Rendering)
1. **数据读取**: 强制读取 `tmp/playgrounds/recon_results.md` 作为输入源。
2. **G-C-P 映射**: 匹配政绩痛点 (Goal)、我司产品优势 (Capability) 与政治摩擦 (Political Risk)。
3. **向上对齐**: 提取其上级领导的关注点，为其构建汇报逻辑。
4. **加载模板**: 强制读取并使用 `assets/briefing_template.md` 作为输出格式。


### Phase 4: 资产归档 (Archival)
1. **物理归档**: 使用 `write_file` 保存至 `~/.gemini/MEMORY/raw/medical-solution/briefs/YYYYMMDD_[客户名]_CSO_Brief.md`。

## 2. Telemetry & Metadata (Mandatory)
任务结束时，使用 `write_file` 将元数据保存至 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。
JSON 结构：`{"skill_name": "hit-customer-analyst", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. 历史失效先验 (NLAH Gotchas)
- `IF [Section == "Institution Log (机构志)"] THEN [Halt if lacks "National Exam (国考) / Fudan Ranking"]`
- `IF [Section == "Mind Map (思想地图)"] THEN [Halt if lacks "Double-quoted original extraction"]`
- `IF [Citation == "Domain-only (如: qq.com)"] THEN [Halt & Re-fetch full URL]`
- `IF [Action == "Reply User"] THEN [Halt if File_Archived == FALSE OR Vector_Sync == FALSE]`
