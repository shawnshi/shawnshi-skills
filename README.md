工具是人类意志的延伸。


## 1. Runtime contract

- 本目录为当前 Pi 使用的本地技能库；每个技能目录中的 `SKILL.md` 是该技能的入口，执行仍受当前运行时能力与上位指令约束。
- 每个技能聚焦一个可描述、可触发、可验证的工作。
- 执行遵循宿主已加载的指令及适用的仓库 `AGENTS.md`；本地安装目录不一定包含仓库级文件。本 README 只记录库级 Schema、库存和维护说明，不得扩张权限或凌驾上位指令。
- 外部系统能力由真实工具、插件或 MCP 提供。技能不得用散文虚构工具接口。

## 2. Required shape

根目录结构：

```text
skills/
├── <skill-name>/           # 一级用户技能
├── scripts/                # 本库门禁、资源索引和共享校验脚本
├── shared/                 # 活跃的跨模型核验、结构模板与触发所有权矩阵
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

`SKILL.md` 的 frontmatter 至少包含：

```yaml
---
name: skill-name
description: 说明技能做什么，以及用户在什么场景下应使用它。
---
```

约束：

- `name` 必须与目录名一致，只使用小写字母、数字和单连字符，长度不超过 64。
- `description` 必须同时写明能力和触发场景，长度为 1–1024 个字符。
- 可选字段限于 Pi 当前支持的 `license`、`compatibility`、`metadata`、`allowed-tools` 与 `disable-model-invocation`；低频或有外部副作用的手动技能用 `disable-model-invocation: true` 从自动路由提示中隐藏。
- 不加入 `version`、`tier`、`triggers`、`benefits-from` 等未被当前运行时消费的字段；版本等机器契约可放入 `metadata`。
- 正文写清目标、必要上下文、真实边界、可用工具或命令、交付物、验证和失败处理，不规定隐藏推理步骤。
- 不强制固定章节名。门禁不得因为缺少 `When to Use`、`Workflow`、`Telemetry` 等标题而失败。
- `SKILL.md` 不超过 500 行；大段模板、规范和示例放入 `references/`。
- 所有技能内资源使用相对技能目录的路径引用，避免深层引用链。

## 3. Execution boundaries

- 不要求输出 `<thought>`、`<Thinking>` 或其他内部推理稿。以证据、假设、验证结果和残余风险替代。
- 不硬编码用户目录、`.gemini`、`.kimi`、会话 ID 或 `file:///` 链接。
- 不把其他运行时的工具名当作当前可调用接口。通过自然语言描述所需能力，并核对宿主实际暴露的工具；`agents/openai.yaml` 仅在对应消费者支持时生效。
- 子代理只在任务可以独立拆分且并行能力可用时采用；必须保留单代理降级路径。
- 联网、安装依赖、控制外部应用、发送消息、发布、合并、删除和永久写入都属于显式授权分支；只有下表声明的窄化归档合同，才可把对应的生成请求本身视为向封闭档案或状态目标写入的授权。
- 临时文件放入当前任务可写的临时目录；最终产物写入用户指定或当前工作区的输出位置。
- Vector Lake、MEMORY、日志和用户偏好不默认写入。除下表声明的目标外，只有用户明确要求保存或同步时才执行。
- 处理医疗、金融、隐私、凭据和个人数据时，声明数据来源、适用范围、不确定性和升级条件。
- 不承诺 100% 成功、零错误或无法验证的效果。

### 3.1 Declared automatic persistence contracts

普通最终产物仍按上一节写入用户指定位置或当前工作区；下表只治理无需单独“保存”请求就会写入 canonical 档案、历史索引或其他长期状态的例外。每项例外必须同时限定触发请求、封闭目标集合和只读退出条件。未列入此表的技能不得把分析、生成或审计请求解释为长期归档授权；根门禁会拒绝未声明、重复、字段不完整或缺少只读退出边界的合同。

