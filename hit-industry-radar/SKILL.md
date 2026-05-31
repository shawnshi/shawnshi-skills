---
name: hit-industry-radar
description: 医疗行业战略雷达。Primary owner for weekly healthcare IT news, competitor moves, bids, vendor dynamics, and market-event battle reports. Use for fast-moving market signals. Prefer hit-weekly-brief for consulting reports and whitepapers, and hit-lectures-scout for academic or clinical paper scouting.
---

<strategy-gene>
Keywords: 医疗 IT 战报, 竞对动态, 行业周报, 价格战预警
Summary: 基于黑板模式调度并发子代理，将碎片化周级情报组装为系统动力学战报。
Strategy:
1. 并发侦察：同时下发国际、国内、卫宁基准指令包至 sandbox。
2. 织者推理：寻找不同标段间的“隐含供应链共振”与价格战预警。
3. 事实仲裁：剥离营销废话，仅保留带金额、版本或节点的硬信息。
AVOID: 严禁重复 14 天内的旧闻；禁止包含无具体数据的公关通稿；禁止使用主观形容词描述事实。
</strategy-gene>

# HIT Industry Radar (医疗行业雷达) V5.2

> **Vision**: 消除跨周失忆与孤立事件堆砌，基于 Blackboard 模式的情报组装机。

## When to Use
- 当用户要求扫描本周医疗 IT 战报、竞对动态或行业大事件时使用。
- 本技能只处理周级时效情报，不为过期新闻或泛行业介绍生成战报。

## Workflow

### 核心操作约束 (Core Constraints)
- **时间范围硬锁**: 所有的情报检索与信息提取，严格限定在**本周之内（周一至周日）**，拒绝陈旧信息。
- **去重硬锁 (SemHash)**: 绝不重复过去 14 天内出现在 `~/.gemini/MEMORY/HealthcareIndustryRadar/` 目录下的历史事件。
- **事实基准 (Fact)**: 没有具体金额、具体版本号或明确时间节点的公关通稿，直接抛弃（例如“宣布了战略合作”属于无效噪音）。
- **分析基准 (Insight)**: 必须使用系统动力学视角（如：护城河、止血、价格战、算力房东），杜绝任何主观形容词（如“重大突破”、“创新”）。

### Sub-agent Delegation Protocol (Antigravity Native)
**CRITICAL RULE**: 为保护主代理的上下文不被海量爬虫数据污染，必须使用原生 `invoke_subagent` 工具执行并发爬取，绝对禁止主代理在当前上下文直接执行广域搜索。
1. **Target Manifest**: 子代理必须优先依据 `assets/intelligence_targets.json` 中的定向高价值信源（如采购网、官微、交易所接口）进行探测，拒绝在公网盲目大海捞针。
2. **Delegation**: 使用 `invoke_subagent` 并发唤起子代理（`TypeName: research`），通过 `Prompt` 参数直接下发战区探测意图。
3. **Suspension**: 主代理结束当前对话轮次，静默等待所有子代理的回调（Callback），并强制要求子代理将原始抓取数据写入临时文件 `C:/Users/shich/.gemini/tmp/raw_scout_data_[战区].json`。
4. **Dependency Lock (数据硬锁)**: 主代理恢复运行后，必须使用 `view_file` 读取子代理的抓取文件。如果你没有读取到真实的原始数据，严禁生成战报，必须报错并停止。

### 核心工作流 (Blackboard Execution Pipeline)

### Phase 1: 并发定向侦察 (Concurrent Directed Reconnaissance)
1. **获取侦察意图**: 参考本技能 `assets/` 目录下的指令包及信源清单以获取精确搜索目标：
   - `assets/intelligence_targets.json` (强制信源列表)
   - `assets/Task_global_hit.md`
   - `assets/Task_china_hit.md`
   - `assets/Task_winning_baseline.md`
2. **集群并发调度**: 使用 `invoke_subagent` 并发拉起 3 个 `research` 类型的子代理，分别下发国际、国内、卫宁基准的情报收集 Prompt，要求其提纯后向主代理汇报结果。
3. **图谱语义去重 (Semantic Deduplication)**: 主代理回收汇报后。若发现重大竞对动作，必须优先利用 `mcp_vector-lake-mcp_search_vector_lake`（Mode: claim/page）检索竞对实体，判断该动作是否在图谱中已存在或已被预判，实现基于实体和声明的语义级防重。

### Phase 2: 仲裁与二跳推理 (Arbiter & Weaver)
1. **五维清洗**: 对留存的 Fact 执行二次审计，剥离所有营销废话。
2. **织者推理**: 跨越不同厂商和标段，寻找“隐含供应链共振”或“暗中价格战预警”。提取为 1-2 条系统级公式/规律。

### Phase 3: 红队对抗审计 (Red Team Verification)
在最终拼装战报前，进行二元硬审计：
- [ ] 事实 (Fact) 部分是否剔除了所有主观形容词？ [Yes/No]
- [ ] 建议 (Insight) 动作是否具备直接的销售/研发话术价值？ [Yes/No]
若任一为 No，强制重写该节点。

