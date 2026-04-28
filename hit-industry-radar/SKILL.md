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

# HIT Industry Radar (医疗行业雷达) V5.1 

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

### Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat, heavy lifting tasks (e.g., mass web scraping, parsing long PDFs, or generating multi-thousand-word drafts) MUST NOT be executed directly in the main memory.
1. **Packet Creation**: Before starting the heavy task, write the required parameters, URLs, or chapter outlines to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Task_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) to read the packet, execute the heavy generation/scraping, and write the final output back to a designated result file.
3. **Suspension**: The main agent must suspend its execution, wait for the sub-agent to finish, and then read ONLY the final output file to proceed with orchestration or final review.

### 核心工作流 (Blackboard Execution Pipeline)

### Phase 1: 并发侦察 (Concurrent Reconnaissance)
1. **获取沙盒指令**: 读取本技能 `assets/` 目录下的静态指令包以获取精确的侦察意图：
   - `assets/Task_global_hit.md`
   - `assets/Task_china_hit.md`
   - `assets/Task_winning_baseline.md`
2. **集群并发调度**: 在 `~/.gemini/tmp/playgrounds/` 建立本次执行的临时空间。同时（并发）调用 3 次 `generalist` 子代理工具，分别下发上述三个指令包进行深度检索，并要求它们将“检索->过滤->提纯”的脱水结果分别写入指定临时文件：
   - `~/.gemini/tmp/playgrounds/Response_global_hit.md`
   - `~/.gemini/tmp/playgrounds/Response_china_hit.md`
   - `~/.gemini/tmp/playgrounds/Response_winning_baseline.md`
3. **清洗拦截**: 主代理回收并读取以上 3 个 Response 文件。利用 `grep_search` 等工具比对 `~/.gemini/MEMORY/HealthcareIndustryRadar/` 下的历史文件进行去重。完成后清除 `tmp/playgrounds/` 下的中间产物。

### Phase 2: 仲裁与二跳推理 (Arbiter & Weaver)
1. **五维清洗**: 对留存的 Fact 执行二次审计，剥离所有营销废话。
2. **织者推理**: 跨越不同厂商和标段，寻找“隐含供应链共振”或“暗中价格战预警”。提取为 1-2 条系统级公式/规律。

### Phase 3: 红队对抗审计 (Red Team Verification)
在最终拼装战报前，进行二元硬审计：
- [ ] 事实 (Fact) 部分是否剔除了所有主观形容词？ [Yes/No]
- [ ] 建议 (Insight) 动作是否具备直接的销售/研发话术价值？ [Yes/No]
若任一为 No，强制重写该节点。

### Phase 4: 激活与分层归档 (Activate & Archive)
1. **渲染战报**: 严格按照下方的 `[Format Stack]` 生成 Markdown 输出。
2. **物理落盘**: 使用 `write_file` 工具将战报物理保存至 `~/.gemini/MEMORY/raw/HealthcareIndustryRadar/DHWB-Radar-YYYYMMDD.md` (替换为当天的年月日)。
3. **遥测记录 (Telemetry)**: 必须使用 `write_file` 将本次执行状态存入 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。结构规范：`{"skill_name": "hit-industry-radar", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## Resources
- `assets/Task_global_hit.md`
- `assets/Task_china_hit.md`
- `assets/Task_winning_baseline.md`
- `~/.gemini/tmp/playgrounds/Response_global_hit.md`
- `~/.gemini/tmp/playgrounds/Response_china_hit.md`
- `~/.gemini/tmp/playgrounds/Response_winning_baseline.md`
- 历史目录：`~/.gemini/MEMORY/HealthcareIndustryRadar/`

## Failure Modes
- `IF [Action == "Add to Blackboard"] THEN [Halt if Event_Date_Delta < 14 days] AND [Require Cross-reference Historical Radars]`
- `IF [Phase == "Arbiter"] THEN [Halt if Fact lacks "Concrete Metrics"]`
- `IF [Section == "Fact"] THEN [Halt if Text contains "Adjectives"] AND [Require Cold Surgical Narrative Tone]`
- 禁止将没有金额、版本号或明确时间节点的公关稿写进最终战报。

## Output Contract
- 最终战报必须包含本周战略主轴、国际/中国战区事实与解读、织者洞察，以及下钻建议。
- 所有 Fact 节点都必须是冷静、可验证、去形容词的硬信息。

## Telemetry
- 使用 `write_file` 将本次执行状态存入 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。结构规范：`{"skill_name": "hit-industry-radar", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 输出格式铁律 (Format Stack)

```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[威胁定性]**: [防御或进攻动作]

## 一、 国际巨头：[国际战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[日期] [脱水的精确动作]
- **解读分析 (Insight)**：[商业本质标签及分析]

## 二、 中国军团：[国内战区主题]
### 1. [公司名称]
- **最新资讯 (Fact)**：[关键金额、版本、动作]
- **解读分析 (Insight)**：[防御性/进攻性分析]

## 三、 织者洞察 (Weaver's View)：[核心共振主题]
1. [系统级规律 1]
2. [系统级规律 2]

## 🎯 下钻建议 (Commander's Hook)
- [极具张力的深度对比建议，转化为 WiNEX 平台的防御建议]
```

## 3. 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Add to Blackboard"] THEN [Halt if Event_Date_Delta < 14 days] AND [Require Cross-reference Historical Radars]`
- `IF [Phase == "Arbiter"] THEN [Halt if Fact lacks "Concrete Metrics"]`
- `IF [Section == "Fact"] THEN [Halt if Text contains "Adjectives"] AND [Require Cold Surgical Narrative Tone]`
