# Skills Ecosystem: The Strategic Armory (V5.2 - Anti-Entropy Edition)

<!-- 
@Pos: Root Level / Knowledge Sovereign 
@Vision: A fractal, battle-hardened ecosystem of specialized intelligence tools.
@Purpose: Extending the Strategic Architect's reach from raw data ingestion to high-fidelity executive delivery.
@Maintenance: All modules are optimized via 'trigger-trap' logic and guarded by 'Absolute Schema Defense'.
-->

> **“工具的本质是意志的延伸。在这里，我们不生产简单的功能，我们构建确定性。”**

## 1. 架构原则 (Architectural Principles)
本目录遵循“四层壳模型”支撑下的技能范式，实现**代码液态化**与**业务语义固态化**的动态平衡：

### A. 物理层：算力主权与环境隔离 (Physics)
- **物理硬锁**：所有技能必须在本地物理目录内闭环执行，严禁依赖外部云端黑盒.
- **路径归一化**：强制统一路径风格，确保 Windows/Unix 环境下的逻辑同态.

### B. 逻辑层：语义主权与 MSL 约束 (Logic)
- **MSL 原子化**：业务逻辑必须封装为原子化 Skill。代码是液态消费品，语义协议是固态资产.
- **Schema 绝对防御**：[Template] 标记的输出必须 100% 同态映射，严禁执行摘要式逻辑脱水.
- **语义守恒**：允许实现路径突变，但核心业务语义必须在重构前后保持恒定.

### C. 执行层：负熵交互与 OODA 闭环 (Execution)
- **脑暴倾倒 + 查漏补缺**：废除串行审讯，采用高带宽初始输入 + 静默映射 + 聚合追问模式.
- **聚合批处理**：在评审任务中整合决策节点，最大化保护用户心流，实现极致的交互负熵.
- **Markdown 原生可视化**：强制使用 Mermaid 进行架构描述，弃用不稳定的 UI 截图.

### D. 进化层：自愈能力与证据网 (Evolution)
- **失效先验 (Gotchas)**：将重复性失败硬编码为 SKILL.md 顶部的禁令，实现系统的对抗性进化.
- **沙箱门控 (Unit-Test Gate)**：任何技能修改在落盘前，必须在临时沙箱执行测试，失败即回滚防退化.
- **细胞分裂 (Utility-Driven Fission)**：基于雷达测算，当技能 `Gotchas` 堆积超载时强制执行架构分裂.
- **负样本打底 (Hard Negatives Logging)**：遥测错选路由数据，为未来的行为对齐路由 (InfoNCE) 奠定物理底座.
- **证据网 (Evidence-Mesh)**：分析类资产必须强制执行物理归档，严禁仅保留在瞬时对话历史中.
- **量化反思**：通过 `skill_utility_radar.py` 监控系统熵增，以数据驱动系统拓扑的持续优化.

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

门禁命中以下任一条件即返回非零退出码：

- frontmatter 非法
- 缺少 `name` 或 `description`
- 缺少 `resource-manifest.json`
- manifest 中声明了不存在的本地依赖
- `SKILL.md` 中存在缺失的本地引用
- 存在不兼容工具令牌
- 存在外部运行时硬编码路径
- `SKILL.md` 超过行数阈值

若只想查看明细，不拦截：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\repair_skills.ps1 -Mode Report
```

## 2.6 标准结构 (Standard Skill Shape)
新建或重构技能时，优先对齐 [shared/skill-structure-template.md](shared/skill-structure-template.md)。

推荐章节顺序：

1. `## When to Use`
2. `## Workflow`
3. `## Resources`
4. `## Failure Modes`
5. `## Output Contract`
6. `## Telemetry`

`repair_skills.ps1` 会在报告中标出缺失这些标准章节的技能，作为结构漂移指标。

## 2.7 触发主权矩阵 (Trigger Ownership)
高重叠域的主触发权不再只靠口头约定，统一收敛到 [shared/trigger-ownership-matrix.json](shared/trigger-ownership-matrix.json)。

