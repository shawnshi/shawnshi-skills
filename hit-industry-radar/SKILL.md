---
name: hit-industry-radar
version: 9.0.0
tier: action-allowed
description: '医疗行业战略雷达。调度子代理并发抓取周级医疗IT战报与竞对动态，并利用 Logic Lake 执行去重与编织。禁止抓取 14 天前的旧闻，禁止保留无数据支撑的公关废话。'
triggers: ["本周战报", "医疗IT战报", "竞对动态", "行业大事件"]
---

<strategy-gene>
Keywords: 医疗 IT 战报, 竞对动态, 行业周报, 价格战预警
Summary: 基于黑板模式调度并发子代理，将碎片化周级情报组装为系统动力学战报。
Strategy:
1. 1. 并发侦察：同时下发国际、国内、卫宁基准指令包至 sandbox。
2. 2. 语义去重：利用图谱引擎剥离 14 天内重复出现的旧闻。
3. 3. 事实仲裁：剥离营销废话，仅保留带金额、版本或节点的硬信息。
4. 4. 织者推理：寻找不同标段间的“隐含供应链共振”与价格战预警。
AVOID: 大模型在单线程广域搜索中迷失；脱离网页 URL 进行情报编造。
</strategy-gene>

# HIT Industry Radar (医疗行业雷达 V8.2 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `invoke_subagent` (并发抓取本周事实)
2. `call_mcp_tool` (针对疑似竞对大动作进行 14 天图谱去重)
3. `write_to_file` (写入草稿沙盒)
4. `run_command` (跨平台代码级质检)
5. `write_to_file` (战报落盘)
6. `invoke_subagent` (战略突变异步委派入湖)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 并发定向侦察
1. 读取本技能 `assets/intelligence_targets.json` 里的高价值信源列表。
2. **集群拉起**: 调用 `invoke_subagent` 并发拉起 3 个 `research` 子代理，将国际、国内、卫宁基准指令下发。
   - **硬性盯盘名单优化**：除了传统 HIS（卫宁/创业/Epic等），必须新增“降维打击者”队列（华为医疗大模型算力池、腾讯健康、百度灵医智大）。
   - **关键词优化**：将原本的“产品发布”转向“政策买单点”，重点搜索 `信创替代大单`、`DRG/DIP 控费衍生项目`、`医疗数据资产入表 / 质押融资`。
   - 指示子代理：“所有事实须 100% 来源真实网页。你必须返回包含 `source_url`（必须是规范的 https:// 链接）和 `publish_date`（精确的 YYYY-MM-DD 格式）的 JSON 结构。若无情报则返回空数组 `[]`，禁止基于知识截断编造或使用占位符链接。”
   - 指示子代理使用 `send_message` 以 JSON 格式回传。
3. **等待回调**: 主代理等待子代理回调完毕后再进入合成阶段。

### Phase 2: 图谱去重与仲裁推演
1. 发现重大竞对动作时，调用 `call_mcp_tool` (`vector-lake-mcp`: `search_vector_lake`) 检索 14 天内是否已记录，执行语义去重。
2. **五维清洗**: 剔除留存 Fact 中的所有形容词与公关废话（严禁“赋能”、“生态”、“智慧体系”等空话），仅留时间/金额/版本/核心临床KPI（如DRG控费、评级过检）。强制保留原始的真实 URL，绝不允许在合成期丢弃链接。
3. **织者推理**: 跨越不同标段和厂商，提取出“隐含供应链共振”规律。

### Phase 3: The Hard Gate (草稿校验)
1. 渲染草稿并写入当前会话隔离区：`<appDataDir>\brain\<conversation-id>\scratch\draft_hit_radar.md`。
2. **过检审计**: 使用 `run_command` 执行审计脚本（需挂载 UTF-8，强制 `WaitMsBeforeAsync=3000` 防死锁）：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_radar.md" --mode radar
   ```
3. 若报错拦截（查出主观形容词或营销禁词），退回修正，最多重试 2 次。

### Phase 4: 分层归档与图谱入湖 (STQM & Payload MCP)
1. **物理落盘**: 质检通过后，使用 `write_to_file` 写入：
   `C:\Users\shich\.gemini\MEMORY\raw\HealthcareIndustryRadar\DHWB-Radar-YYYYMMDD.md`
2. **异步入湖**: 提取草稿中第四部分生成的 STQM JSON 数据，强制使用 `write_to_file` 写入 `scratch/ingest_payload.json`，如有战略突变必须提取为 `tension_edges`。
3. 调用 `invoke_subagent` 唤醒入湖子代理 (TypeName: self)，明确指令：“读取 scratch/ingest_payload.json，调用 `vector-lake-mcp:prepare_ingest_batch` 执行入湖，绝对禁止通过命令行参数或提示词传递长文本。”

## 2. <Contracts> (输出与交付契约)
### [Format Stack] 战报格式模板
```markdown
# 医疗 IT 行业战略雷达 - [时间周期]
> **本周战略主轴**：[一句话概括核心对抗焦点]

## 🚨 紧急预警 (Urgent - 10s Read)
- **[威胁定性]**: [防御或进攻动作]

> **工作量证明**: [必须列举 1-2 条被仲裁过滤的公关噪音作为检索证明，证明系统确实扫描过但主动拦截了劣质内容]

## 一、 核心战区：事实与脱水情报
*(禁止形容词，仅允许动作。必须包含 亿/万/版本号 等硬核数据，并且每条事实末尾必须附带真实可点击的 URL)*
### 1. 国际巨头生态 \ 2. 中国 EHR/HIS 底座厂商 \ 3. 数据要素与垂直医疗 AI 厂商
- **[[公司名]]**: [YYYY-MM-DD] [脱水精确动作 Fact] [来源](https://...)

## 二、 战略全景对比矩阵
| 公司名称 | 本周核心动作萃取 | 暴露的技术底座 | 战略意图与背景破译 |
|---|---|---|---|

## 三、 织者洞察：涟漪效应与趋势推演
### 1. [核心趋势/规律命名]
- **传导链条**：[事件A] -> [事件B] -> [系统后果C]

## 四、 行业张力与冲突网 (STQM Tension Edges)
- [必须将本周的战略背离或供应链共振（如：学术主权 vs 商业退潮、标准化 vs 定制化），结构化为符合 STQM 规范的张力边 (`tension_edges`) 载荷，作为后续 Vector Lake 入湖的数据源。必须是纯 JSON 代码块。]

## 🎯 战术下钻与应对建议
- **⚔️ 针对友商防御**：[建议]
- **🏥 针对CIO破冰**：[建议]
```
交付完成后，必须通过 Markdown 语法向用户提供指向落盘文件的绝对链接。

## 3. <Failure_Taxonomy> (失败分类学)
- **跨周失忆症**：未调用图谱引擎拦截，将 14 天前的旧新闻当做本周战报输出。
- **公关软文污染**：脱水情报中残留“业界领先”、“全面赋能”等恶性主观形容词，被脚本拦截。
- **孤立查词幻觉**：不使用 `invoke_subagent` 发起并发代理，主模型在单线程中消耗时间。
