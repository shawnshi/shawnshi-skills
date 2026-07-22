 工具是人类意志的延申。


## 1. Runtime contract

- Codex 只以每个技能目录中的 `SKILL.md` 作为运行真相源。
- 每个技能聚焦一个可描述、可触发、可验证的工作。
- 仓库级规则写在 `AGENTS.md`；技能只保留可复用的专业流程。
- 外部系统能力由真实工具、插件或 MCP 提供。技能不得用散文虚构工具接口。

## 2. Required shape

根目录结构：

```text
skills/
├── <skill-name>/           # 一级用户技能
├── .system/                # Codex 内置技能，不计入用户技能库存
├── scripts/                # 本库门禁、资源索引和共享校验脚本
├── shared/                 # 跨技能协议、Schema 与触发所有权矩阵
├── examples/               # 共享校验样例
└── README.md               # 本文件，库级合同
```

每个一级技能目录必须包含：

```text
skill-name/
├── SKILL.md
├── agents/openai.yaml       # 可选：界面元数据或外部能力声明
├── scripts/                 # 可选：确定性、可重复执行的脚本
├── references/              # 可选：按需读取的领域资料
├── assets/                  # 可选：生成产物使用的模板和素材
└── resource-manifest.json   # 本库门禁使用的资源索引
```

`SKILL.md` 的 frontmatter 只能包含：

```yaml
---
name: skill-name
description: 说明技能做什么，以及用户在什么场景下应使用它。
---
```

约束：

- `name` 必须与目录名一致，只使用小写字母、数字和单连字符，长度不超过 64。
- `description` 必须同时写明能力和触发场景，长度为 1–1024 个字符。
- 不在 frontmatter 中加入 `version`、`tier`、`triggers`、`allowed-tools` 或运行时私有字段。
- 正文使用命令式步骤，写清输入、处理、输出、验证和失败处理。
- 不强制固定章节名。门禁不得因为缺少 `When to Use`、`Workflow`、`Telemetry` 等标题而失败。
- `SKILL.md` 不超过 500 行；大段模板、规范和示例放入 `references/`。
- 所有技能内资源使用相对技能目录的路径引用，避免深层引用链。

## 3. Execution boundaries

- 不要求输出 `<thought>`、`<Thinking>` 或其他内部推理稿。以证据、假设、验证结果和残余风险替代。
- 不硬编码用户目录、`.gemini`、`.kimi`、会话 ID 或 `file:///` 链接。
- 不写入当前 Codex 不存在的工具名。通过自然语言描述所需能力，或在 `agents/openai.yaml` 中声明真实依赖。
- 子代理只在任务可以独立拆分且并行能力可用时采用；必须保留单代理降级路径。
- 联网、安装依赖、控制外部应用、发送消息、发布、合并、删除和永久写入都属于显式授权分支。
- 临时文件放入当前任务可写的临时目录；最终产物写入用户指定或当前工作区的输出位置。
- Vector Lake、MEMORY、日志和用户偏好不默认写入。只有用户明确要求保存或同步时才执行。
- 处理医疗、金融、隐私、凭据和个人数据时，声明数据来源、适用范围、不确定性和升级条件。
- 不承诺 100% 成功、零错误或无法验证的效果。

## 4. Resource and dependency rules

- 优先使用现有脚本；新增脚本必须实际运行代表性测试。
- 外部命令、操作系统、浏览器、桌面应用、Python/Node 包和凭据要求必须在正文的依赖或边界部分写明。
- 不提交 `node_modules`、缓存、日志、临时下载、测试输出或生成音频。
- 不把同一说明同时复制到 `SKILL.md` 和 `references/`。
- `resource-manifest.json` 只记录资源与引用状态，不定义技能语义。

## 5. Skill inventory

当前库存为 49 个用户技能，不包含 `.system`、`scripts`、`shared`、`examples` 和 `reports`。功能说明取自各技能 `SKILL.md` 的当前 `description`。

### Academic and cognitive research

| Skill | 功能说明 |
|---|---|
| `academic-paper-reader` | 深入拆解单篇学术论文，解释研究问题、方法、证据、局限与学术演化位置，并用贯穿案例和必要的机制图降低理解门槛 |
| `academic-scientific-visualization` | 设计、生成和审查可投稿的科学图表，包括多面板布局、误差棒、显著性标注、防色盲编码、期刊尺寸和矢量导出 |
| `automate-github-issues` | 审计、设计或配置 GitHub Issue 分析、任务拆分、冲突检测、代理分派和受控合并流程 |
| `cognitive-book-mirror` | 将书籍或长文重构为“原文主张—个人映射”的伴读分析，在保留作者原意的同时结合用户明确提供并授权使用的个人材料 |
| `cognitive-ceo-review` | 从创始人或经营负责人视角审计战略、产品、项目和架构计划，检验问题定义、资源配置、风险、扩张空间和退出机制 |
| `cognitive-deep-reader` | 深度拆解文章和长文，识别原有共识、核心机制、论证承重墙、认知变化与可执行含义 |
| `cognitive-hv-analysis` | 对公司、产品、技术、政策或社会现象进行纵向演化追踪和横向同期比较，解释关键转折的原因、竞争位置和未来情景 |
| `cognitive-ideation-brainstorming` | 将模糊创意或产品需求收敛为可验证的问题、范围、方案和设计决策 |
| `cognitive-logic-adversary` | 对计划、论证和关键决策执行红队压力测试，识别矛盾、脆弱假设、单点故障和激励错位，并重构为更可防守的方案 |
| `cognitive-morphism-mapper` | 把业务或组织问题抽象为对象、关系和约束，再映射到控制论、生态学、博弈论等成熟领域，借用可验证机制生成跨领域方案 |
| `cognitive-personal-roundtable` | 用彼此有张力的分析视角对复杂议题进行结构化圆桌辩论，呈现冲突、共识、遗漏变量和决策选项 |
| `cognitive-storm-research` | 对复杂、争议或高风险议题开展多来源深度研究，建立事实底座、比较互相冲突的视角、进行红队复核并形成带引用的综合报告 |

