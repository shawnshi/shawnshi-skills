---
name: personal-intelligence-hub
version: 7.4.0
description: |
  战略情报作战中枢 (Native Agent Edition)。基于《龙虾教程》五层价值链，交付具备极致信噪比的智库资产。
  核心要求：必须读取 feeds.json 确定扫描范围，遵循 quality_standard.md 执行三段论审计，强制使用 briefing_template.md 输出报告。
  对抗性审计：L3/L4 级情报必须调用 logic-adversary 执行红队验证。
  物理去重：必须通过 pushed_history.json 拦截过去 7 天内已推送过的 Top 10 信号。
  Native tools integration: google_web_search, glob, write_file, read_file, ask_user.
benefits-from: [logic-adversary]
triggers: ["获取最新情报", "分析行业趋势", "扫描技术新闻", "生成每日简报", "提取Alpha级洞察", "战略情报汇总"]
---

# Personal Intelligence Hub V7.4 (Native Agent Edition)

Version: 6.5 (The High-SNR Defense System) Vision: 消除过滤失败（Filter Failure），通过“弱信号放大”与“物理去重”建立决策优势。系统不再是线性 Pipeline，而是围绕“数字黑板”协作的 Multi-Agent 集群。

## 0. 核心架构约束 (The 5-Layer Value Chain)
感知层 (Sense): 引入 SemHash (语义哈希)。跨平台重复资讯在入口处即被拦截。
过滤层 (Filter): 实装 5D Arbiter。基于证据 (Evidence)、信誉、新颖度、一致性、时效性的二元硬核拦截。
关联层 (Connect): 激活 Weaver (织者)。寻找表象无关但底层逻辑相关的情报串联，生成“二跳推理”。
个性化层 (Personalize): 引入 Serendipity (意外之喜)。自动探测用户过去 10 天未曾接触的跨界 Alpha 信号。
激活层 (Activate): Format Stack (分层交付)。按紧急 (10s)、日常 (15min)、深度 (Deep Dive) 分层渲染。
1. 核心调度约束 (Global Blackboard Mode)
[黑板协议]：所有执行动作必须读写 tmp/intelligence_blackboard.json 共享状态。每一步必须在输出首行打印 [System State: Moving to Phase X] 探针。

## 1. Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat, long-running pipelines (e.g., scraping multiple URLs, filtering high-noise feeds) MUST NOT be executed directly in the main memory.
1. **Packet Creation**: Before starting a heavy scraping/parsing task, write the specific parameters or target URLs to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Task_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) to consume the packet, execute the heavy scraping, and write the output back to a designated result file.
3. **Suspension**: The main agent must suspend execution, wait for the sub-agent to complete the task, and then read ONLY the final synthesized result file to continue the orchestration.

## 2. 执行协议 (Execution Protocol)
### Phase 0: 战略对齐与黑板初始化 [Mode: PLANNING]
Initialize: 运行 scripts/blackboard.py 初始化会话状态。
强制拦截: 调用 ask_user 复述扫描域，确认是否需要针对特定竞对（如东软/Epic）执行“专项侦察”。
### Phase 1: 扫描矩阵与语义去重 [Mode: EXECUTION]
采集点火 (Sentinel): 执行 scripts/fetch_news.py。
SemHash 拦截: 调用 history_manager.py 对标题哈希进行物理去重，拦截已读信号。
### Phase 2: 五维仲裁与织网 (Filter & Connect) [Mode: EXECUTION]
五维审计 (Arbiter): 执行 scripts/refine.py。强制执行 Evidence-Check，无数据支撑的信号直接归位噪音。
二跳推理 (Weaver): Agent 扫描黑板，寻找“芯片+车企+台风 = 供应链危机”级别的逻辑关联。
### Phase 3: 对抗性博弈 (Advocate) [Mode: EXECUTION]
红方激活: 若包含 L4/Alpha 情报，强制调用 logic-adversary。
非共识识别: 专门搜寻与市场主流情绪相悖的证据，防止确认偏差。记录 [Adversarial_Audit]。
### Phase 4: 分层简报铸造 (Activate) [Mode: EXECUTION]
Format Stack 渲染: 执行 scripts/forge.py。按“紧急预警 -> 战略判词 -> 行动杠杆 -> Top 10”分层排版。
So What 转换: 每一个情报点必须翻译为具体的“业务动作建议”。
### Phase 5: 物理归档与自愈 [Mode: EXECUTION]
保存：生成的报告保存在"{root}\.gemini\MEMORY\raw\news"
归档: 将 Top 10 的 URL 与语义指纹存入 pushed_history_v2.json。
认知蒸馏: 自动更新 pai\MEMORY.md 增量记忆。
## 3. Anti-Patterns (绝对禁令)
❌ 禁止“摘要式”空转: 如果 AI 只是概括了文章，未产生“联结”与“推演”，视为废稿。
❌ 禁止跨日期逻辑复读: Top 10 严禁出现过去 7 天内已推送过的核心信号。
❌ 禁止“算法谄媚”: 严禁在 Evidence 不足时给出高分评价。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "personal-intelligence-hub", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Refine News"] THEN [Require is_redundant() == TRUE]`
- `IF [URL matches "antirez.com/news/160" OR is_benchmark] THEN [Halt inclusion into Top 10]`
- `IF [Source Content == "Corporate PR"] THEN [Halt Summarization & Discard]`
- `IF [Signal == "urgent_signals"] THEN [Enforce Strict Restriction Criteria]`