当前重点治理 4 个高碰撞域：

- `research`
- `writing`
- `healthcare_strategy`
- `personal_analysis`

规则：

- 每个请求类只允许 `1` 个 `primary_skill`
- `secondary_skills` 只能做补充，不得夺主
- `request_signals` 在矩阵内不得跨类重复

`repair_skills.ps1` 现在会校验该矩阵是否存在、引用的技能是否真实存在、以及信号是否发生跨类重叠，并在报告中输出冲突计数。

## 3. 核心分类矩阵 (Core Skill Hierarchy)

> **Total Inventory: 45 Strategic Modules across 8 Domains**

### 🧠 深度认知与研究工作台 (Cognitive Research)
*底层思考工具箱：需求脱水、战略审计、红蓝对抗与情报分析。*

| 技能标识 (Directory)                                        | 核心本质 (Trigger Traps)                                                                                              |
|:------------------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------|
| **[office-hours](office-hours/)**                           | **战略架构师与需求脱水 (Native Edition)**。通过“脑暴倾倒+查漏补缺”模式，执行 6 个高压问题进行战略脱水，输出设计文档. |
| **[plan-ceo-review](plan-ceo-review/)**                     | **创始人模式战略审计 (Native Edition)**。采用“聚合批处理”模式对开发计划执行核能挑战，支持范围扩张、择优或缩减.       |
| **[personal-brainstorming](personal-brainstorming/)**                         | **创意与架构设计专家 (Native Edition)**。在任何开发行为前强制调用，将模糊意图转化为具体的设计规范与验证方案.         |
| **[personal-logic-adversary](personal-logic-adversary/)**                     | **逻辑对抗系统 (Native Edition)**。搜索单点故障 (SPOF)，通过饱和逻辑攻击验证方案鲁棒性.                              |
| **[personal-intelligence-hub](personal-intelligence-hub/)** | **个人情报作战中枢 (Native Edition)**。执行全球多源抓取，将噪音降维为 Alpha 级决策资产.                              |
| **[personal-roundtable](personal-roundtable/)** | **高密度动态圆桌 (V4.0)**。基于议题构建张力网络，采用“碎片化落盘与最终合并”机制，彻底消除大模型长文本截断风险. |
| **[hv-analysis](hv-analysis/)** | **横纵分析法深度研究 (Horizontal-Vertical Analysis)**。由数字生命卡兹克提出，通过纵轴追踪时间深度，横轴进行同期对比，最后产出排版精美的深度研究报告. |

### 🏥 大健康与战略研判中枢 (Healthcare Strategy)
*聚焦垂直主业：医疗信息化 (HIT)、临床决策支持及大客户分析。*

| 技能标识 (Directory)                                              | 核心本质 (Trigger Traps)                                                            |
|:------------------------------------------------------------------|:------------------------------------------------------------------------------------|
| **[hit-solution-architect](hit-solution-architect/)**             | **顶级方案架构师 (V7.0)**。执行多阶段落盘锻造，确保 TCO 最优与技术可演进.          |
| **[hit-digital-strategy-partner](hit-digital-strategy-partner/)** | **顶级数字化战略专家 (V15.1)**。执行 ROI 测算、MBB 框架分析与动词驱动的叙事.       |
| **[hit-industry-radar](hit-industry-radar/)**                     | **行业战略雷达**。监控卫宁动态、友商中标及 Epic/Cerner 异动，输出 S-T-C 战报.      |
| **[hit-weekly-brief](hit-weekly-brief/)**                         | **行业战区研报中枢 (V5.0)**。将智库研报与白皮书降维为高管视角的抗幻觉决策资产.     |
| **[hit-lectures-scout](hit-lectures-scout/)**                     | **数字化前沿侦察兵 (V5.0)**。基于多智能体并发与龙虾架构重构，执行 SemHash 去重与 RWE 过滤，输出实战科研战报. |
| **[hit-customer-analyst](hit-customer-analyst/)**                 | **大客户拜访分析专家 (V3.1)**。强制执行三阶侦察（人物、机构、足迹），输出实战策略. |