<!-- automatic-persistence-exceptions:start -->
| Skill | 构成写入授权的请求 | 封闭目标集合 | 只读退出条件 |
|---|---|---|---|
| `personal-cognitive-auditor` | 生成当前自然周、月或季度的精确 canonical 个人日志审计请求 | `personal-diary-writer` 权威入口返回的 canonical 季度个人日志内同周期审计区块 | 草稿、预览、只读、不保存、日度、年度、自定义路径或第二处存储 |
| `personal-diary-writer` | 生成通过受保护 `personal-diary-request-v1` 与内容门的完整个人日记，承接 `mentat-insight-diary` 的 canonical Mentat 请求，或承接 `personal-cognitive-auditor` 的当前自然周、月、季度审计请求 | 对应权威入口返回的 canonical 季度个人日志或 canonical Mentat 季度档案 | 草稿、预览、只读、不保存、跨日期复用、自定义路径或第二处存储 |
| `personal-health-analysis` | 明确启用 Garmin 自动同步 | 绑定的 GarminDB 本地数据库、一个当前用户计划任务及单一脱敏运行状态文件 | 仅诊断、预览、试运行、不同步、禁用、移除自动同步或自定义第二处存储 |
| `personal-intelligence-hub` | 生成正式日简报 | 正式新闻文件及新闻目录内的去重索引 | 预览或明确不保存 |
| `hit-weekly-brief` | 生成正式数字健康周报 | DigitalHealthWeeklyBrief 本地归档 | 草稿、预览或明确不保存 |
| `hit-industry-radar` | 生成正式医疗行业雷达 | HealthcareIndustryRadar 本地归档 | 草稿、预览或明确不保存 |
| `hit-lectures-scout` | 生成正式医疗数字化文献侦察报告 | DigitalHealthLecturesScout 本地归档 | 草稿、预览或明确不保存 |
<!-- automatic-persistence-exceptions:end -->

## 4. Resource and dependency rules

- 优先使用现有脚本；新增脚本必须实际运行代表性测试。
- 外部命令、操作系统、浏览器、桌面应用、Python/Node 包和凭据要求必须在正文的依赖或边界部分写明。
- 不提交 `node_modules`、缓存、日志、临时下载、测试输出或生成音频。
- 不把同一说明同时复制到 `SKILL.md` 和 `references/`。
- `resource-manifest.json` 只记录资源与引用状态，不定义技能语义。

## 5. Skill inventory

当前库存为 52 个用户技能，不包含 `.system`、`scripts`、`shared` 和 `reports`。以下为功能摘要，完整触发条件、授权范围和退出边界以对应 `SKILL.md` 为准。

### Academic and cognitive research

| Skill | 功能说明 |
|---|---|
| `academic-paper-reader` | 深入拆解目标学术论文，核验身份与版本，审查方法、数据、关键数字、证据强度、局限及复现条件，并提供页码、章节和表图证据索引 |
| `academic-scientific-visualization` | 设计、生成和审查可投稿的科学图表，包括多面板布局、误差棒、显著性标注、防色盲编码、期刊尺寸和矢量导出 |
| `automate-github-issues` | 审计、设计或配置 GitHub Issue 分析、任务拆分、冲突检测、代理分派和受控合并流程 |
| `cognitive-book-mirror` | 将书籍或长文重构为“原文主张—个人映射”的伴读分析，在保留作者原意的同时结合用户明确提供并授权使用的个人材料 |
| `cognitive-ceo-review` | 从创始人或经营负责人视角审计战略、产品、项目和架构计划，检验问题定义、资源配置、风险、扩张空间和退出机制 |
| `cognitive-deep-reader` | 深度拆解文章和长文，识别原有共识、核心机制、论证承重墙、认知变化与可执行含义 |
| `cognitive-hv-analysis` | 对公司、产品、技术、政策或社会现象进行纵向演化追踪和横向同期比较，解释关键转折的原因、竞争位置和未来情景 |
| `cognitive-ideation-brainstorming` | 将模糊创意或产品需求收敛为可验证的问题、范围、方案和设计决策 |
| `cognitive-logic-adversary` | 对计划、论证和关键决策执行红队压力测试，识别矛盾、脆弱假设、单点故障和激励错位，并重构为更可防守的方案 |
| `cognitive-morphism-mapper` | 把业务或组织问题抽象为对象、关系和约束，再映射到控制论、生态学、博弈论等成熟领域，借用可验证机制生成跨领域方案 |
| `cognitive-personal-roundtable` | 对存在真实取舍的复杂议题开展证据化多视角压力测试，识别事实冲突、底层假设、遗漏变量和可执行决策路径；不替代检索与专业审查 |
| `cognitive-storm-research` | 对复杂、争议或高风险议题开展多来源深度研究，建立事实底座、比较互相冲突的视角、进行红队复核并形成带引用的综合报告 |
| `industry-strategy-analyst` | 以公开且可追溯的证据开展行业与市场研究，形成市场边界、规模、需求、价值链、竞争格局、供应商比较、情景预测、风险和可执行建议 |
| `senior-osint-analyst` | 以合法公开来源开展政策、行业、企业、技术、供应链、地区或重大事件的开源情报研究，执行实体与时效核验、交叉验证和替代假设分析 |

### Healthcare strategy

