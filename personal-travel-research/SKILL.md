---
name: personal-travel-research
version: 8.1.0
description: "Deep travel research workflow for museums and ancient architecture. Input a city name, auto-generates structured knowledge document (org-mode) + portable reference cards (PNG). Covers historical background, museum highlights, archaeological significance, and architectural heritage. Use when user says '旅行研究', '博物馆功课', '古建功课', 'travel research', '出发前功课', or provides a city name with intent to do deep cultural travel preparation."
triggers: ["旅行研究", "博物馆功课", "古建功课", "travel research", "出发前功课"]
---

<strategy-gene>
Keywords: 旅行研究, 博物馆, 古建筑, 考古, 城市案头研究
Summary: 为文化旅行生成结构化知识文档和便携参考卡。
Strategy:
1. 锚定城市、时间、兴趣主题和行程深度。
2. 使用原生 invoke_subagent 发起大规模并行研究。
3. 输出结构化知识长文档（包含博物馆、古建、历史脉络等）。
AVOID: 禁止只列景点；禁止忽略开放时间、位置和历史背景；禁止在缺乏真实 URL 来源的情况下强行胡编。
</strategy-gene>

# Personal Travel Research (深度文化旅行案头研究 V8.1 Native)

本技能是对目标城市执行极其严谨的“考古学案头评估（Desk-Based Assessment）”。核心设计是不分“知识底图”和“平台发现”，而是直接通过原生大并发子智能体执行多维度的同步突击搜索。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 解析与兵力投送 (Concurrent Deployment) [Mode: PLANNING]
从用户的请求中提取城市名以及可能的聚焦主题（如：唐代、石窟等）。
紧接着，主代理必须使用原生的 `invoke_subagent` 工具，一次性组装并启动多个 `TypeName: research` 型子智能体，对以下 6 个核心维度进行并发围剿（必须通过中英文双语搜索）：

- **Subagent A (历史分层)**: 搜索该城市的历史时期、物质遗存、朝代更迭对城市格局的影响。
- **Subagent B (重点博物馆)**: 搜索重要博物馆、镇馆之宝、核心馆藏及具有重大考古意义的展品，并查清展厅位置。
- **Subagent C (古建遗存)**: 搜索现存重要古建筑、营造年代、建筑形制、国保单位，以及看建筑时应关注的微观细节（斗拱/碑刻等）。
- **Subagent D (重大考古发现)**: 搜索重大考古事件及其发掘故事，文物现藏地。
- **Subagent E (人文脉络)**: 搜索相关历史人物、文学作品、文化性格。
- **Subagent F (深网内容提取)**: 搜索 B站、知乎、微信公众号等平台的深度讲解长文或视频（筛除纯打卡推荐，仅保留深度分析），提取高价值 URL 及摘要。

### Phase 2: 内容提炼 (Content Distillation) [Mode: EXECUTION]
待上述所有子代理在后台返回情报后，主代理将对回收的有效 URL（特别是 B 站深度视频或长文）进行提纯。
- 此时可直接利用原生的 `read_url_content` 工具快速抓取文本，提取其中的高价值知识点（不阻塞，如部分 URL 报错直接跳过）。

### Phase 3: 终极合成与落盘 (Synthesis & Archive) [Mode: EXECUTION]
将收集到的海量情报收敛为一份结构极度严谨的 Markdown 文档。
1. **强制采用物理绝对路径落盘**:
   使用原生 `write_to_file` 工具，将该文档安全保存至：`C:\Users\shich\.gemini\MEMORY\notes\{YYYYMMDDTHHMMSS}==z--{城市}旅行研究.md`
2. **结构锁**: 文档必须包含以下 Org-mode 风格的核心骨架：
   `* 城市概览`, `* 历史分层`, `* 博物馆指南` (必含镇馆之宝、重点展厅、易被错过的), `* 古建遗存` (必含观察细节), `* 考古发现`, `* 参观路线`, `* 深度内容推荐`。

## 2. <Contracts> (输出与交付契约)
- **学术级品控**: 每个具体的地点/文物推荐，**必须**附带“为什么看”以及“看什么细节”，决不允许空泛的旅游导词。没有确切来源信息的模块宁可留空，绝对不编。
- **降级不中断原则**: 若深网内容提炼失败（URL 无效等），作为增强层的 Phase 2 允许直接失败，系统必须利用 Phase 1 的情报继续合成文档。
- **Telemetry 记录**: 文档落盘后，使用 `write_to_file` 将元数据记录至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
  格式示例：`{"skill_name": "personal-travel-research", "status": "success", "duration_sec": 12, "input_tokens": 1500, "output_tokens": 4000}`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **调度幻觉 (Subagent Hallucination)**：严禁使用类似 `Skill tool 执行 Research` 的假命令，必须且只能走原生的 `invoke_subagent`，并正确配置子代理角色数组。
- **路径死锁 (Pathing Deadlock)**：严禁在落盘和遥测时使用已废弃的假变量 `{root}/MEMORY/...`。所有写入操作必须硬锚定到真实的绝对地址 `C:\Users\shich\.gemini\MEMORY\...`。
- **信息伪造 (Data Forgery)**：对于博物馆闭馆日、文物具体放置展厅、古建筑所处朝代，如果没有检索到任何可信证据支撑，系统必须直言“待查实”，严禁发挥大模型幻觉编造历史和地理数据。
