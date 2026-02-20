---
name: intelligence-hub
description: 战略情报作战中枢。整合全球多源新闻抓取与二阶深度情报精炼，构建统一的个人“逻辑湖”。
language: py
---

# SKILL.md: Intelligence Hub V3.2 (战略情报作战中枢)

> **Version**: 3.2 (Strategic OSINT Optimized) | **Last Updated**: 2026-02-19
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的“逻辑湖”。追求高可用采集与对抗性推演。

## 1. 触发逻辑 (Trigger)
- 当用户要求“获取最新情报”、“分析行业趋势”、“扫描技术新闻”或“生成每日简报”时激活。

## 2. 核心工作流 (The Intelligence Cycle)

### 第零阶段：动态校准 (Calibration)
1. **执行**：`python scripts/calibrate_focus.py`。
2. **要求**：自动分析 `C:\Users\shich\.gemini\pai\memory.md`，将当前项目重心（如 MSL, ACE）实时同步至 `references/strategic_focus.json`。

### 第一阶段：多源情报侦察 (Reconnaissance)
1. **执行**：`python scripts/fetch_news.py --source all`。
2. **工程特性**：支持增量抓取（自动过滤 7 天内已读链接）与代理配置，确保 100+ 来源的高可用性。

### 第二阶段：深度精炼与推演 (Refinement)
1. **二阶推演**：针对精选信息进行“So What?”审计。**[硬约束：必须使用简体中文]**。
2. **逻辑湖联结**：将情报与 `memory.md` 中的现有资产进行交叉验证。
3. **分级标注**：标注 L1-L4 等级。

### 第三阶段：对抗性博弈审计 (Optional Adversarial Audit)
1. **触发条件**：当发现 L4 级（Alpha）情报时，**建议**调用 `logic-adversary` 技能。
2. **任务**：模拟红队挑战该 Alpha 结论的鲁棒性，识别潜在的“自动化偏见”。

### 第四阶段：战略简报生成 (Strategic Briefing)
1. **注入准备**：AI 将对话中的高维洞察（insights, punchline, digest, market）写入临时交换文件 `MEMORY/news/intelligence_current_refined.json`。
2. **执行锻造**：调用 `python scripts/forge.py`。
3. **自愈逻辑**：`forge.py` 自动检测并注入 AI 成果，若检测到 `[WAITING]` 占位符将拒绝标记为 "Polished"。

### 第五阶段：物理归档与索引 (Archiving & Indexing)
1. **持久化**：文件强制保存至根目录 `MEMORY/news/intelligence_[YYYYMMDD]_briefing.md`。
2. **清理**：归档完成后自动清理临时交换文件。

## 3. 核心约束 (Constraints)
- **拒绝信息垃圾**：单次简报条目不得超过 12 条。
- **环境一致性**：Node.js 脚本必须通过 `dotenv` 加载根目录 `.env`。
- **路径协议**：统一使用 `pathlib` 处理 win32 路径，严禁硬编码转义字符。

## 4. 维护协议 (Maintenance Protocol)
- **Sensor Update**: 新增采集源需同步更新 `fetch_news.py` 与 `karpathy_feeds.json`。
- **Focus Sync**: 每次执行前必须先进行 Phase 0 校准。
- **Standard Header**: 所有脚本必须保持标准 Header 契约。

## 5. 资源库
- **校准引擎**: `scripts/calibrate_focus.py` (NEW)。
- **采集引擎**: `scripts/fetch_news.py` (Improved)。
- **质量标准**: `references/quality_standard.md`。
- **情报总目**: `MEMORY/news/_INDEX.md`.
