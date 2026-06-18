# Skills Ecosystem: The Strategic Armory (V9.0 - Swarm & Routing Edition)

<!-- 
@Pos: Root Level / Knowledge Sovereign 
@Vision: A fractal, battle-hardened ecosystem of specialized intelligence tools.
@Purpose: Extending the Strategic Architect's reach from raw data ingestion to high-fidelity executive delivery.
@Maintenance: All modules are optimized via 'trigger-trap' logic and guarded by 'Absolute Schema Defense' under GEP V4.0.
-->

> **“工具的本质是意志的延伸。在这里，我们不生产简单的功能，我们构建确定性。”**

## 1. 架构原则 (Architectural Principles)
本目录遵循 GEP V4.0 “四层壳模型”与 Antigravity Native 架构范式，实现**代码液态化**与**业务语义固态化**的动态平衡：

### A. 物理层：绝对沙盒直控 (Physics)
- **绝对物理地址**：彻底废弃 `{SKILL_DIR}`、`{WORKSPACE}`、`{root}` 等一切易引发沙盒解析坍塌的伪变量宏。所有的脚本寻址与文件落盘，必须硬编码为带有驱动器盘符的绝对路径（如 `C:\Users\shich\.gemini\config\skills\...`）。
- **Native 工具合规**：废除 `run_shell_command` 与 `write_file`。全面切入抗死锁的 `run_command` 与 `write_to_file`。
- **环境安全锁**：所有调用本地 Python 的进程，强制在同一命令栈内前置挂载 `$env:PYTHONIOENCODING="utf-8"`，彻底杜绝跨平台中文字符集引发的进程截断。

### B. 逻辑层：GEP V4.0 纪律约束 (Logic)
- **架构压缩**：彻底推平旧时代的松散八段式模板（如 Workflow, Resources, Telemetry 等）。
- 所有的 `SKILL.md` 必须严丝合缝地凝练入以下三大装甲防线：
  1. `## 1. 核心流程与架构 (The Protocol)`：执行路径与断点控制。
  2. `## 2. <Contracts> (输出与交付契约)`：不容妥协的质量底线、语义映射与美学原则。
  3. `## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)`：枚举并阻断所有的沙盒塌陷点、系统幻觉与行为越轨。

### C. 执行层：负熵交互与 OODA 闭环 (Execution)
- **脑暴倾倒 + 断点门控**：采用高带宽初始输入 + 幽灵骨架（Ghost Deck / Shadow Draft）进行断点阻击，未获人类批准前严禁进行不可逆的生成消耗。
- **降维图谱探针**：所有的核心推演动作，在动笔前必须通过 `call_mcp_tool` 探查 `vector-lake-mcp` 以获取商业真相与图谱实体，严禁依靠大模型权重凭空瞎编。

### D. 进化层：自愈能力与证据网 (Evolution)
- **失效先验**：将曾经导致任务溃败的代码报错与死锁幻觉，打入 `<Failure_Taxonomy>` 作为系统级免疫记忆。
- **证据网 (Evidence-Mesh)**：分析类资产必须执行物理归档，将其使用 `write_to_file` 永久写入 `MEMORY` 或本地知识图谱。

## 2. 标准结构 (Standard Skill Shape)
新建或重构技能时，必须完全对齐 **GEP V4.0**。旧版 `repair_skills.ps1` 中的 6 段式验证将被弃用，新结构强制校验以下三块核心板：

1. `## 1. 核心流程与架构`
2. `## 2. <Contracts>`
3. `## 3. <Failure_Taxonomy>`

任何依旧包含 `## Telemetry`、`## Workflow` 游离章节的技能，将被雷达判定为“架构漂移”并标记为待清剿的遗留废料。

## 3. 核心分类矩阵 (Core Skill Hierarchy)

> **Total Inventory: 47 Strategic Modules across 8 Domains**

