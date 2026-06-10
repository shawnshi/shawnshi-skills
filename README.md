# Skills Ecosystem: The Strategic Armory (V8.0 - Antigravity Post-Surgery Edition)

<!-- 
@Pos: Root Level / Knowledge Sovereign 
@Vision: A fractal, battle-hardened ecosystem of specialized intelligence tools.
@Purpose: Extending the Strategic Architect's reach from raw data ingestion to high-fidelity executive delivery.
@Maintenance: All modules are optimized via V8.0 'BasePipelineOrchestrator' logic and guarded by 'Absolute Schema Defense'.
-->

> **“工具的本质是意志的延伸。在这里，硅基注意力被我们锻造为了冷酷的自动化流水线。”**

## 1. 架构原则 (Architectural Principles V8.0)
本目录现已全面升级为 **V8.0 Antigravity 纯逻辑引擎标准**，彻底消灭了旧时代大模型并发拉起子代理导致的 I/O 灾难与认知坍缩：

### A. 物理层：并发防御与算力隔离 (Physics)
- **封杀手动 Subagent I/O**：彻底废除大模型跨进程拉起子代理并争抢写入 `tmp/` 文件的行为。所有复杂的多步推演，全部下沉至 `scripts/run_*.py` 引擎内执行内存级光速流转。
- **Mime 免疫与 UTF-8 编码锁**：强制声明 `$env:PYTHONIOENCODING="utf-8"`，所有落盘中间文件严格携带 `.md` 或 `.json` 后缀以穿透底层拦截。

### B. 逻辑层：微角色圆桌与人格剥离 (Micro-Persona Isolation)
- **粉碎缝合怪 (Monolithic Collapse)**：禁止让单个大模型在同一会话中同时扮演“爬虫+架构师+精算师”。
- **True Persona Isolation**：重型技能（如战略伙伴、行业雷达、圆桌映射）全部被切片为独立的微角色流水线。每个微角色（如“悲观精算师”、“数据清洗员”）均享有 100% 独立的 LLM 调用算力，保证绝对的认知锋芒。

### C. 执行层：ReAct 义体感官外挂 (Execution & Sensory)
- **解开感官剥夺**：底层的 `BasePipelineOrchestrator` 现已内置 ReAct (Reasoning and Acting) 工具循环。
- **按需赋权**：流水线中的微角色可自主调用 `Search_Web`、`Fetch_URL_Content`、`Query_Vector_Lake` 工具进行实时自证，打破了纯文本推演的闭塞性。

### D. 进化层：全自动睡眠演化 (Autonomous Dream Cycle)
- **后台驻留 (Cron Automaton)**：彻底告别人工清扫。系统依靠 `schedule` 工具在每天凌晨静默唤醒。
- **闭环自愈 (Self-Healing)**：在睡梦中自动查重入湖 (Vector Lake Dedup)、扫描失败日志，并在底层直接跨进程触发大模型重写修复自己崩溃的 Python 代码。

## 2. 安装与部署 (Deployment)
```bash
# 全库安装
gemini skills install https://github.com/shawnshi/shawnshi-skills.git

# 特定技能精准安装（示例：hit-solution-architect）
gemini skills install https://github.com/shawnshi/shawnshi-skills.git --path hit-solution-architect
```

