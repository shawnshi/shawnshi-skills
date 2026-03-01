---
name: intelligence-hub
description: 战略情报作战中枢。整合全球多源新闻抓取与二阶深度情报精炼，构建统一的个人"逻辑湖"。
language: py
---

# SKILL.md: Intelligence Hub V4.0 (战略情报作战中枢)

> **Version**: 4.0 (Full Python Stack) | **Last Updated**: 2026-02-21
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的"逻辑湖"。追求高可用采集与对抗性推演。

## 1. 触发逻辑 (Trigger)
- 当用户要求"获取最新情报"、"分析行业趋势"、"扫描技术新闻"或"生成每日简报"时激活。

## 2. 核心工作流 (The Intelligence Cycle)

### 第零阶段：动态校准 (Calibration)
1. **执行**：`python scripts/calibrate_focus.py`。
2. **功能**：分析 `{root}/pai/memory.md` 中的关键词频率，动态调整 `references/strategic_focus.json` 中的战略权重。

### 第一阶段：多源情报侦察 (Reconnaissance)
1. **执行**：`python scripts/fetch_news.py [--proxy URL]`。
2. **工程特性**：支持增量抓取（7 天去重缓存）、指数退避重试、100+ RSS/API 源并发采集。
3. **输出**：`tmp/latest_scan.json`。

### 第二阶段：深度精炼与推演 (Refinement)
1. **执行**：`python scripts/refine.py`。
2. **功能**：基于战略关键词权重评分排序，生成结构化 AI 提示词至 `tmp/refinement_prompt.txt`。
3. **AI 交互**：Agent 读取提示词，执行二阶推演（"So What?" 审计）并完成**全量列表翻译**。
4. **输出**：Agent 将结果写入 `{root}/MEMORY/news/intelligence_current_refined.json`。**[硬约束：必须包含 `top_10`, `translations`, `insights`, `punchline`, `digest`, `market` 六个核心字段]**。
5. **逻辑湖联结**：将情报与 `memory.md` 中的现有资产进行交叉验证。
6. **分级标注**：标注 L1-L4 等级（参见 `references/quality_standard.md`）。

### 第三阶段：对抗性博弈审计 (Optional Adversarial Audit)
1. **触发条件**：当发现 L4 级（Alpha）情报时，**建议**调用 `logic-adversary` 技能。
2. **任务**：模拟红队,从医疗数字化专家、医疗临床专家等角度挑战该 Alpha 结论的鲁棒性，识别潜在的"自动化偏见"。

### 第四阶段：战略简报生成 (Strategic Briefing)
1. **执行**：`python scripts/forge.py`。
2. **功能**：整合 AI 精炼结果与全量翻译，按 `references/briefing_template.md` 模板渲染最终简报。
3. **自愈逻辑**：若 JSON 缺失，自动降级为原始英文列表并显示 `[WAITING]`。

### 第五阶段：物理归档与索引 (Archiving & Indexing)
1. **执行**：`python scripts/update_index.py`。
2. **持久化**：简报保存至 `{root}/MEMORY/news/intelligence_[YYYYMMDD]_briefing.md`。
3. **索引维护**：同时更新 Markdown 总目与 JSON 检索索引。

## 3. 核心约束 (Constraints)
- **路径协议**：统一使用 `scripts/utils.py` 获取路径，严禁硬编码绝对路径。
- **全量中文化**：简报输出必须 100% 中文化。
- **依赖管理**：Python 依赖通过 `requirements.txt` 管理。

## 4. 维护协议 (Maintenance Protocol)
- **Sensor Update**: 新增采集源需同步更新 `fetch_news.py` 与 `references/karpathy_feeds.json`。
- **Focus Sync**: 每次执行前必须先进行 Phase 0 校准。
- **Standard Header**: 所有脚本必须保持标准 Header 契约（@Input, @Output, @Pos）。

## 5. 资源库
- **校准引擎**: `scripts/calibrate_focus.py`（Phase 0，词频权重校准）。
- **采集引擎**: `scripts/fetch_news.py`（Phase 1，多源并发抓取）。
- **精炼引擎**: `scripts/refine.py`（Phase 2，评分排序 + 提示词生成）。
- **锻造引擎**: `scripts/forge.py`（Phase 4，简报模板渲染）。
- **索引引擎**: `scripts/update_index.py`（Phase 5，归档索引维护）。
- **质量标准**: `references/quality_standard.md`（L1-L4 分级与叙事纪律）。
- **情报总目**: `{root}/MEMORY/news/_INDEX.md`。