### 🧠 深度认知与研究工作台 (Cognitive Research)
*底层思考工具箱：需求脱水、战略审计、红蓝对抗与情报分析。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[cognitive-book-mirror](cognitive-book-mirror/)** | **认知书籍镜像引擎 (Native Edition)**。提取书籍原旨并与近 14 天日记碰撞，生成毒舌双栏伴读。 |
| **[cognitive-ideation-brainstorming](cognitive-ideation-brainstorming/)** | **高压想法脱水机 (Native Edition)**。统一收口宏观点子拷问，执行逻辑压力测试。 |
| **[cognitive-ceo-review](cognitive-ceo-review/)** | **创始人模式战略审计**。聚合批处理模式下对开发计划执行核能挑战。 |
| **[cognitive-logic-adversary](cognitive-logic-adversary/)** | **逻辑对抗系统 (Native Edition)**。通过饱和逻辑攻击搜索单点故障 (SPOF)。 |
| **[personal-intelligence-hub](personal-intelligence-hub/)** | **个人情报作战中枢 (Native Edition)**。全球多源抓取，降维噪音。 |
| **[cognitive-personal-roundtable](cognitive-personal-roundtable/)** | **高密度动态圆桌**。张力网络构建，碎片化落盘防截断。 |
| **[cognitive-hv-analysis](cognitive-hv-analysis/)** | **横纵分析法深度研究**。纵轴时间深度，横轴同期对比。 |
| **[cognitive-deep-reader](cognitive-deep-reader/)** | **认知深潜引擎 (V9.0)**。冷热双轨路由：结构抽骨架 或 滤镜榨取剧本。 |
| **[tool-concept-synthesis](tool-concept-synthesis/)** | **宏观缝合与体系全景图**。依赖图谱寻找孤立实体逻辑暗线。 |
| **[tool-archive-crawler](tool-archive-crawler/)** | **数字废墟矿工**。翻新非结构化旧库锚定进 Tier 2 图谱。 |
| **[cognitive-morphism-mapper](cognitive-morphism-mapper/)** | **范畴论跨界思维引擎**。异构领域生成突破性解法。 |
| **[cognitive-storm-research](cognitive-storm-research/)** | **斯坦福 STORM 调研引擎 (Agent Swarm Edition)**。5并发子代消除偏见，高密度映射盲区。 |

### 🏥 大健康与战略研判中枢 (Healthcare Strategy)
*聚焦垂直主业：医疗信息化 (HIT)、临床决策支持及大客户分析。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[hit-intelligence-hub](hit-intelligence-hub/)** | **情报指挥中枢 (Swarm Commander)**。最高级 orchestrator，并发拉起并缝合雷达、智库与学术三大战区情报。 |
| **[hit-solution-architect](hit-solution-architect/)** | **顶级方案架构师 (Native Edition)**。执行多阶段落盘锻造，确保 TCO 最优与技术可演进。 |
| **[hit-digital-strategy-partner](hit-digital-strategy-partner/)** | **顶级医疗数字化战略专家**。ROI 测算与战略验证。 |
| **[hit-industry-radar](hit-industry-radar/)** | **行业战略雷达 (Native Edition)**。监控友商动态与 S-T-C 战报。 |
| **[hit-weekly-brief](hit-weekly-brief/)** | **行业战区研报中枢 (Native Edition)**。智库研报降维。 |
| **[hit-lectures-scout](hit-lectures-scout/)** | **数字化前沿侦察兵 (Native Edition)**。RWE 过滤与科研战报。 |
| **[hit-customer-analyst](hit-customer-analyst/)** | **大客户拜访分析专家 (Native Edition)**。机构与足迹的三阶侦察。 |

### 🔬 专业科研与学术评价 (Scientific Research)
*学术重型武器：论文检索、读论文提炼、系统性打分与论文级绘图。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[academic-paper-reader](academic-paper-reader/)** | **学术论文深度研读**。剥离黑话，知识降阶。 |
| **[academic-scientific-visualization](academic-scientific-visualization/)** | **科研级绘图指引**。支持 Nature 级多面板视觉。 |