### Healthcare strategy

| Skill | 功能说明 |
|---|---|
| `hit-customer-analyst` | 基于可核验公开信息研究医院、卫健行政机构及医疗信息化客户，形成机构画像、采购与项目线索、公开职业角色、厂商格局和拜访准备简报 |
| `hit-digital-strategy-partner` | 为医疗机构、医疗信息化企业和管理团队制定数字化战略、商业模式、投资优先级、ROI/TCO分析及高管决策备忘录 |
| `hit-industry-radar` | 检索并分析指定周期内的医疗信息化、数字健康、医疗AI、监管政策和竞争厂商动态，生成带来源、事件日期、影响判断和行动建议的行业雷达 |
| `hit-lectures-scout` | 检索、筛选和解释医疗AI、数字医疗与临床信息学论文及预印本，按研究类型评估证据质量，并将学术信号转化为可验证的研发、产品或市场假设 |
| `hit-solution-architect` | 设计医疗机构数字化、信创改造、数据平台和临床信息系统方案，覆盖现状诊断、目标架构、迁移路径、互操作、安全合规、容灾及TCO/ROI |
| `hit-weekly-brief` | 汇总并研判指定周期内的数字健康、医疗政策、医疗AI、医疗信息化技术和行业研究，生成面向管理层的带来源周报 |

### Image and system workflows

| Skill | 功能说明 |
|---|---|
| `image-promp-gen` | 将简短主题转化为适合海报、书籍封面、专辑封面、文章配图和社交媒体视觉的平面设计图像提示词，擅长丝网印刷、负空间、象征构图和有限色板 |
| `image-studio-architect` | 使用当前图像生成能力创建或编辑海报、封面、插画、概念图、社交媒体图片和其他视觉资产，并根据输入完整度补足构图、色彩、光线、材质与画幅 |
| `mentat-collaboration-audit` | 基于真实会话记录、日志、工具调用和遥测事件审计系统效率与人机协作摩擦，复算等待、技能载入、错误重试、子代理Token、上下文压缩和写入授权指标 |
| `mentat-dream-cycle` | 以审计、预览和事务化方式检查临时文件、热记忆、失败日志及知识图谱待治理项，生成可执行的清理与归档建议，并在获得明确授权后执行限定范围的安全维护 |
| `mentat-insight-diary` | 将真实发生的系统事件、执行摩擦、失败、权衡和改进动作整理为OODA结构的内观审计日志 |
| `mentat-skill-creator` | 在本地 Codex skills 库中审计、修订、拆分和验证用户技能，落实根 README、资源索引、触发所有权和发布门禁 |

### Personal workflows

| Skill | 功能说明 |
|---|---|
| `personal-cognitive-auditor` | 基于用户提供或明确授权读取的日志、日程与健康数据，生成事实导向的日、周、月或年度复盘，识别承诺偏差、重复模式和可执行改进 |
| `personal-cognitive-prescription` | 从用户提供的近期问题、决策或复盘材料中识别认知盲区，并给出可核验到具体章节的跨领域阅读处方 |
| `personal-diary-writer` | 将用户已经确认的日记、工作记录、生理摘要或复盘内容安全写入用户指定的本地文件 |
| `personal-health-analysis` | 分析用户授权访问的 Garmin 本地数据，生成睡眠、HRV、心率、压力、身体电量、运动负荷和趋势报告 |
| `personal-intelligence-hub` | 对指定主题开展多来源情报扫描、去重、证据核验、情景推演和红队审查，并生成带来源的战略简报 |
| `personal-investment-advisor` | 基于当前行情、公司原始披露、财务数据和用户明确提供的持仓，执行证券身份核验、研究任务约束、方法化筛选、公司研究、估值情景、组合风险审计和结果校准 |
| `personal-musicbee-dj` | 在本地 Windows 电脑上根据歌曲、歌单、流派、场景或情绪请求启动并控制 MusicBee 播放，必要时生成临时 M3U 歌单 |
| `personal-travel-research` | 为城市或地区制作历史、考古、古建筑、博物馆与重点文物的出发前研究资料，并核验当前开放信息 |
| `personal-write-humanizer` | 在不改变事实、业务含义和作者立场的前提下重写中文文本，减少机器化句式、客服口吻、空泛名词和过度排比，恢复自然母语节奏 |
| `personal-writing-assistant` | 起草、重构和深度润色医疗数字化领域的内参、观点文章、政策解读与行业长文，强化论点、证据、临床或管理指标和读者可读性 |