## 2.5 静态审计门禁 (Static Audit Gate)
在修改任何 `SKILL.md`、`scripts/`、`references/`、`assets/` 后，先刷新资源清单，再执行静态门禁。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\generate_resource_manifests.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\repair_skills.ps1 -Mode Gate
```

## 3. 核心分类矩阵 (Core Skill Hierarchy)

> **Total Inventory: 48 Strategic Modules across 8 Domains**

### 🧠 深度认知与研究工作台 (Cognitive Research)
*底层思考工具箱：需求脱水、战略审计、红蓝对抗与情报分析。*

| 技能标识 (Directory)                                                      | 核心本质 (Trigger Traps)                                                                                                                             |
|:--------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------|
| **[cognitive-personal-roundtable](cognitive-personal-roundtable/)**       | **高密度动态圆桌 (V8.0 Native)**。基于 Python Orchestrator 实现的真·人格算力隔离引擎，消除大模型精分效应。                                           |
| **[cognitive-morphism-mapper](cognitive-morphism-mapper/)**               | **范畴论跨界思维引擎 (V8.0 Native)**。利用异构领域结构生成突破性解法，经 5 层理论检验的降维打击管线。                                                |
| **[personal-intelligence-hub](personal-intelligence-hub/)**               | **个人情报作战中枢 (V8.0 Native)**。执行全球多源抓取，带查重与证据锚点的决策资产。                                                                   |
| **[cognitive-book-mirror](cognitive-book-mirror/)**                       | **认知书籍镜像引擎**。提取书籍原旨并强行与最近 14 天日记价值观碰撞，生成毒舌双栏伴读。                                                               |
| **[cognitive-ideation-brainstorming](cognitive-ideation-brainstorming/)** | **高压想法脱水机**。宏观商业点子拷问与微观架构选型，执行逻辑压力测试。                                                                               |
| **[cognitive-logic-adversary](cognitive-logic-adversary/)**               | **逻辑对抗系统**。搜索单点故障 (SPOF)，通过饱和逻辑攻击验证方案鲁棒性。                                                                              |

### 🏥 大健康与战略研判中枢 (Healthcare Strategy)
*聚焦垂直主业：医疗信息化 (HIT)、临床决策支持及大客户分析。*

| 技能标识 (Directory)                                              | 核心本质 (Trigger Traps)                                                                                     |
|:------------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------|
| **[hit-solution-architect](hit-solution-architect/)**             | **顶级方案架构师 (V8.0 Atomized)**。拆解为 5 级微角色圆桌管线，TCO 最优与红队防线。                          |
| **[hit-digital-strategy-partner](hit-digital-strategy-partner/)** | **顶级医疗数字化战略专家 (V8.0 Atomized)**。拆解为政策推演、悲观精算、极右风控等独立角色流水线。             |
| **[hit-industry-radar](hit-industry-radar/)**                     | **行业战略雷达 (V8.0 Atomized)**。包含“数据清洗员”与“供应链侦探”的无情竞对扫描仪。                           |
| **[hit-weekly-brief](hit-weekly-brief/)**                         | **行业战区研报中枢 (V8.0 Atomized)**。龙虾架构管线，具备“反共识黑天鹅分析师”。                               |
| **[hit-lectures-scout](hit-lectures-scout/)**                     | **数字化前沿侦察兵 (V8.0 Atomized)**。临床证据网过滤与硬核技术架构萃取。                                     |

### 🔬 专业科研与学术评价 (Scientific Research)
*学术重型武器：论文检索、系统性打分与论文级绘图。*

| 技能标识 (Directory)                                                        | 核心本质 (Trigger Traps)                                                                            |
|:----------------------------------------------------------------------------|:----------------------------------------------------------------------------------------------------|
| **[academic-paper-writer](academic-paper-writer/)**                         | **学术论文写作管线 (V2.4)**。12-Agent 管线，支持 IMRaD 与双语摘要，强制 APA 7.0 / LaTeX 出版级排版. |
| **[academic-paper-reader](academic-paper-reader/)**                         | **读论文 (academic-paper-reader)**。猎取思想，将别人的发现拆解成自己能用的认知，拒绝学术腔.         |
| **[academic-scientific-visualization](academic-scientific-visualization/)** | **论文级科研绘图与可视化**。生成符合 Nature/Science 规格图表，支持多面板布局、显著性标注.           |
| **[academic-deep-research](academic-deep-research/)**                       | **通用深度研究中枢 (V2.3)**。13-Agent 管线，支援 PRISMA 系統性回顧与嚴格的證據查核 (RoB).           |

### 📝 内容创作与出版引擎 (Content Creation)
*高密度叙事锻造：专栏写作、风格迁移与出版级排版。*

| 技能标识 (Directory)                                          | 核心本质 (Trigger Traps)                                                                                                       |
|:--------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------------------------|
| **[personal-writing-assistant](personal-writing-assistant/)** | **思维淬炼与写作引擎**。同行对话姿态，强制“找核”审计，带降级与乒乓共创模式的深度原创管线.                                                      |
| **[personal-write-humanizer](personal-write-humanizer/)**     | **中文文本“去 AI 化”锻造场**。引入术语硬锁、结构粉碎与影子草稿协议，执行极度物理级去塑料化重塑.                                                        |
| **[tool-slide-architect](tool-slide-architect/)**             | **战略级 PPT 架构师**。交付具备原生逻辑的 PPT 资产蓝图，拒绝平庸模板.                                                              |
| **[tool-drawio](tool-drawio/)**                               | **企业级图表工程引擎**。内置语义化配色系统(7色)、5种图表类型专用规则(架构/流程/时序/ER/甘特). |

### 💼 商业洞察与投资顾问 (Marketing & Finance)

| 技能标识 (Directory)                                            | 核心本质 (Trigger Traps)                                                         |
|:----------------------------------------------------------------|:---------------------------------------------------------------------------------|
| **[personal-investment-advisor](personal-investment-advisor/)** | **顶级金融量化引擎**。提供结构化量化 JSON 分析与 K 线周期解析。 (附带 16:00 定时数据获取器) |

### 👤 数字原生个体成长中心 (Personal Management)

| 技能标识 (Directory)                                          | 核心本质 (Trigger Traps)                                                               |
|:--------------------------------------------------------------|:---------------------------------------------------------------------------------------|
| **[personal-diary-writer](personal-diary-writer/)**           | **个人日志原子写入器**。负责高频轻量级的日常状态录入与安全落盘，强绑定物理 I/O 组件.   |
| **[personal-cognitive-auditor](personal-cognitive-auditor/)** | **战略认知联合审计官**。处理日/周/月/年结认知复盘，强制调度多源数据，交接 Writer 落盘. |
| **[personal-health-analysis](personal-health-analysis/)**     | **首席医疗官 (CMO) 引擎 (V8.0 Native)**。对 Garmin 生理数据执行全链路审计，管理决策准备度.           |

### ⚙️ 技术全栈、逆向工程与系统演化 (Tech & System Evolution)

| 技能标识 (Directory)                                          | 核心本质 (Trigger Traps)                                                                                                     |
|:--------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------|
| **[mentat-dream-cycle](mentat-dream-cycle/)**                 | **系统静默演化管线 (V8.0 Autonomous)**。凌晨 3 点 Cron 触发，跨进程拉起自愈引擎，自动清理孤岛与查重合并热缓存。|
| **[mentat-skill-creator](mentat-skill-creator/)**             | **技能工厂与自愈中心 (Native Edition)**。管理技能生命周期，受 Dream Cycle 后台调度以覆盖损坏代码。                               |
| **[mentat-collaboration-audit](mentat-collaboration-audit/)** | **系统与协作联合审计管线 (Native Edition)**。统一收口系统底层算力损耗与人机协作摩擦。 |

---
*Last Global Audit: 2026-06-11 | Version: 8.0 (Antigravity Post-Surgery Edition) | System State: Locked*
