---
name: hit-industry-radar
version: 8.2.0
description: 医疗行业战略雷达。Primary owner for weekly healthcare IT news, competitor moves, bids, vendor dynamics, and market-event battle reports. Use for fast-moving market signals. Prefer hit-weekly-brief for consulting reports and whitepapers, and hit-lectures-scout for academic or clinical paper scouting.
triggers: ["本周战报", "医疗IT战报", "竞对动态", "行业大事件"]
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

# HIT Industry Radar (医疗行业雷达 V8.2 Native)

> **Vision**: 消除跨周失忆与孤立事件堆砌，基于 Blackboard 模式的情报组装机。

本技能只处理**本周（周一至周日）**的时效情报，绝不为过期新闻或泛行业介绍生成战报。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 并发定向侦察 (Concurrent Directed Reconnaissance) [Mode: PLANNING]
1. 主代理阅读本技能 `assets/intelligence_targets.json` 里的高价值信源列表。
2. **集群并发拉起 (Subagent Delegation)**: 必须使用原生的 `invoke_subagent` 并发拉起 3 个 `TypeName: research` 的子代理，将国际、国内、卫宁基准的情报收集目标下发给他们。绝对禁止主代理在当前对话框内自己做低效的广域搜索。在拉起子代理时，必须明确在 Prompt 中指示他们：“使用 `write_to_file` 工具将底层抓取数据写入 `C:\Users\shich\.gemini\tmp\raw_scout_data_[战区].json`”。
3. **静默挂起与硬锁读取**: 主代理必须结束当前对话轮次，静默等待子代理完成写入。主代理恢复时，必须使用 `view_file` 验证这些数据确实存在。

### Phase 2: 图谱去重与仲裁推演 (Deduplication & Causal Weaving) [Mode: EXECUTION]
1. 若发现重大竞对动作，必须优先调用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `search_vector_lake`) 检索该动作是否已在过往 14 天内记录过，执行语义去重。
2. **五维清洗**: 剔除留存 Fact 中的所有形容词与公关废话。
3. **织者推理**: 跨越不同标段和厂商，提取出“隐含供应链共振”规律。

### Phase 3: The Hard Gate (草稿校验与跨平台审查) [Mode: VERIFICATION]
1. 根据 <Contracts> 要求的 `[Format Stack]` 渲染草稿，强制使用 `write_to_file` 写入临时文件 `C:\Users\shich\.gemini\tmp\draft_hit_radar.md`。
2. **强制过检**: 调用原生的 `run_command` 执行跨平台审计脚本（必须挂载 UTF-8 数据流锁并使用绝对物理路径）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "C:\Users\shich\.gemini\tmp\draft_hit_radar.md" --mode radar`
3. 若报错拦截（如查出主观形容词或营销禁词），必须退回修正，最多重试 2 次。

### Phase 4: 激活与分层归档 (Activate & Async Ingest) [Mode: EXECUTION]
1. **物理落盘**: Phase 3 脚本审计返回 Exit Code 0 后，使用原生 `write_to_file` 工具将草稿正式写入：
   `C:\Users\shich\.gemini\MEMORY\raw\HealthcareIndustryRadar\DHWB-Radar-YYYYMMDD.md`
2. **知识异步入湖**: 落盘后，主代理必须提取包含双链 `[[ ]]` 的战略突变（如：友商实控权变更）。
   - 若图谱已存在该实体，使用 `replace_file_content` 将新情报作为 Timeline 追加至对应的实体卡中。
   - 然后必须使用 `call_mcp_tool` (ServerName: `vector-lake-mcp`, ToolName: `prepare_ingest_batch`) 将新节点抛入后台引擎异步消化。

## 2. <Contracts> (输出与交付契约)

### [Format Stack] 战报格式铁律
战报必须完全匹配如下拓扑结构：
```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[威胁定性]**: [防御或进攻动作]

> **工作量证明 (Proof of Work)**: [即使本周是静默期，也必须在此列举 1-2 条被仲裁过滤掉的“无数据公关噪音”，以此作为系统爬网的硬性证据]

## 一、 核心战区：事实与脱水情报 (Dehydrated Facts)
*(本部分禁止形容词，仅允许动作、版本或金额)*
### 1. 国际巨头生态 \ 2. 中国 EHR/HIS 底座厂商 \ 3. 数据要素与垂直医疗 AI 厂商
- **[公司名]**: [日期] [脱水的精确动作 Fact]

## 二、 战略全景对比矩阵 (Strategic Contrast Matrix)
| 公司名称 | 本周核心动作萃取 | 暴露的技术底座 | 战略意图与背景破译 (Insight) |
|---|---|---|---|

## 三、 织者洞察：涟漪效应与趋势推演 (Causal Implications)
### 1. [核心趋势/规律命名]
- **传导链条 (Causal Chain)**：[事件A] -> [事件B] -> [系统后果C]

## 🎯 战术下钻与应对建议 (Commander's Hook)
- **⚔️ 针对友商防御**：[建议]
- **🏥 针对CIO破冰**：[建议]
```

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **工具/调度幻觉 (Tool Hallucination)**：严禁使用旧版长指令 MCP，必须合法组合 `call_mcp_tool`。严禁主代理自行广域搜索，必须强制 `invoke_subagent`。
- **路径与工具死锁 (Pathing Deadlock)**：严禁写入漏层级或多层级的脚本路径。必须执行绝对物理寻址 `C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py`。落盘工具必须使用原生的 `write_to_file`，子代理交互也必须明确要求其使用该工具。
- **跨周失忆症 (Cross-week Amnesia)**：如果情报的时间差 `Event_Date_Delta < 14 days` 并且在历史记录中已经存在过，强行把旧闻当新闻汇报将被直接打回。
- **公关软文污染 (PR Pollution)**：Fact 节点中如果出现“取得了重大突破”、“全面升级”、“业界领先”等恶性主观形容词，或完全没有版本/金额数据，该节点被判定为污染，系统需立即查杀该 Fact。