### 🔬 专业科研与学术评价 (Scientific Research)
*学术重型武器：论文检索、读论文提炼、系统性打分与论文级绘图。*

| 技能标识 (Directory)                                            | 核心本质 (Trigger Traps)                                                                             |
|:----------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------|
| **[academic-paper-writer](academic-paper-writer/)**             | **学术论文写作管线 (V2.4)**。12-Agent 管线，支持 IMRaD 与双语摘要，强制 APA 7.0 / LaTeX 出版级排版. |
| **[academic-paper-reader](academic-paper-reader/)**             | **读论文 (academic-paper-reader)**。猎取思想，将别人的发现拆解成自己能用的认知，拒绝学术腔.         |
| **[academic-scientific-visualization](academic-scientific-visualization/)** | **论文级科研绘图与可视化**。生成符合 Nature/Science 规格图表，支持多面板布局、显著性标注. |
| **[academic-deep-research](academic-deep-research/)**                         | **通用深度研究中枢 (V2.3)**。13-Agent 管线，支援 PRISMA 系統性回顧与嚴格的證據查核 (RoB).            |

### 📝 内容创作与出版引擎 (Content Creation)
*高密度叙事锻造：专栏写作、风格迁移与出版级排版。*

| 技能标识 (Directory)                                          | 核心本质 (Trigger Traps)                                                   |
|:--------------------------------------------------------------|:---------------------------------------------------------------------------|
| **[personal-writing-assistant](personal-writing-assistant/)** | **统一内容锻造场**。内置高管降维与多方博弈双轨制生产线，执行语义主权捍卫. |
| **[personal-write-humanizer](personal-write-humanizer/)**                     | **中文文本“去 AI 化”锻造场**。模拟毒舌高管视角，执行遣词造句的同态重写.   |
| **[image-nano-gen](image-nano-gen/)**                         | **高质量图像生成引擎 (Imagen 3)**。利用 Gemini 引擎执行 4K 级图像锻造，支持高认知 Prompt 增强. |
| **[image-promp-gen](image-promp-gen/)**                       | **大师级海报与封面提示词引擎**。基于 33+ 位传奇设计师风格，支持多平台比例适配与逻辑隐喻构建. |
| **[presentation-architect](presentation-architect/)**         | **战略级 PPT 架构师**。交付具备原生逻辑的 PPT 资产，拒绝平庸模板.         |
| **[guizang-ppt-skill](guizang-ppt-skill/)**                   | **电子杂志风网页 PPT 引擎**。生成基于 WebGL 与响应式排版的单文件 HTML 演示资产. |
| **[slide-blocks](slide-blocks/)**                             | **PPT 智能组装助手**。从历史素材库中挑选幻灯片并自动拼装为风格统一的完整演示文稿. |
| **[smart-doc-latex](smart-doc-latex/)**                       | **自动化出版 LaTeX 引擎**。提供 IEEE、CV 等专业模板，交付工业级排版结果.  |

### 💼 商业洞察与投资顾问 (Marketing & Finance)
*二级市场分析与商业价值变现。*

| 技能标识 (Directory)                                            | 核心本质 (Trigger Traps)                                                          |
|:----------------------------------------------------------------|:----------------------------------------------------------------------------------|
| **[personal-investment-advisor](personal-investment-advisor/)** | **顶级金融量化引擎**。提供结构化量化 JSON 分析与 K 线周期解析，严禁通用知识回答. |

### 👤 数字原生个体成长中心 (Personal Management)
*个人生活审计、生理分析、旅行研究与生活方式控制。*