| Skill | 功能说明 |
|---|---|
| `hit-customer-analyst` | 医疗客户研究与拜访准备的 2.6.2 交付候选，仅用于明确指定候选版本的内部试用、验证或修订；提供会前速览、标准拜访包、战略客户包和一封信四种模式。入口要求常规业务继续使用原 `discovery-call`，该入口不在本库库存内 |
| `hit-digital-strategy-partner` | 为医疗机构或医疗信息化企业开展数字化战略、方案选择、投资排序、可审计 ROI/TCO 和高管决策备忘录；不用于详细技术架构或临床审批 |
| `hit-industry-radar` | 检索并分析指定周期内的医疗信息化、数字健康、医疗AI、监管政策和竞争厂商动态，生成带来源、事件日期、影响判断和行动建议的行业雷达 |
| `hit-lectures-scout` | 检索、筛选和解释医疗AI、数字医疗与临床信息学论文及预印本，按研究类型评估证据质量，并将学术信号转化为可验证的研发、产品或市场假设 |
| `hit-solution-architect` | 设计和评审医疗机构应用、数据、集成、基础设施、安全、容灾、信创迁移及临床 AI 技术方案；业务战略、预算取舍和投资排序转交 `hit-digital-strategy-partner` |
| `hit-weekly-brief` | 汇总并研判指定周期内的数字健康、医疗政策、医疗AI、医疗信息化技术和行业研究，生成面向管理层的带来源周报 |

### Image and system workflows

| Skill | 功能说明 |
|---|---|
| `image-prompt-gen` | 将简短主题或现有视觉要求转化为原创、可执行的平面设计图像提示词，也可在用户明确要求时直接生成或编辑图片 |
| `image-studio-architect` | 使用当前图像生成能力创建或编辑海报、封面、插画、概念图、社交媒体图片和其他视觉资产，并根据输入完整度补足构图、色彩、光线、材质与画幅 |
| `magazine-illustrator` | 为文章、博客、公众号、报告和演示文稿设计并直接生成杂志式位图插画，包括头图、封面、章节插图、系列配图和可复制的图像生成提示词 |
| `mentat-collaboration-audit` | 基于真实会话记录、日志、工具调用和遥测事件审计系统效率与人机协作摩擦，复算等待、技能载入、错误重试、子代理Token、上下文压缩和写入授权指标，并按需生成Markdown报告和HTML审计面板 |
| `mentat-skill-creator` | 仅在用户显式调用时维护当前 Pi 本地技能库的根治理合同、资源清单、触发所有权、批量迁移与发布门禁；通用新技能、无关单技能更新及插件打包不触发 |

### Personal workflows

| Skill | 功能说明 |
|---|---|
| `personal-cognitive-auditor` | 基于授权日志、日历与 Garmin 数据生成日、周、月、季度或年度复盘；个人周、月、季度审计通过校验和结构化请求门后保存到 canonical 季度日志 |
| `personal-cognitive-prescription` | 从用户提供的近期问题、决策或复盘材料中识别认知盲区，并给出可核验到具体章节的跨领域阅读处方 |
| `personal-diary-writer` | 完整个人日记通过受保护请求与内容门后自动保存；承接 Mentat 和个人周、月、季度审计的受保护写入；草稿不保存，当前写入器拒绝非 canonical 路径 |
| `personal-health-analysis` | 以本地优先、失败关闭方式分析用户授权的 Garmin 数据，验证本地数据库读取窗口与设备/固件时期，披露时间范围、缺失和来源，并生成非诊断性报告、离线面板或研究用途 FHIR R4 包装 |
| `personal-intelligence-hub` | 基线优先生成技术与医疗数字化资讯简报，按缺口补检、事件去重、语义评估和独立红队核验来源；正式日简报按声明合同自动保存 |
| `personal-investment-advisor` | 默认使用免费公开来源，结合用户明确提供的持仓，执行证券身份核验、财报研究、估值情景、组合风险审计、主动机会验证和研究复盘；固定为 `research_only`，不生成交易指令 |
| `personal-musicbee-dj` | 在本地 Windows 电脑上根据歌曲、歌单、流派、场景或情绪请求启动并控制 MusicBee 播放，必要时生成临时 M3U 歌单 |
| `personal-travel-research` | 为城市或地区制作历史、考古、古建筑、博物馆与重点文物的出发前研究资料，并核验当前开放信息 |
| `personal-write-humanizer` | 在不改变事实、业务含义和作者立场的前提下重写中文文本，减少机器化句式、客服口吻、空泛名词和过度排比，恢复自然母语节奏 |
| `personal-writing-assistant` | 起草、重构、润色、核验和审校医疗卫生与医疗数字化领域的内参、观点文章、政策解读、案例及白皮书；仅在医疗主题与写作成稿同时成立时使用 |

### Meetings and utility workflows

