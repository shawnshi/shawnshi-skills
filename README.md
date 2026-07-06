# Skills Ecosystem: The Strategic Armory (V11.0 - Director Architecture)

<!-- 
@Pos: Root Level / Knowledge Sovereign 
@Vision: A fractal, battle-hardened ecosystem of specialized intelligence tools.
@Purpose: Extending the Strategic Architect's reach from raw data ingestion to high-fidelity executive delivery.
@Maintenance: All modules are optimized via 'Fable 5 Checkpoints' and guarded by 'Sandbox Isolation' under Director V11.0.
-->

> **“工具的本质是意志的延伸。在这里，我们不生产简单的功能，我们构建拥有物理穿透力与图谱记忆的自主智能体集群。”**

## 1. 架构原则 (Architectural Principles)
本目录遵循最新的 **V11 Director Architecture** 架构范式，彻底废弃了过去的线性执行链与静态模板，全面拥抱并发编排、隔离沙盒与系统级知识持久化：

### A. 架构定义：7层代理模型 (The 7-Layer Class)
所有的技能已被重构为独立的自主智能体（Agent），彻底推平了旧版 `<strategy-gene>` 的松散八段式模板。每一个 `SKILL.md` 必须严丝合缝地实现以下 7 层微服务防线：
1. **Identity**: 身份映射与角色认同。
2. **Mission**: 核心使命与目标锁定。
3. **Workflow**: 状态机流转与任务执行链。
4. **Deliverables**: 输出制品与交付契约。
5. **Guardrails**: 防爆红线与沙盒物理隔离。
6. **Metrics**: 质量评估与成功度量。
7. **Voice**: 发声通道与冷酷基调。

