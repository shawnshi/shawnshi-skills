---
name: intelligence-hub
description: 战略情报作战中枢。整合全球多源新闻抓取与二阶深度情报精炼，构建统一的个人"逻辑湖"。
language: py
---

# SKILL.md: Intelligence Hub V4.1 (战略情报作战中枢)

> **Version**: 4.1 (Full Python Stack & Gateway Logic) | **Last Updated**: 2026-03-01
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的"逻辑湖"。追求高可用采集与对抗性推演。
> **Mode**: 严守 GEB-Flow 契约，以状态变更化解异步黑盒焦虑。

## 1. 触发逻辑 (Trigger)
- 当用户要求"获取最新情报"、"分析行业趋势"、"扫描技术新闻"或"生成每日简报"时激活。

## 2. 核心工作流 (The Intelligence Cycle)

*注意：长耗时采集与精炼任务必须支持后台容错异步执行，并通过 `task_boundary` 强制同步状态（🟢 扫描收集 / 🟡 综合起草 / 🔴 归档冻结）。*

### 第零阶段：动态校准 (Calibration) [PLANNING Mode]
1. **执行**：`python scripts/calibrate_focus.py`。
2. **功能**：分析 `{root}/pai/memory.md` 中的关键词频率，动态调整 `references/strategic_focus.json` 中的战略权重。

### 第一阶段：多源情报侦察 (Reconnaissance) [EXECUTION Mode]
1. **执行**：`python scripts/fetch_news.py [--proxy URL]`。
2. **工作流状态**：执行前后必须使用 `task_boundary` 更新状态至 **`🟢 扫描收集`**。
3. **工程特性**：支持增量抓取（7 天去重缓存）、指数退避重试、100+ RSS/API 源后台并发采集。
4. **输出**：`tmp/latest_scan.json`。

### 第二阶段：深度精炼与推演 (Refinement) [EXECUTION Mode]
1. **执行**：`python scripts/refine.py`。
2. **功能**：基于战略关键词权重评分排序，生成结构化 AI 提示词至 `tmp/refinement_prompt.txt`。提示词必须解耦，禁止在代码中硬编码长文本。
3. **AI 交互**：Agent 读取解耦后的独立提示词，执行二阶推演（"So What?" 审计）并完成**全量列表翻译**。
4. **输出**：Agent 将结果写入 `{root}/MEMORY/news/intelligence_current_refined.json`。**[硬约束：必须新增并包含 `intel_grade` 分级，以及 `top_10`, `translations`, `insights`, `punchline`, `digest`, `market` 七个核心字段]**。
5. **分级与联结**：参照 `references/quality_standard.md` 将情报物理分类为 L1-L4，建立结构化的逻辑湖资产索引。

### 第三阶段：对抗性博弈审计 (Adversarial Audit Gateway) [PLANNING Mode]
1. **物理网关触发条件**：该阶段被硬性阻断。必须向 `{root}/MEMORY/news/intelligence_current_refined.json` 执行读操作，解析 `intel_grade` 字段。
2. **审计许可**：**只有当情报评级达到 L4 级（Alpha级别/非共识洞察）时，才允许调用 `logic-adversary` 技能执行全量对抗。**
3. **任务**：模拟红队，从医疗数字化专家、医学专家等角度暴力挑战 Alpha 结论的鲁棒性，打碎一切可能的“自动化偏见”。

### 第四阶段：战略简报生成 (Strategic Briefing) [EXECUTION Mode]
1. **工作流状态**：渲染开始前，切换生命周期指引至 **`🟡 综合起草`**。
2. **执行**：`python scripts/forge.py`。
3. **功能**：整合精炼情报，按 `references/briefing_template.md` 模板渲染中文化最终简报。
4. **无损降级 (Robust Parsing)**：若 JSON 输出意外缺失或损坏，触发自愈逻辑，自动降级为原始列表渲染，并添加 `[WAITING]` 标识，确保简报始终可交付。

### 第五阶段：物理归档与索引 (Archiving & Indexing) [EXECUTION Mode]
1. **工作流状态**：收尾工作进入 **`🔴 归档冻结`** 并清除中间态态沙箱文件。
2. **执行**：`python scripts/update_index.py`。
3. **持久化**：简报保存至 `{root}/MEMORY/news/intelligence_[YYYYMMDD]_briefing.md`。
4. **索引维护**：同时更新 Markdown 总目与 JSON 检索索引。

## 3. 核心约束 (Constraints)
- **硬核网关 (Gateway Protocol)**：对抗审计前必须执行基于 `intel_grade` 的阈值判断，严格隔离噪音。
- **状态感知 (GEB-Flow Synchronization)**：核心异步任务必须使用 `task_boundary` 回调当前阶段（🟢/🟡/🔴）。
- **解耦防腐 (Prompt Decoupling)**：绝不允许在主循环代码中硬封装包含思维链（CoT）的复杂提示词，它们必须是独立的 .md/.txt 配置文件。
- **路径协议**：统一使用 `scripts/utils.py` 获取路径，严禁硬编码绝对路径。
- **全量中文化**：最终面向用户的战略简报展示必须达到 100% 中文化水平。
- **依赖管理**：Python 依赖通过 `requirements.txt` 管理。

## 4. 维护协议 (Maintenance Protocol)
- **Sensor Update**: 新增采集源需同步更新 `fetch_news.py` 与 `references/karpathy_feeds.json`。
- **Focus Sync**: 每次执行前必须先进行 Phase 0 校准。
- **Standard Header**: 所有脚本必须保持标准 Header 契约（@Input, @Output, @Pos）。

## 5. Anti-Patterns (绝对禁令)
- ❌ **禁止黑盒长轮询**：严禁无进度通知的静默爬取。即使异步，也必须声明正在执行的 🟢 扫描状态。
- ❌ **禁止弱网关溢出**：对低阶（L1-L2）资讯启动大模型暴力穷举推演是对算力和专注力的极其浪费，严格遵循 `intel_grade` 分流。
- ❌ **禁止全内存操作**：每一个阶段的成果（JSON或MD文件）必须立刻落盘，下一过程必须基于落盘的物理文件提取上下文。

## 6. 资源库
- **校准引擎**: `scripts/calibrate_focus.py`（Phase 0，词频权重校准）。
- **采集引擎**: `scripts/fetch_news.py`（Phase 1，多源后台并发抓取）。
- **精炼引擎**: `scripts/refine.py`（Phase 2，评分排序 + 提示词剥离生成）。
- **锻造引擎**: `scripts/forge.py`（Phase 4，简报无损模板渲染）。
- **索引引擎**: `scripts/update_index.py`（Phase 5，归档索引维护）。
- **质量标准**: `references/quality_standard.md`（L1-L4 分级与叙事纪律）。
- **情报总目**: `{root}/MEMORY/news/_INDEX.md`。