| Skill | 功能说明 |
|---|---|
| `officecli` | 使用 officecli CLI 创建、分析、校对和修改 DOCX、XLSX 与 PPTX 文档，并检查格式、定位问题、添加图表或执行结构化编辑 |
| `tencent-meeting-mcp` | 通过已安装并授权的腾讯会议 CLI 或本地代理查询会议、成员、录制、转写和智能纪要，并在明确确认后创建、更新或取消会议 |
| `tool-archive-crawler` | 对用户明确指定的历史文件、旧笔记或档案目录进行只读盘点、文本提取、去重、主题归类和可追溯摘要 |
| `tool-blogger-publisher` | 将 Markdown 转换为适合 Google Blogger、微信公众号和邮件订阅系统粘贴或导入的内联样式 HTML 片段，并校验结构、链接、图片和基础安全 |
| `tool-concept-synthesis` | 跨来源梳理概念、实体与关系，形成有证据支撑的体系图和战略长文 |
| `tool-document-summarizer` | 提取医疗信息化、商业方案、招标材料和政策文件的结构化摘要与标签 |
| `technical-diagram-renderer` | 将已确认的系统关系或流程描述规范化为结构化 JSON，并生成经过结构与安全校验的静态 SVG 技术图，按需单向导出基础 `.drawio`/mxGraph 文件 |
| `tool-markdown-converter` | 将 PDF、Office、HTML、富文本和杂乱笔记转换为结构清晰的 Markdown |
| `tool-slide-architect` | 设计高管汇报、咨询路演和决策型演示文稿的叙事结构、逐页蓝图与讲稿 |
| `tool-smart-latex` | 将 Markdown 或结构化内容转换为 LaTeX，并在环境允许时编译为 PDF |
| `tool-text-forger` | 在不改变事实和原意的前提下润色、校对和重组现有文本 |
| `tool-tts` | 将用户提供的文本合成为语音并在明确要求时播放 |
| `tool-tuanbiao-downloader` | 仅下载全国团体标准信息平台公开可访问的 kkfileview 图片型标准并合并为 PDF；需显式调用并提供图片查看链接或已核实的路径 ID，不支持其他站点或普通 PDF 链接 |
| `tool-url-markdown` | 从公开或用户有权访问的网页提取正文并保存为结构清晰的 Markdown |
| `tool-web-slide` | 将演示内容构建为可在浏览器运行、验证和交付的 HTML 幻灯片、离线演示包或单文件 HTML；不用于原生 PPTX 或仅需故事线的任务 |
| `tool-youtube-summary` | 从 YouTube 视频、字幕、转录稿或长文中提取论点、证据和结构，并生成摘要、观点矩阵或长文 |
| `weknora` | 通过 WeKnora REST API 列出知识库、导入文件或 URL、写入 Markdown、跟踪解析状态、浏览与检索知识条目；删除或编辑条目前须逐条确认，凭据由环境提供。本技能为 2026-09-16 从 ClawHub 安装的第三方技能，来源与本地差异见 `weknora/UPSTREAM.md` |

## 6. Trigger ownership

相近技能按产物区分：

- 医疗领域新稿、主张变更、证据/政策判断与发布审校：`personal-writing-assistant`
- 事实定稿后的忠实校对、轻润色、受控重组与压缩：`tool-text-forger`
- 明确去 AI 味/更自然且无需领域判断：`personal-write-humanizer`
- 演示文稿蓝图：`tool-slide-architect`
- 单页网页演示：`tool-web-slide`
- 位图提示词：`image-prompt-gen`
- 位图生成或编辑：`image-studio-architect`
- 系统结构图：`technical-diagram-renderer`
- 单篇论文身份、方法与结果（快速问答按需核验）：`academic-paper-reader`
- 非论文长文论证拆解（非普通摘要/压缩）：`cognitive-deep-reader`
- 视频、字幕与转录内容：`tool-youtube-summary`
- 纵向演化＋横向同期对照：`cognitive-hv-analysis`
- 市场、行业、供应商决策：`industry-strategy-analyst`
- 实体身份、事实、时序与公开材料核查：`senior-osint-analyst`
- 跨证据域、真实争议或冲突的综合研究：`cognitive-storm-research`
- 医疗文档摘要：`tool-document-summarizer`
- 通用文件转 Markdown：`tool-markdown-converter`

详细所有权由 `shared/trigger-ownership-matrix.json` 维护；其中引用的技能必须真实存在。

写作按主任务而非医疗名词分流：纯语言请求不启动完整医疗写作项目；混合请求仅按需组合，不强制串联三个入口。矩阵新增 `faithful_controlled_editing` 表达 S46 的忠实编辑所有权，保留既有类 ID；`secondary_skills` 只表示可选协作，不要求加载。研究入口收窄自动触发，不禁止用户显式要求的合法深研。