### 📝 内容创作与出版引擎 (Content Creation)
*高密度叙事锻造：专栏写作、风格迁移与出版级排版。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[personal-writing-assistant](personal-writing-assistant/)** | **思维淬炼与写作引擎 (Native Edition)**。同行视角找核，消灭 AI 塑料词。 |
| **[personal-write-humanizer](personal-write-humanizer/)** | **中文“去 AI 化”锻造场 (Native Edition)**。动词驱动与影子草稿协议。 |
| **[image-studio-architect](image-nano-gen/)** | **端到端视觉资产工厂 (V9.0)**。模糊意图全自动炼金或严守零干预物理直出。 |
| **[tool-slide-architect](tool-slide-architect/)** | **战略级幻灯片蓝图构建师 (Native Edition)**。标题即判词，禁用名词标签。 |
| **[tool-web-slide](tool-web-slide/)** | **电子杂志风网页 PPT 引擎 (Native Edition)**。HTML 单文件演示资产。 |
| **[tool-smart-latex](tool-smart-latex/)** | **自动化出版 LaTeX 引擎**。IEEE/CV 工业级排版。 |
| **[tool-drawio](tool-drawio/)** | **SVG 架构渲染仪 (Native Edition)**。纯 Python List 原生防爆注入与 UML 挂载。 |

### 💼 商业洞察与投资顾问 (Marketing & Finance)
*二级市场分析与商业价值变现。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[personal-investment-advisor](personal-investment-advisor/)** | **顶级金融量化引擎**。提供结构化 JSON 仪表盘，严禁通用对话解答。 |

### 👤 数字原生个体成长中心 (Personal Management)
*个人生活审计、生理分析、旅行研究与生活方式控制。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[personal-diary-writer](personal-diary-writer/)** | **个人日志原子写入器**。负责高频日常状态录入。 |
| **[personal-cognitive-auditor](personal-cognitive-auditor/)** | **战略认知联合审计官**。日/周/月认知复盘，强制调度。 |
| **[personal-cognitive-prescription](personal-cognitive-prescription/)** | **认知处方引擎**。无情的认知盲区开方器。 |
| **[personal-health-analysis](personal-health-analysis/)** | **首席医疗官 (CMO) 引擎 (Native Edition)**。Garmin 生理数据审计。 |
| **[personal-musicbee-dj](personal-musicbee-dj/)** | **音乐极客控制协议**。JIT 算法精准控制本地 MusicBee 进程。 |
| **[personal-travel-research](personal-travel-research/)** | **旅行深度研判**。博物馆与文化考古案头准备。 |

### ⚙️ 技术全栈、逆向工程与系统演化 (Tech & System Evolution)
*工作流编排、技能创建、算力监控与系统级演化。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[mentat-skill-creator](mentat-skill-creator/)** | **技能工厂与自愈中心 (Native Edition)**。生命周期管控与 GEP V4.0 标准化生成。 |
| **[mentat-insight-diary](mentat-insight-diary/)** | **内观日记与逻辑审计**。OODA 反思自动物理归档。 |
| **[mentat-collaboration-audit](mentat-collaboration-audit/)** | **系统与协作联合审计管线 (Native Edition)**。统一收口摩擦损耗诊断。 |
| **[mentat-dream-cycle](mentat-dream-cycle/)** | **系统静默清洗与演化管线**。清扫沙盒，孤岛扫描。 |

### 🧰 全能格式转换与数据工厂 (Utilities Format)
*负责标准化格式转换与数据原质提取。*

| 技能标识 (Directory) | 核心本质 (Trigger Traps) |
| :--- | :--- |
| **[tencent-meeting-mcp](tencent-meeting-mcp/)** | **腾讯会议 MCP 服务**。会议调度、录制转写搜索。 |
| **[tool-document-summarizer](tool-document-summarizer/)** | **医疗文档战略情报引擎**。本体驱动的精确语义压榨。 |
| **[tool-markdown-converter](tool-markdown-converter/)** | **Markdown 原质炼金术**。异构文件 MarkItDown 标准化转换。 |
| **[tool-tts](tool-tts/)** | **高保真导演级播报系统 (Native Edition)**。多角色 Audio Tags 控制与双轨降级。 |
| **[tool-tuanbiao-downloader](tool-tuanbiao-downloader/)** | **团体标准下载器**。PDF 自动解析合并装订。 |
| **[tool-url-markdown](tool-url-markdown/)** | **CDP 网页原质提取器 (Native Edition)**。JS 强对抗与断点防穿模。 |

---
*Last Global Audit: 2026-06-18 | Version: 9.0.0 (Swarm & Routing Edition) | System State: Locked*