### Phase 4: The Hard Gate (物理层强制代码审计)
1. **渲染战报草稿**: 严格按照下方的 `[Format Stack]` 生成 Markdown 输出，并**强制**将其写入临时文件 `C:/Users/shich/.gemini/tmp/draft_hit_radar.md`。
2. **强制过检**: 调用 shell 执行跨平台强编码审计：
   `$env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/scripts/hit_audit_gate.py" "C:/Users/shich/.gemini/tmp/draft_hit_radar.md" --mode radar`
3. **处理失败**: 如果审计脚本报错（如包含“全栈式”、“智慧大脑”等营销禁词，或 Fact 缺乏数字指标），必须退回上一步修正草稿，最多重试 2 次。

### Phase 5: 激活与分层归档 (Activate & Async Ingest)
1. **物理落盘**: 只有在 Phase 4 返回 `Audit Passed` (Exit Code 0) 后，才允许使用 `write_file` 工具将草稿内容物理保存至最终目录 `C:/Users/shich/.gemini/MEMORY/raw/HealthcareIndustryRadar/DHWB-Radar-YYYYMMDD.md`。
2. **知识异步入湖 (Graph Ingestion)**：战报落盘后，强制主代理甄别高价值战略突变（如：友商实控权变更、全新架构发布）。若存在，必须利用 `write_file` 或 `replace` 将该结论作为 Timeline 节点追加至 `MEMORY/wiki/Entity_*.md` 对应的实体卡片中。
   - **异步同步流**: 严禁调用阻塞式 Sync。必须调用 `mcp_vector-lake-mcp_prepare_ingest_batch` 提取待同步清单，随后利用 `invoke_subagent` 拉起 `vector-lake-ingestor` 异步消化。
3. **遥测记录**: (已废弃手动写入，由系统基建自动追踪 Token 与耗时)。

## Resources
- `assets/intelligence_targets.json`
- `assets/Task_global_hit.md`
- `assets/Task_china_hit.md`
- `assets/Task_winning_baseline.md`
- 历史目录：`C:/Users/shich/.gemini/MEMORY/HealthcareIndustryRadar/`

## Failure Modes
- `IF [Action == "Add to Blackboard"] THEN [Halt if Event_Date_Delta < 14 days] AND [Require Cross-reference Historical Radars]`
- `IF [Phase == "Arbiter"] THEN [Halt if Fact lacks "Concrete Metrics"]`
- `IF [Section == "Fact"] THEN [Halt if Text contains "Adjectives"] AND [Require Cold Surgical Narrative Tone]`
- 禁止将没有金额、版本号或明确时间节点的公关稿写进最终战报。

## Output Contract
- 最终战报必须包含：本周战略主轴、脱水事实分区（国际巨头/底座厂商/AI厂商）、全景对比矩阵、带有传导链条的织者洞察，以及分众化的战术下钻建议（CIO视角与友商防御视角）、参考来源。
- 所有 Fact 节点都必须是冷静、可验证、去形容词的硬信息。

## Telemetry
- [已移除] 遥测统计由系统生命周期钩子自动完成，无需 Agent 介入。

## 输出格式铁律 (Format Stack)

```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[威胁定性]**: [防御或进攻动作]

> **工作量证明 (Proof of Work)**: [必填：即使本周是静默期，也必须在此列举 1-2 条被仲裁过滤掉的“无数据公关噪音”，例如“某厂商发布了未经证实的合作通稿”，以此作为系统执行过真实爬网侦察的硬性证据]

## 一、 核心战区：事实与脱水情报 (Dehydrated Facts)
*(注：本部分仅允许冷峻陈述事实，禁止任何主观形容词，必须包含具体动作、版本或金额)*

### 1. 国际巨头生态
- **[公司名]**: [日期] [脱水的精确动作 Fact]

### 2. 中国 EHR/HIS 底座厂商
- **[公司名]**: [日期] [脱水的精确动作 Fact]

### 3. 数据要素与垂直医疗 AI 厂商
- **[公司名]**: [日期] [脱水的精确动作 Fact]

## 二、 战略全景对比矩阵 (Strategic Contrast Matrix)
| 公司名称 | 本周核心动作萃取 | 暴露的技术底座 | 战略意图与背景破译 (Insight) |
|---|---|---|---|
| [公司] | [极简Fact] | [如：逻辑湖/遗留系统等] | [商业本质定性] |

## 三、 织者洞察：涟漪效应与趋势推演 (Causal Implications)
### 1. [核心趋势/规律命名]
- **传导链条 (Causal Chain)**：[事件A] -> [事件B] -> [系统性后果C]
- **底层逻辑**：[第一性原理分析]

## 🎯 战术下钻与应对建议 (Commander's Hook)
- **⚔️ 针对医疗 IT 友商（防御/进攻视角）**：[如何结合 WiNEX 平台等进行对抗的深度建议]
- **🏥 针对医院 CIO（销售破冰视角）**：[如何利用本次情报制造院方痛点共鸣或提供解决方案]

## 🔗 情报溯源 (References)
- [[链接标题]](URL)
```

## 3. 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Add to Blackboard"] THEN [Halt if Event_Date_Delta < 14 days] AND [Require Cross-reference Historical Radars]`
- `IF [Phase == "Arbiter"] THEN [Halt if Fact lacks "Concrete Metrics"]`
- `IF [Section == "Fact"] THEN [Halt if Text contains "Adjectives"] AND [Require Cold Surgical Narrative Tone]`
