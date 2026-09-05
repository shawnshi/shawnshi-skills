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
| `mentat-insight-diary` | 生成、更新、记录或写 Mentat 日志，且取证完成、证据门允许保存 | 权威入口返回的 canonical 季度档案 | 草稿、预览、分析、审计技能、不保存、来源未就绪、来源读取失败或证据不足 |
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
- `resource-manifest.json` 只记录资源与引用状态，不定义技能语义。当前 schema v3 使用 LF 规范化 SHA-256 校验 `SKILL.md`、顶层文件、全部受管资源文件和明确引用，并拒绝绝对路径、根外路径与磁盘不一致。

## 5. Skill inventory

当前库存为 53 个用户技能，不包含 `.system`、`scripts`、`shared` 和 `reports`。以下为功能摘要，完整触发条件、授权范围和退出边界以对应 `SKILL.md` 为准。

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
| `industry-strategy-analyst` | 以公开且可追溯的证据开展行业与市场研究，形成市场边界、规模、需求、价值链、竞争格局、供应商比较、情景预测、风险和可执行建议 |
| `senior-osint-analyst` | 以合法公开来源开展政策、行业、企业、技术、供应链、地区或重大事件的开源情报研究，执行实体与时效核验、交叉验证和替代假设分析 |

### Healthcare strategy

| Skill | 功能说明 |
|---|---|
| `hit-customer-analyst` | 面向医疗卫生信息化售前开展重点客户研究与重要拜访准备，提供会前速览、标准拜访包、战略客户包和一封信四种模式；不用于一般机构介绍或私人背景调查 |
| `hit-digital-strategy-partner` | 为医疗机构、医疗信息化企业和管理团队制定数字化战略、商业模式、投资优先级、ROI/TCO分析及高管决策备忘录 |
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
| `mentat-dream-cycle` | 以审计、预览和事务化方式检查临时文件、热记忆、失败日志及知识图谱待治理项，生成可执行的清理与归档建议，并在获得明确授权后执行限定范围的安全维护 |
| `mentat-insight-diary` | 先核查日期与授权来源，区分未取证、读取失败和检查后无事件；证据门通过后生成八段 OODA 日志并原子保存到权威季度档案，不默认扫描全部历史会话 |
| `mentat-skill-creator` | 显式维护本地 Codex skills 库的根治理合同、资源清单、触发所有权、批量迁移和发布门禁；通用新技能与可安装插件分别转交系统 creator |

### Personal workflows

| Skill | 功能说明 |
|---|---|
| `personal-cognitive-auditor` | 基于授权日志、日历与 Garmin 数据生成日、周、月、季度或年度复盘；个人周、月、季度审计通过校验和结构化请求门后保存到 canonical 季度日志 |
| `personal-cognitive-prescription` | 从用户提供的近期问题、决策或复盘材料中识别认知盲区，并给出可核验到具体章节的跨领域阅读处方 |
| `personal-diary-writer` | 完整个人日记通过受保护请求与内容门后自动保存；承接 Mentat 和个人周、月、季度审计的受保护写入，草稿或非标准路径仍执行确认门 |
| `personal-health-analysis` | 以本地优先、失败关闭方式分析用户授权的 Garmin 数据，验证本地数据库读取窗口与设备/固件时期，披露时间范围、缺失和来源，并生成非诊断性报告、离线面板或研究用途 FHIR R4 包装 |
| `personal-intelligence-hub` | 对指定主题开展多来源情报扫描、去重、证据核验、情景推演和红队审查，并生成带来源的战略简报 |
| `personal-investment-advisor` | 执行点时财务筛选、结构化预期差与三情景估值、持仓及行情身份审计、实时行情刷新与离线 Daily Sync 评估、组合情景压测、只读逆波动率分配实验和研究校准；固定为 `research_only` |
| `personal-musicbee-dj` | 在本地 Windows 电脑上根据歌曲、歌单、流派、场景或情绪请求启动并控制 MusicBee 播放，必要时生成临时 M3U 歌单 |
| `personal-travel-research` | 为城市或地区制作历史、考古、古建筑、博物馆与重点文物的出发前研究资料，并核验当前开放信息 |
| `personal-write-humanizer` | 在不改变事实、业务含义和作者立场的前提下重写中文文本，减少机器化句式、客服口吻、空泛名词和过度排比，恢复自然母语节奏 |
| `personal-writing-assistant` | 起草、重构和深度润色医疗数字化领域的内参、观点文章、政策解读与行业长文，强化论点、证据、临床或管理指标和读者可读性 |

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
- 位图提示词：`image-prompt-gen`
- 位图生成或编辑：`image-studio-architect`
- 系统结构图：`technical-diagram-renderer`
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
- 名称、描述、行数和本地引用有效。
- 每个用户技能存在 schema v3 `resource-manifest.json`；清单字段、规范化哈希、全部受管资源、声明依赖和可移植路径与磁盘一致。
- 可选 `agents/openai.yaml` 必须能安全解析，界面字段、精确 `$skill-name` 默认提示、图标路径、颜色、调用策略和 MCP 依赖类型有效。
- 不存在 `skill.json`。
- 对 `SKILL.md`、脚本、参考资料、配置和界面元数据执行一致检查；不存在旧运行时工具令牌、外部运行时路径、思维稿指令、硬编码模型版本、强制子代理或强制持久化。
- `_runtime` 目录属于用户运行产物，不进入源码一致性扫描，也不得被当作技能资源或业务事实。
- 触发所有权矩阵不存在未知技能和重复信号。

关键失败必须返回非零退出码；报告模式不得代替门禁。

## 8. Maintenance sequence

1. 读取目标技能及其直接引用资源。
2. 以小批次修改 `SKILL.md` 和必要资源。
3. 运行代表性脚本或静态验证。
4. 先用 `scripts/generate_resource_manifests.ps1 -Check` 检查资源索引；在授权范围内仅刷新真实过期的技能，再复检无时间戳漂移。
5. 先运行选中技能 Gate；涉及根治理、共享资源或批量迁移时再运行全库 Gate。
6. 对修改过的脚本运行语法检查、代表性正向测试和相关单元测试。
7. 只有验证结果真实变化时，才同步本 README 的库存和基线数字。

禁止在维护流程中重新生成 `skill.json`。旧工具如果仍依赖该文件，应修订或移除该工具，不得恢复双重真相源。

### 8.1 Verified baseline (2026-09-05)

- 全库 `repair_skills.ps1 -Mode Gate`：53 个技能，8 项自动持久化例外，19 类触发所有权；阻断项为 0。
- Mentat 定向回归：`mentat-insight-diary/scripts/test_skill_contract.py` 的 14 项测试通过。
- Gate 只证明其覆盖的静态合同与资源一致性，不代表所有技能已在新会话中端到端验证，也不代替发布前的敏感信息检查。

Last updated: 2026-09-05
