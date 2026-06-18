---
name: hit-intelligence-hub
version: 9.0.0
tier: action-allowed
description: '医疗数字化情报指挥中枢。通过子代理并发调度市场、智库与学术三路集群，执行跨域共振映射输出总裁级看板。禁止串行执行，禁止主代理自行搜索或堆砌原文。'
triggers: ["全局战略视野图", "全景情报", "医疗数字化全景", "执行三军集群扫描"]
---

<strategy-gene>
Keywords: 全局视野, 医疗战略情报, HIT Swarm, 综合简报
Summary: 代理集群指挥官。通过并发唤醒三个战役集群，将独立战报熔炼为高维战略面板。
Strategy:
1. 并发调度：使用 `invoke_subagent` 一次性并发发射 3 个自洽的子代理。
2. 跨域映射：跨越孤立事实，寻找学术突破、市场动态与政策间的共振点与价值鸿沟。
3. 高维降噪：生成极端压缩的总裁级看板，强调行动杠杆。
AVOID: 大模型亲自下场执行搜索；将长文机械拼接而非重新熔炼。
</strategy-gene>

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `invoke_subagent` (以 self 类型并发唤醒三个技能)
2. `write_to_file` (最终 Dashboard 落盘)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 三军齐发 (Concurrent Fleet Launch)
You MUST NOT execute web searches or write the sub-reports yourself.
Use the `invoke_subagent` tool to spawn 3 subagents SIMULTANEOUSLY.
1. **Radar Agent**
   - TypeName: `self`
   - Role: `Market Radar`
   - Prompt: "Activate the `hit-industry-radar` skill. Execute a full scan for this week and return your final dehydrated report to me via `send_message`. You are fully autonomous."
2. **Brief Agent**
   - TypeName: `self`
   - Role: `Think-Tank Analyst`
   - Prompt: "Activate the `hit-weekly-brief` skill. Execute a full scan for this week and return your final strategic brief to me via `send_message`. You are fully autonomous."
3. **Scout Agent**
   - TypeName: `self`
   - Role: `Academic Scout`
   - Prompt: "Activate the `hit-lectures-scout` skill. Execute a full scan of recent medical AI papers and return your final report to me via `send_message`. You are fully autonomous."

*Note: Since each subagent handles its own complex sub-swarms, this operation is computationally expensive. Wait reactively for all 3 subagents to return their final text.*

### Phase 2: 跨域共振映射 (Cross-Domain Resonance)
收到 3 份回调报告后，分析以下跨域交叉点：
- **The Echo (共鸣)**: 学术侦察中出现的新技术，是否在智库研报中得到了印证？
- **The Gap (鸿沟)**: 市场是否在激烈争夺某个在学术界已被证明落后的概念？
- **The Catalyst (催化剂)**: 智库研报中的哪些政策/事件将直接加速市场雷达中的趋势？

### Phase 3: The CEO Dashboard (Synthesis & Output)
起草终极战略大屏。必须高度压缩脱水，滤除噪音，仅突显系统级趋势。
输出格式：
1. **The Executive Summary (一句话定调)**: 50字以内。
2. **The Resonance Map (跨域共振点)**: 3 个要点突出跨域交汇点。
3. **Radar Summary (市场动态摘要)**: 3 个最大市场动作。
4. **Think-Tank Summary (智库研报摘要)**: 3 个最大战略转向。
5. **Academic Summary (学术突破摘要)**: 3 个最具破坏性的技术突破。
6. **Actionable Lever (行动杠杆)**: 周一早会必须采取的应对动作。

## 2. <Contracts> (输出与交付契约)
- **Output Artifact**: 最终面板必须通过 `write_to_file` 工具写入沙盒区 `<appDataDir>\brain\<conversation-id>\scratch\HIT_Global_Dashboard.md`，并在聊天流向用户展示摘要。
- **Strict Concurrency**: 3 个子代理必须包含在同一个 `invoke_subagent` 数组中被发射，拒绝串行启动。

## 3. <Failure_Taxonomy> (失败分类学)
- **微操幻觉 (Micro-Management)**: 试图告诉子代理具体怎么搜查。子代理自带其原生技能的流程控制，主代理只需下达触发指令。
- **超时恐慌 (Timeout Panic)**: 子代理在底层会拉起自身的 swarm，耗时较长。主代理若恐慌并尝试自行触发原生网页搜索工具，将被判定为越权。