### B. 执行引擎：兵团编排与断点门控 (Orchestration & Gatekeeping)
- **并发编排 (Subagent Orchestration)**：废除主代理单线程瞎编的幻觉风险，强制使用 `invoke_subagent` 派遣专职的 `research`、`adversary` 等子代理执行 Map-Reduce 数据脱水与红队对战。
- **物理断点 (Fable 5 Checkpoints)**：引入绝对拦截机制。在进行高危落盘、执行昂贵 API 或提交高管战略前，必须强制向人类指挥官呈现黑板草稿并请求 `[APPROVE]`，严禁先斩后奏。
- **物理沙盒 (Sandbox Isolation)**：杜绝污染全局 `config/` 目录。所有的侦察JSON、中间草稿、Python探针脚本，必须强制被软禁在当前会话隔离的 `<appDataDir>\brain\<conversation-id>\scratch\` 空间。

### C. 记忆中枢：图谱入湖 (Vector Lake Registry)
- **终结失忆症**：废除传统的本地 `MEMORY/` 碎片化读写。所有经过红蓝对抗和 Fable 5 质检的高价值实体、架构经验与张力边（`tension_edges`），必须通过 `invoke_subagent` 拉起专职 Ingestor，并调用 `vector-lake-mcp` （如 `prepare_ingest_batch`）执行绝对异步的 Fire-and-forget 知识图谱入湖。

## 2. 标准结构 (Standard Skill Shape)
新建或重构技能时，必须完全对齐 **V11 Director Architecture 规范**。
任何依旧包含旧版 `<strategy-gene>` 游离章节的技能，将被雷达判定为“架构漂移”并标记为待清剿的系统级技术债。

## 3. 核心分类矩阵 (Core Skill Hierarchy)

> **Total Inventory: 50 Strategic Modules across 8 Domains**

### 🧠 深度认知与研究工作台 (Cognitive Research)
*底层思考工具箱：需求脱水、战略审计、红蓝对抗与情报分析。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[cognitive-book-mirror](cognitive-book-mirror/)** | **认知书籍镜像引擎 (V11 Architecture)**。提取书籍原旨并与近 14 天日记碰撞，生成毒舌双栏伴读。 |
| **[cognitive-ideation-brainstorming](cognitive-ideation-brainstorming/)** | **高压想法脱水机 (V11 Architecture)**。统一收口宏观点子拷问，执行逻辑压力测试。 |
| **[cognitive-ceo-review](cognitive-ceo-review/)** | **创始人模式战略审计 (V11 Architecture)**。聚合批处理模式下对开发计划执行核能挑战。 |
| **[cognitive-logic-adversary](cognitive-logic-adversary/)** | **逻辑对抗系统 (V11 Architecture)**。通过饱和逻辑攻击搜索单点故障 (SPOF)。 |
| **[cognitive-personal-roundtable](cognitive-personal-roundtable/)** | **高密度动态圆桌 (V11 Architecture)**。张力网络构建，碎片化落盘防截断。 |
| **[cognitive-hv-analysis](cognitive-hv-analysis/)** | **横纵分析法深度研究 (V11 Architecture)**。纵轴时间深度，横轴同期对比。 |
| **[cognitive-deep-reader](cognitive-deep-reader/)** | **认知深潜引擎 (V11 Architecture)**。冷热双轨路由：结构抽骨架 或 滤镜榨取剧本。 |
| **[cognitive-morphism-mapper](cognitive-morphism-mapper/)** | **范畴论跨界思维引擎 (V11 Architecture)**。异构领域生成突破性解法。 |
| **[cognitive-storm-research](cognitive-storm-research/)** | **重型并发调研管线 (V11 Architecture)**。5并发子代消除偏见，高密度映射盲区。 |

### 🏥 大健康与战略研判中枢 (Healthcare Strategy)
*聚焦垂直主业：医疗信息化 (HIT)、临床决策支持及大客户分析。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[hit-solution-architect](hit-solution-architect/)** | **顶级方案架构师 (V11 Architecture)**。执行多阶段落盘锻造，确保 TCO 最优与技术可演进。 |
| **[hit-digital-strategy-partner](hit-digital-strategy-partner/)** | **顶级医疗数字化战略专家 (V11 Architecture)**。ROI 测算与战区黑板状态机。 |
| **[hit-industry-radar](hit-industry-radar/)** | **行业战略雷达 (V11 Architecture)**。并发监控友商动态与四维战报。 |
| **[hit-weekly-brief](hit-weekly-brief/)** | **行业战区研报中枢 (V11 Architecture)**。智库研报降维与非共识张力捕获。 |
| **[hit-lectures-scout](hit-lectures-scout/)** | **数字化前沿侦察兵 (V11 Architecture)**。学术信号 RWE 过滤与科研战报。 |
| **[hit-customer-analyst](hit-customer-analyst/)** | **大客户拜访分析专家 (V11 Architecture)**。多管线机构与足迹侦察。 |

### 🔬 专业科研与学术评价 (Scientific Research)
*学术重型武器：论文检索、读论文提炼、系统性打分与论文级绘图。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[academic-paper-reader](academic-paper-reader/)** | **学术论文深度研读 (V11 Architecture)**。剥离黑话，知识降阶。 |
| **[academic-scientific-visualization](academic-scientific-visualization/)** | **科研级绘图指引 (V11 Architecture)**。支持 Nature 级多面板视觉。 |

### 📝 内容创作与出版引擎 (Content Creation)
*高密度叙事锻造：专栏写作、风格迁移与出版级排版。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[image-promp-gen](image-promp-gen/)** | **大师级提示词引擎 (V11 Architecture)**。视觉资产炼金。 |
| **[image-studio-architect](image-studio-architect/)** | **端到端视觉资产工厂 (V11 Architecture)**。模糊意图全自动炼金或严守零干预物理直出。 |
| **[tool-slide-architect](tool-slide-architect/)** | **战略级幻灯片蓝图构建师 (V11 Architecture)**。标题即判词，禁用名词标签。 |
| **[tool-web-slide](tool-web-slide/)** | **电子杂志风网页 PPT 引擎 (V11 Architecture)**。HTML 单文件演示资产。 |
| **[tool-smart-latex](tool-smart-latex/)** | **自动化出版 LaTeX 引擎 (V11 Architecture)**。IEEE/CV 工业级排版。 |
| **[tool-drawio](tool-drawio/)** | **SVG 架构渲染仪 (V11 Architecture)**。纯 Python List 原生防爆注入与 UML 挂载。 |
| **[tool-text-forger](tool-text-forger/)** | **文字锻造师 (V11 Architecture)**。三重淬炼与意图锚定，强制呈现前后对比洞察。 |
| **[tool-blogger-publisher](tool-blogger-publisher/)** | **工业级 HTML 排版引擎 (V11 Architecture)**。内联防御性样式，内置思维链与优雅降级。 |

### 💼 商业洞察与投资顾问 (Marketing & Finance)
*二级市场分析与商业价值变现。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[personal-investment-advisor](personal-investment-advisor/)** | **顶级金融量化引擎 (V11 Architecture)**。并发调用伯克希尔辛迪加大师会诊。 |

### 👤 数字原生个体成长中心 (Personal Management)
*个人生活审计、生理分析、旅行研究与生活方式控制。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[personal-diary-writer](personal-diary-writer/)** | **个人日志原子写入器 (V11 Architecture)**。负责高频日常状态录入。 |
| **[personal-cognitive-auditor](personal-cognitive-auditor/)** | **战略认知联合审计官 (V11 Architecture)**。日/周/月认知复盘，强制调度。 |
| **[personal-cognitive-prescription](personal-cognitive-prescription/)** | **认知处方引擎 (V11 Architecture)**。无情的认知盲区开方器。 |
| **[personal-health-analysis](personal-health-analysis/)** | **首席医疗官 (CMO) 引擎 (V11 Architecture)**。Garmin 生理数据审计。 |
| **[personal-musicbee-dj](personal-musicbee-dj/)** | **音乐极客控制协议 (V11 Architecture)**。JIT 算法精准控制本地 MusicBee 进程。 |
| **[personal-travel-research](personal-travel-research/)** | **旅行深度研判 (V11 Architecture)**。多代理并发的文化与案头准备。 |
| **[personal-writing-assistant](personal-writing-assistant/)** | **思维淬炼与写作引擎 (V11 Architecture)**。同行视角找核，消灭 AI 塑料词。 |
| **[personal-write-humanizer](personal-write-humanizer/)** | **中文“去 AI 化”锻造场 (V11 Architecture)**。动词驱动与影子草稿协议。 |
| **[personal-intelligence-hub](personal-intelligence-hub/)** | **个人情报作战中枢 (V11 Architecture)**。全球多源抓取，降维噪音。 |

### ⚙️ 技术全栈、逆向工程与系统演化 (Tech & System Evolution)
*工作流编排、技能创建、算力监控与系统级演化。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[mentat-skill-creator](mentat-skill-creator/)** | **技能工厂与自愈中心 (V11 Architecture)**。生命周期管控与 Director 标准化生成。 |
| **[mentat-insight-diary](mentat-insight-diary/)** | **内观日记与逻辑审计 (V11 Architecture)**。OODA 反思自动物理归档。 |
| **[mentat-collaboration-audit](mentat-collaboration-audit/)** | **系统与协作联合审计管线 (V11 Architecture)**。统一收口摩擦损耗诊断。 |
| **[mentat-dream-cycle](mentat-dream-cycle/)** | **系统静默清洗与演化管线 (V11 Architecture)**。清扫沙盒，孤岛扫描。 |

### 🧰 全能格式转换与数据工厂 (Utilities Format)
*负责标准化格式转换与数据原质提取。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[tencent-meeting-mcp](tencent-meeting-mcp/)** | **腾讯会议 CLI/MCP 服务**。底层采用 tmeet 引擎，通过游标分页强制控制会议录制与纪要搜寻。 |
| **[tool-document-summarizer](tool-document-summarizer/)** | **医疗文档战略情报引擎 (V11 Architecture)**。本体驱动的精确语义压榨。 |
| **[tool-markdown-converter](tool-markdown-converter/)** | **Markdown 原质炼金术 (V11 Architecture)**。异构文件 MarkItDown 标准化转换。 |
| **[tool-tts](tool-tts/)** | **高保真导演级播报系统 (V11 Architecture)**。多角色 Audio Tags 控制与双轨降级。 |
| **[tool-tuanbiao-downloader](tool-tuanbiao-downloader/)** | **团体标准下载器 (V11 Architecture)**。PDF 自动解析合并装订。 |
| **[tool-url-markdown](tool-url-markdown/)** | **CDP 网页原质提取器 (V11 Architecture)**。JS 强对抗与断点防穿模。 |
| **[tool-youtube-summary](tool-youtube-summary/)** | **深度知识同构引擎 (V11 Architecture)**。YouTube 与长文核心提取、降噪落盘。 |
| **[tool-concept-synthesis](tool-concept-synthesis/)** | **宏观缝合与体系全景图 (V11 Architecture)**。依赖图谱寻找孤立实体逻辑暗线。 |
| **[tool-archive-crawler](tool-archive-crawler/)** | **数字废墟矿工 (V11 Architecture)**。翻新非结构化旧库锚定进图谱。 |

*Last Global Audit: 2026-07-06 | Version: 11.0.0 (Director Architecture) | System State: 100% V11 Covered & Locked*
