---
name: hit-industry-radar
description: 医疗行业战略雷达。当用户询问“卫宁动态”、“东软/创业中标”、“Epic/Cerner异动”、“医疗IT大事件”、“调用雷达扫描”、“扫描竞争对手新闻”、“HIT市场动态”或“本周医疗IT战报”时务必强制激活。基于五层价值链，输出高信噪比实战战报。
---

# HIT Industry Radar (医疗行业雷达) V5.1 

> **Vision**: 消除跨周失忆与孤立事件堆砌，基于 Blackboard 模式的情报组装机。

## 0. 核心操作约束 (Core Constraints)
- **时间范围硬锁**: 所有的情报检索与信息提取，严格限定在**本周之内（周一至周日）**，拒绝陈旧信息。
- **去重硬锁 (SemHash)**: 绝不重复过去 14 天内出现在 `~/.gemini/MEMORY/HealthcareIndustryRadar/` 目录下的历史事件。
- **事实基准 (Fact)**: 没有具体金额、具体版本号或明确时间节点的公关通稿，直接抛弃（例如“宣布了战略合作”属于无效噪音）。
- **分析基准 (Insight)**: 必须使用系统动力学视角（如：护城河、止血、价格战、算力房东），杜绝任何主观形容词（如“重大突破”、“创新”）。

## 1. 核心工作流 (Blackboard Execution Pipeline)

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
2. **物理落盘**: 使用 `write_file` 工具将战报物理保存至 `~/.gemini/MEMORY/HealthcareIndustryRadar/DHWB-Radar-YYYYMMDD.md` (替换为当天的年月日)。
3. **遥测记录 (Telemetry)**: 必须使用 `write_file` 将本次执行状态存入 `~/.gemini/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`。结构规范：`{"skill_name": "hit-industry-radar", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 2. 输出格式铁律 (Format Stack)

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

## 3. 历史失效先验 (Gotchas)
- **[CRITICAL]** NEVER repeat an identical event from a previous week. ALWAYS cross-reference historical radars before adding to the blackboard.
- **[CRITICAL]** DO NOT proceed past Arbiter phase if the Fact lacks concrete metrics.
- DO NOT use adjectives in the Fact section (e.g., avoid "significant", "innovative"). MAINTAIN a cold, surgical narrative tone.