### Meetings and utility workflows

| Skill | 功能说明 |
|---|---|
| `tencent-meeting-mcp` | 通过已安装并授权的腾讯会议 CLI 或本地代理查询会议、成员、录制、转写和智能纪要，并在明确确认后创建、更新或取消会议 |
| `tool-archive-crawler` | 对用户明确指定的历史文件、旧笔记或档案目录进行只读盘点、文本提取、去重、主题归类和可追溯摘要 |
| `tool-blogger-publisher` | 将 Markdown 转换为适合 Google Blogger、微信公众号和邮件订阅系统粘贴或导入的内联样式 HTML 片段，并校验结构、链接、图片和基础安全 |
| `tool-concept-synthesis` | 跨来源梳理概念、实体与关系，形成有证据支撑的体系图和战略长文 |
| `tool-document-summarizer` | 提取医疗信息化、商业方案、招标材料和政策文件的结构化摘要与标签 |
| `tool-drawio` | 将系统架构、流程、数据流、时序、状态和实体关系转换为结构化 JSON 与可验证 SVG |
| `tool-markdown-converter` | 将 PDF、Office、HTML、富文本和杂乱笔记转换为结构清晰的 Markdown |
| `tool-slide-architect` | 设计高管汇报、咨询路演和决策型演示文稿的叙事结构、逐页蓝图与讲稿 |
| `tool-smart-latex` | 将 Markdown 或结构化内容转换为 LaTeX，并在环境允许时编译为 PDF |
| `tool-text-forger` | 在不改变事实和原意的前提下润色、校对和重组现有文本 |
| `tool-tts` | 将用户提供的文本合成为语音并在明确要求时播放 |
| `tool-tuanbiao-downloader` | 从合法公开来源下载、校验并按需合并团体标准或其他标准文件 |
| `tool-url-markdown` | 从公开或用户有权访问的网页提取正文并保存为结构清晰的 Markdown |
| `tool-web-slide` | 将演示文稿内容构建为可在浏览器运行的单页 HTML 幻灯片并进行视觉验证 |
| `tool-youtube-summary` | 从 YouTube 视频、字幕、转录稿或长文中提取论点、证据和结构，并生成摘要、观点矩阵或长文 |

## 6. Trigger ownership

相近技能按产物区分：

- 原创长文：`personal-writing-assistant`
- 忠实润色：`tool-text-forger`
- 去机器腔：`personal-write-humanizer`
- 演示文稿蓝图：`tool-slide-architect`
- 单页网页演示：`tool-web-slide`
- 位图提示词：`image-promp-gen`
- 位图生成或编辑：`image-studio-architect`
- 系统结构图：`tool-drawio`
- 单篇论文：`academic-paper-reader`
- 多源横纵研究：`cognitive-hv-analysis`
- 多视角证据研究：`cognitive-storm-research`
- 医疗文档摘要：`tool-document-summarizer`
- 通用文件转 Markdown：`tool-markdown-converter`

详细所有权由 `shared/trigger-ownership-matrix.json` 维护；其中引用的技能必须真实存在。

## 7. Gate

刷新资源索引：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/generate_resource_manifests.ps1 -Root .
```

运行阻断门禁：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/repair_skills.ps1 -Mode Gate -Root .
```

脚本还支持：

- `-Mode Audit`：只输出检查结果，不写报告。
- `-Mode Report`：在报告目录生成 `skills-audit.json`。
- `-Mode Gate`：发现任一阻断项时返回非零退出码。

门禁必须检查：

- 一级用户技能数与 README 库存一致。
- frontmatter 仅含 `name` 和 `description`。
- 名称、描述、行数和本地引用有效。
- 每个用户技能存在 `resource-manifest.json`，且没有缺失依赖。
- 不存在 `skill.json`。
- 对 `SKILL.md`、脚本、参考资料、配置和界面元数据执行一致检查；不存在旧运行时工具令牌、外部运行时路径、思维稿指令、硬编码模型版本、强制子代理或强制持久化。
- 触发所有权矩阵不存在未知技能和重复信号。

关键失败必须返回非零退出码；报告模式不得代替门禁。

## 8. Maintenance sequence

1. 读取目标技能及其直接引用资源。
2. 以小批次修改 `SKILL.md` 和必要资源。
3. 运行代表性脚本或静态验证。
4. 运行 `scripts/generate_resource_manifests.ps1` 刷新资源索引。
5. 运行 Gate。
6. 对修改过的脚本运行语法检查、代表性正向测试和相关单元测试。
7. 只有验证结果真实变化时，才同步本 README 的库存和基线数字。

禁止在维护流程中重新生成 `skill.json`。旧工具如果仍依赖该文件，应修订或移除该工具，不得恢复双重真相源。

Last updated: 2026-07-22