| 技能标识 (Directory)                                        | 核心本质 (Trigger Traps)                                                                   |
|:------------------------------------------------------------|:-------------------------------------------------------------------------------------------|
| **[personal-diary-writer](personal-diary-writer/)**         | **个人日志原子写入器**。负责高频轻量级的日常状态录入与安全落盘，强绑定物理 I/O 组件.        |
| **[personal-cognitive-auditor](personal-cognitive-auditor/)** | **战略认知联合审计官**。处理日/周/月/年结认知复盘，强制调度多源数据，交接 Writer 落盘.      |
| **[personal-health-analysis](personal-health-analysis/)**   | **首席医疗官 (CMO) 引擎**。对 Garmin 生理数据执行全链路审计，管理决策准备度.              |
| **[personal-monthly-insights](personal-monthly-insights/)** | **战略元分析解码器**。提取人机协作的负熵规律，识别摩擦基因并同步记忆.                     |
| **[personal-musicbee-dj](personal-musicbee-dj/)**           | **音乐极客控制协议**。通过 JIT 算法精准控制本地进程，实现秒级心流氛围切换.                |
| **[travel-research](travel-research/)**                     | **旅行研究 (ljg-travel-flow)**。深度文化旅行案头研究，涵盖博物馆、古建与考古发现.         |
| **[mentat-insight-diary](mentat-insight-diary/)**           | **内观日记与逻辑审计**。通过 OODA 框架执行认知反思，并自动物理归档 Mentat 审计日志.       |
| **[mentat-system-retro](mentat-system-retro/)**             | **量化反思引擎**。基于 Telemetry 解析 Token 黑洞与摩擦率，执行高认知负载任务后的量化复盘. |

### ⚙️ 技术全栈与逆向工程 (Tech Design)
*工作流编排、技能创建与跨界映射。*

| 技能标识 (Directory)                                  | 核心本质 (Trigger Traps)                                                                          |
|:------------------------------------------------------|:--------------------------------------------------------------------------------------------------|
| **[drawio](drawio/)**                                 | **企业级图表工程引擎**。内置语义化配色系统(7色)、5种图表类型专用规则(架构/流程/时序/ER/甘特)、5大医疗架构模式库与交付质量清单. |
| **[morphism-mapper-master](morphism-mapper-master/)** | **范畴论跨界思维引擎**。利用异构领域结构生成突破性解法，执行升维打击.                            |
| **[mentat-skill-creator](mentat-skill-creator/)**                   | **技能工厂与自愈中心 (Native Edition)**。管理技能生命周期，确保符合“四层壳模型”与三层架构规范.   |

### 🧰 全能格式转换与数据工厂 (Utilities Format)
*负责标准化格式转换与数据原质提取。*

| 技能标识 (Directory)                            | 核心本质 (Trigger Traps)                                                                              |
|:------------------------------------------------|:------------------------------------------------------------------------------------------------------|
| **[document-summarizer](document-summarizer/)** | **战略情报引擎**。具备本体驱动的语义压缩能力，输出带有战略标签的摘要.                                |
| **[minimax-docx](minimax-docx/)**               | **顶级 Word 锻造师 (MiniMax Edition)**。基于 OpenXML SDK 执行专业 DOCX 渲染，支持硬核模板校验与排版. |
| **[xlsx](xlsx/)**                               | **重装级数据治理专家**。通过物理层 XML 操纵实现 100% 数据一致性.                                     |
| **[markdown-converter](markdown-converter/)**   | **Markdown 原质炼金术**。利用 MarkItDown 将异构文件统一转化为极致干净的语义层.                       |
| **[pdf](pdf/)**                                 | **PDF 全能处理器**。支持底层字节流处理，执行 OCR 扫描、合并与拆分.                                   |
| **[text-to-speech](text-to-speech/)**           | **军工级播报系统**。支持 Edge 神经网络语音，确保高审美播报.                                          |
| **[tuanbiaodownloader](tuanbiaodownloader/)**   | **团体标准下载器**。全自动 ID 解析与 PDF 合并装订，确保 100% 获取率.                                 |
| **[url-to-markdown](url-to-markdown/)**         | **网页原质提取器**。直控 Chrome CDP 协议，强制清除网页噪音.                                          |

---
*Last Global Audit: 2026-04-30 | Version: 5.3 (Inventory Sync Edition) | System State: Locked*
