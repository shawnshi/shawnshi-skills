---
name: intelligence-hub
description: 战略情报作战中枢。整合全球多源新闻抓取与二阶深度情报精炼，构建统一的个人“逻辑湖”。
language: py
---

# SKILL.md: Intelligence Hub V3.1 (战略情报作战中枢)

> **Version**: 3.1 (Strategic OSINT Optimized) | **Last Updated**: 2026-02-19
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的“逻辑湖”。

## 1. 触发逻辑 (Trigger)
- 当用户要求“获取最新情报”、“分析行业趋势”、“扫描技术新闻”或“生成每日简报”时激活。

## 2. 核心工作流 (The Intelligence Cycle)

### 第零阶段：扫描参数校准 (Calibration)
1. **任务**：同步 `memory.md` 中的 `Project Context` 与 `references/strategic_focus.json`。
2. **要求**：根据当前战役（如 MSL 落地、ACE 研发）动态调整关键词权重。

### 第一阶段：多源情报侦察 (Reconnaissance)
1. **执行**：`python scripts/fetch_news.py --source all`。
2. **高增益滤波**：基于 IQS 准则（`references/quality_standard.md`）初筛 L2 级以上信息。

### 第二阶段：深度精炼与推演 (Refinement)
1. **二阶推演**：Agent 必须针对精选信息进行“So What?”审计。
2. **逻辑湖联结**：将情报与 `memory.md` 中的现有资产进行交叉验证。
3. **分级标注**：所有情报必须标注 L1-L4 等级。

### 第三阶段：战略简报生成 (Strategic Briefing)
1. **执行**：调用 `scripts/digest.ts`，基于 `references/briefing_template.md` 渲染。
2. **叙事纪律**：遵循“结论先行”标题，严禁使用平庸黑话。

### 第四阶段：物理归档与反馈 (Archiving & Feedback)
1. **持久化**：强制保存至 `C:\Users\shich\.gemini\MEMORY\news\intelligence_[YYYYMMDD].md`。
2. **记忆同步**：将 L4 级情报（Alpha）同步至 `memory.md` 的 `Strategic Axioms` 模块。

## 3. 核心约束 (Constraints)
- **拒绝信息垃圾**：宁缺毋滥，单次简报条目不得超过 12 条。
- **关联度考核**：未通过“So What?”审计的情报不得进入简报。
- **分类硬约束**：必须包含 [AI/Agentic]、[Medical IT/MSL]、[Strategy/Logic] 三大核心板块。

## 4. 维护协议 (Maintenance Protocol)
- **Sensor Update**: 新增采集源需同步更新 `fetch_news.py` 并检查其 Standard Header。
- **Quality Update**: 调整质量标准需同步修改 `references/quality_standard.md`。
- **Sync Trigger**: 每次生成简报后，自动触发对 `strategic_focus.json` 的反馈优化。

## 5. 资源库
- **质量标准**: `references/quality_standard.md` (NEW).
- **采集引擎**: `scripts/fetch_news.py`.
- **推演引擎**: `scripts/digest.ts`.
- **战略重心**: `references/strategic_focus.json`.