Pi 手动入口：`mentat-skill-creator`（显式治理）使用 `disable-model-invocation: true`；`hit-customer-analyst` 现已启用受限自动触发，其 `agents/openai.yaml` 仍声明 `allow_implicit_invocation: true`，两者一致；`image-studio-architect` 原有手动属性不变。其余技能保持原自动/手动属性。

本次 P2 静态修订同步上述路由与手动说明；合成场景和文档检查不代表真实模型选路、图片生成、编译或业务验收。下列历史 Gate/测试记录保持原样，本次不据此声称重跑通过。

## 7. Gate

跨平台单一入口（缺 `pwsh` 或 Python 3 + PyYAML 时失败关闭）：

```sh
sh scripts/gate.sh                    # 全库
sh scripts/gate.sh <skill-name> ...   # 按技能作用域
```

刷新资源索引：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/generate_resource_manifests.ps1 -Root .
```

只检查不写入时增加 `-Check`；局部维护时增加 `-IncludeSkills <skill-name>`，先检查、获授权后再刷新，并用同一范围复检。

严格资源与界面元数据检查需要 Python 3 与 PyYAML；依赖缺失时 Gate 失败关闭，不得静默跳过，安装依赖仍须用户明确授权。

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
- frontmatter 包含 `name` 和 `description`，且可选字段仅使用 Pi 当前支持的集合。
- 名称、描述、行数、估算 token 和本地引用有效。行数与估算 token 双指标均按 `>0` 即失败：`SKILL.md` 默认不得超过 500 行或 8000 估算 token（`-LineThreshold` / `-TokenThreshold`）。
- 每个用户技能存在 schema v3 `resource-manifest.json`；清单字段、规范化哈希、全部受管资源、声明依赖和可移植路径与磁盘一致。
- 可选 `agents/openai.yaml` 必须能安全解析，界面字段、精确 `$skill-name` 默认提示、图标路径、颜色、调用策略和 MCP 依赖类型有效。
- 可选 `agents/openai.yaml` 必须能安全解析，界面字段、精确 `$skill-name` 默认提示、图标路径、颜色、调用策略和 MCP 依赖类型有效；调用策略与 `SKILL.md` 的 `disable-model-invocation` 不得互相矛盾。仅声明一侧时以 `OpenAiPolicyWarnings` 非阻断警告报告，不代替技能所有者决定路由。
- 对 `SKILL.md`、脚本、参考资料、配置和界面元数据执行一致检查；不存在旧运行时工具令牌、外部运行时路径、思维稿指令、硬编码模型版本、强制子代理或强制持久化。
- `_runtime`、`.venv`、`node_modules`、`__pycache__` 与构建输出目录属于用户运行产物或依赖副本，不进入源码一致性扫描，也不得被当作技能资源或业务事实。因此技能内自带虚拟环境不会产生误判。
- 触发所有权矩阵不存在未知技能和重复信号。

关键失败必须返回非零退出码；报告模式不得代替门禁。

## 8. Maintenance sequence

1. 读取目标技能及其直接引用资源。
2. 以小批次修改 `SKILL.md` 和必要资源。
3. 运行代表性脚本或静态验证。
4. 先用 `scripts/generate_resource_manifests.ps1 -Check` 检查资源索引；`scripts/gate.sh` 封装了同一组检查及下列步骤。
5. 对修改过的脚本运行语法检查、代表性正向测试和相关单元测试。改动 `scripts/` 下门禁脚本本身会使 `mentat-skill-creator/resource-manifest.json` 过期（它记录了所声明依赖的脚本哈希），所以顺序是先改脚本、最后重新生成该 manifest、再跑门禁。
6. 只有验证结果真实变化时，才同步本 README 的库存和基线数字。

### 8.1 Current validation (2026-09-24)

环境：Windows 主机；`pwsh`（PowerShell Core）；Python 3.13 + PyYAML。

- 全库 `sh scripts/gate.sh` 通过。`repair_skills.ps1 -Mode Gate` 的 28 类阻断项全为 0，退出码 0：`InventoryMismatch=False`（声明 52、实际 52）、`FrontmatterFailures=0`、`OversizedSkills=0`、`OversizedByEstimatedTokens=0`（最大估算 6600）、`MissingResourceManifests=0`、`InvalidResourceManifests=0`、`ManifestDependencyIssues=0`、`OpenAiMetadataFailures=0`、`ValidatorIntegrationFailures=0`、`DeprecatedToolSkills=0`、`ForeignRuntimeSkills=0`、`ReasoningDirectiveSkills=0`、`HardcodedModelSkills=0`、`SkillJsonFiles=0`、`NodeModulesDirectories=0`、`TriggerOwnershipClasses=19`、`TriggerOwnershipConflicts=0`。
- 非阻断项：`OpenAiPolicyWarnings=3`（`industry-strategy-analyst`、`personal-health-analysis`、`senior-osint-analyst` 的 `agents/openai.yaml` 关闭隐式调用，但 `SKILL.md` 未声明 `disable-model-invocation`，因此本宿主仍会自动触发）。属路由决策，待技能所有者确认后再改任一侧。
- 测试：`python -m pytest scripts -q` 在**本地安装目录**运行 102 项通过、67 项子测试通过。同一命令在**独立克隆**中为 90 项通过、13 项失败，且这 13 项在同步前的 `HEAD` 清洁工作树上以完全相同的集合复现：`scripts/test_autonomy_contracts.py` 从 `AGENT = SKILLS.parent` 读 `pai/*` 契约文件，而该路径只在安装库旁边存在，故发布副本内不可能通过。“发布副本 Gate 通过”因此仅在 `repair_skills.ps1 -Mode Gate` 与资源清单两层成立，不含该测试层；本节旧文句中的无限定“102 项通过”仅在安装目录可复现。
- 本轮同步（2026-09-26，`fca6940e`）：从安装库同步 118 个文件的内容变更并新增 `scripts/gate.sh`、`mentat-skill-creator/references/host-routing-eval.md`；`resource-manifest.json` 由发布副本按自身实际文件重新生成，不沿用安装库版本。同步不删除发布副本独有文件。
  - `academic-paper-reader`：复现就绪度卡片成为门禁强制槽位（标题 + 四个维度，缺一则具名报错），模板补 YAML frontmatter、数字并入带 E-ID 的证据索引、新增消融归因与负向边界，参考示例重写为新结构，避免样例继续教旧结构。
  - 刻意未发布：`gws-auth-keeper`（安装库独有的新技能，未进库存表，且正文写死 `C:/Users/shich`，违反本 README 第 3 节“不硬编码用户目录”）。发布它属另一项治理决定。
  - 刻意不删除：`weknora`（发布副本存在且本 README 已声明，安装库缺失——按安装缺口处理，不按退役处理；“同步”不蕴含删除已发布的第三方内容）。
  - 排除项：`.ruff_cache`、`__pycache__`、`.pytest_cache`、`.skill_state`、`.deepxiv-draft-*`、`output/`、`garmin-output/`、`scripts/tmp/`、`NUL`。
- 资源清单：52 个技能各一份 schema v3 manifest，`-Check` 报过期 0。
- 修复项（本轮）：
  - 恢复丢失的 `scripts/validate_openai_yaml.py` 及其测试；同步 `scripts/resource_manifest.py` 与 `scripts/test_resource_manifest.py` 的 Lua 换行归一化修复。修复前 `repair_skills.ps1` 会在 `validator_integration_failures` 上恒失败，19 份 `agents/openai.yaml` 处于无校验状态。
  - 为 52 个技能补齐 `resource-manifest.json`（此前仅 2 份，缺失 39 份）。
  - 修正 `Get-SkillTextCorpus`：它未跳过 `.venv` 等依赖目录，导致 `personal-health-analysis` 的虚拟环境被当作技能正文扫描，误报 `deprecated_tool_skills=1`；同时使全库门禁耗时从数分钟降到约 7 秒。
  - 新增估算 token 指标（`CharCount`、`EstimatedTokens`、`OversizedByEstimatedTokens`、`MaxEstimatedTokens`、`-TokenThreshold`）；纯行数口径看不出一份 85 行、每行 118 字节的中文正文。
  - 新增调用策略一致性检查：`disable-model-invocation` 与 `allow_implicit_invocation` 矛盾时阻断，仅声明一侧时警告。
  - 新增 `scripts/gate.sh`，使门禁有可被第三方复现的跨平台入口。
  - `mentat-skill-creator`：夹具从 8 条扩到 12 条并标明宿主表面（`pi` 用 `/skill:` 入口，`codex-openai` 用 `$<skill>`）；新增 `references/host-routing-eval.md` 定义宿主路由与档位评测的责任人、判据和运行记录格式；`SKILL.md` 增加门禁判定表，并按维护豁免把基线制品降为按需。
  - 独立修复（与本轮修改无关的既有漂移）：`scripts/test_autonomy_contracts.py` 的 `a02` 断言沿用 `pai/coding.md` 改词前的字面串，自 2026-09-24 起失败；已改为当前子句 `验收集合内存在不可归因的失败测试`。同步注意：该契约现允许可归因的既有失败单列披露，与 §10 既有段落一致。
- 未运行：宿主级路由与档位评测（本宿主未配置上游档位，夹具只证明合同完整）；`scripts/gate.sh` 的 POSIX 分支仅在 Windows Git Bash 下验证，未在 Linux/macOS 实测。
- 声明：上述结果只证明静态合同、资源一致性与单元测试通过，不代表所有技能已在新会话中端到端验证。

### 8.2 Historical validation (2026-09-22)

- 本次同步 `personal-intelligence-hub`、`hit-industry-radar`、`personal-investment-advisor` 三个技能的本地安装副本漂移，共 48 个文件（+661/−193 行）。同步排除缓存、虚拟环境、运行产物、草稿与 `.skill_state`，并排除 `resource-manifest.json`（由发布副本重新生成）；文件按 LF 字节表示写入，未引入换行改写，也未删除发布副本独有文件。
- `personal-intelligence-hub`：日期证据层新增两条确定性规则。`standalone-dateline/1` 读取整行完整日期（`YYYY年M月D日`、`YYYY-MM-DD`、`Month D, YYYY`，可带 `, H:MM AM/PM` 与 UTC/GMT 后缀，容忍对称强调包裹），仅扫描正文前 1500 字节，且要求上一非空行是短标签行、之前不出现 ≥120 字符段落；`cn-wire-dateline/1` 读取无年份中文电讯日期（如`央广网北京9月17日消息`），年份只取自 URL 路径中唯一一个完整日期，并与正文月、日逐项比对，报告窗口不参与年份推断，无锚点或多锚点冲突时整条作废。补检父级收口 `supplement_finalization_grace_seconds` 由 300 秒提高到 900 秒，上限常量化 `article_broker.MAX_FINALIZATION_GRACE_SECONDS = 3600`，worker `timeout_ms` 仍按 `max_duration_seconds + grace_seconds` 推导。arXiv 提交历史一致性守卫保持严格：v1 提交月必须等于编号月，与编号或年份不一致的页面继续判为冲突证据，不修补日期。
- 本地安装副本验证：改动影响面 796 项测试 / 100 子测试通过（含 8 条新增日期规则回归，以及把 grace 相关断言改为按 packet 推导）；真实封存正文回放（同一 run 的 14 份 body proof，只读）中可解析日期由 3 份增至 7 份，窗口内由 1 份增至 5 份。
- 发布副本验证：`scripts/resource_manifest.py generate/check` → 检查 52 个技能、重写 3 个、过期 0；受影响技能快速子集 537 项测试 / 29 子测试通过；`personal-investment-advisor` 技能级测试 48 项通过；全部改动 Python 文件字节编译通过；全库 `scripts/` 测试 85 项通过、13 项失败，同一失败集合在 HEAD 的清洁工作树内复现，属既有失败，本次同步未新增失败。
- 限制：发布副本未重跑 `personal-intelligence-hub` 的耗时用例（`test_native_article_evidence.py` 两处内容一致，仅在本地安装副本运行 107 项）；`hit-industry-radar` 无技能级测试。上述结果只证明静态合同、资源一致性与单元测试行为，不代表真实模型选路的端到端验收。

### 8.3 Historical validation (2026-09-19)

- 本次同步 `tool-smart-latex`（P0–P2 修复）。模板改为按单一 `cjk` 开关分流语言：中文用 CTeX 方案与中文标签，英文用 `scheme=plain`、类基线行距与左对齐。补齐 Pandoc 前置（`\passthrough`、`\newcounter{none}`、`secnumdepth`、`\pandocbounded`、`CSLReferences`），修复此前已存在的结构性失败：Markdown 表格在 5 个预设中的 4 个必然编译失败、`tech_report` 行内代码失败、任意图片在所有预设失败；`academic` 清除 `newtxtext` 向 xeCJK 泄漏的 `Extension=.otf`；新增 `twocol_table.lua`（双栏表格）与 `div_boxes.lua`（fenced div 到 tcolorbox）两个过滤器。
- 修复副本与本地运行副本同源：13 个技能文件的 Git blob 哈希与运行时副本逐字节一致；两个新过滤器在索引与工作区均为 LF。
- 本地验证（TeX Live 2026、Pandoc 3.8.3、Windows CTeX 字体）：`tool-smart-latex` 42 项测试 / 94 个子测试通过（含 5 个样式的端到端真实编译）；引擎矩阵 30/30 组合退出码 0、有 PDF、无 LaTeX 错误；编译后实测英文正文行距 120.0–124.2%（合同 120–145%）、行长 60–90 字符（合同 45–90）。发布副本内重跑同一套件同为 42 项 / 94 子测试通过。
- 仓库工具：清单生成器增加 `.lua` 换行归一化覆盖并附回归测试（`scripts/test_resource_manifest.py` 29 项 / 24 子测试通过）；用 CRLF/LF 往返验证 `.lua` 哈希不再随检出的换行设置变化。
- 全库资源清单刷新：检查 52 个技能，重写 6 个、未变 46 个。重写的 6 个为 `cognitive-morphism-mapper`（`examples/.gitkeep`）、`mentat-collaboration-audit`（`resources/.gitkeep`）、`officecli`（`LICENSE`、`NOTICE`）、`personal-investment-advisor`（`resources/.gitkeep`）、`technical-diagram-renderer`（`LICENSE`）、`tool-url-markdown`（`bun.lock`）：这 6 项是更早提交改动文件后未刷新清单造成的记录滞后，记录哈希与磁盘既非原始字节也不匹配 LF 归一化，且工作区无换行差异，不是换行伪影；文件本身未在本轮修改。刷新后全库清单检查过期数为 0。
- 全库 `repair_skills.ps1 -Mode Gate` 通过：52 个技能、7 项自动持久化例外、19 类触发所有权，阻断项为 0。
- 上述结果只证明静态合同、资源一致性与已记录的编译行为，不代表面向真实模型选路的端到端验收，也不代替逐页视觉验收：本轮未对最终 PDF 做逐页人工/多模态版面检查。

### 8.4 Historical validation (2026-09-09)

- 按本地一级 `SKILL.md` 盘点为 51 个技能；`mentat-dream-cycle`、`mentat-insight-diary` 当前不在本目录，已从库存表移除。
- 自动持久化例外表保留 7 项现存技能合同；移除缺失技能的独立条目，不改变其他技能入口中已有的受保护写入边界。
- 已清理 `shared/trigger-ownership-matrix.json` 中对缺失技能 `mentat-insight-diary` 的 3 处引用：移除其独占触发类别及两处辅助技能引用，不把相关请求转派给其他技能。触发所有权由 19 类调整为 18 类。
- 全库 `repair_skills.ps1 -Mode Gate` 通过：51 个技能、7 项自动持久化例外、18 类触发所有权，阻断项为 0。此结果仅证明静态合同与资源一致性，不代表所有技能已在新会话中端到端验证。
- 本地安装目录不含 `.git`；源码发布目标为 [shawnshi/shawnshi-skills](https://github.com/shawnshi/shawnshi-skills) 的 `main` 分支，通过独立 Git 工作副本同步，排除缓存、运行产物及敏感信息。发布副本按实际文件和 Git 字节表示生成资源清单，不保留空目录或运行日志的清单条目。
- 发布副本全库 Gate 通过。测试分别在适用环境运行：本地安装目录根测试 94 项通过；日记测试运行 63 项，跳过 4 项缺少已移除 Mentat 技能的可选集成，其余通过；发布副本资讯测试运行 337 项，跳过 1 项，其余通过。发布副本单独复验日记写入器 36 项，跳过相同 4 项，其余通过。
- 新增缺失 Mentat 证据门时拒绝写入且不创建目标目录的回归测试，未放宽生产写入门。依赖宿主目录布局的根合同及日记入口测试在本地安装目录验证，不将独立克隆中的路径不匹配写成代码通过。

### 8.5 Historical validation (2026-09-07)

- 本次全库 `repair_skills.ps1 -Mode Gate` 通过：53 个技能，8 项自动持久化例外，19 类触发所有权，阻断项为 0。
- 资源索引独立检查：53 个技能，过期或缺失清单为 0；界面元数据独立检查：19 份配置，错误为 0。
- 本次修复 `hit-customer-analyst` 的三项发布阻塞：生成缺失的资源清单，将默认提示中的技能标识改为 `$hit-customer-analyst`，移除校验器不接受的 `policy.products` 字段；未放宽校验规则或改变客户研究业务逻辑。
- `hit-customer-analyst` 仍为交付候选；静态门禁通过不改变其限定内部试用状态，真实发布验收以该技能的 `references/release-acceptance.md` 为准。
- Gate 只证明其覆盖的静态合同与资源一致性，不代表所有技能已在新会话中端到端验证，也不代替发布前的敏感信息检查。

### 8.6 Historical baseline (2026-09-05)

- 此前记录：全库 Gate 通过，53 个技能、8 项自动持久化例外、19 类触发所有权，阻断项为 0。
- 此前记录：`mentat-insight-diary/scripts/test_skill_contract.py` 的 14 项测试通过；本次未重跑该回归。

Last updated: 2026-09-24
