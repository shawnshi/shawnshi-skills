# Skills Ecosystem: The Strategic Armory
<!-- Pos: Root Level. -->
<!-- Vision: A modular, fractal ecosystem of specialized intelligence tools. -->
<!-- Purpose: Extending the Strategic Architect's reach across data, narrative, and execution. -->
<!-- Maintenance Protocol: All new skills must be initialized via 'skill-creator'. -->

## 1. 架构总览 (Architectural Overview)
本目录是由 33 个专业技能构成的“分形武器库”，旨在医疗智能时代构建从“情报抓取”到“顶层设计”的完整能力闭环。

## 2. 安装与部署协议 (Installation & Deployment)

你可以通过 Gemini CLI 的官方命令将本仓库中的技能安装到你的环境中：

### 安装整个仓库
gemini skills install https://github.com/shawnshi/shawnshi-skills.git
### 安装特定技能
如果你只想安装其中的某一个技能，可以使用 --path 参数。例如安装 research-analyst：

gemini skills install https://github.com/shawnshi/shawnshi-skills.git --path research-analyst


## 3. 功能矩阵 (Functional Matrix)

### A. 战略核心与规划 (Strategic Core & Planning)
- **research-analyst**: 工业级深度研究流水线，生产具备实证加固的万字级报告。
- **medical-solution-writer**: 医疗数字化转型架构专家，将模糊意图映射为确定性规划。
- **marketing-strategy**: AI 首席营销官，执行竞争博弈、风险预演与 ROI 建模。
- **planning-with-files**: “磁盘工作记忆”管理，通过持久化文件确保复杂任务的鲁棒性。
- **brainstorming**: 第一性原理驱动的实现准入门槛，强制执行技术权衡分析。
- **auditingdiary**: 个人认知熵值管理，将实战洞察同步至全局 `memory.md`。

### B. 情报获取与语义挖掘 (Intelligence & Research)
- **news-aggregator-skill**: 全域情报监测中枢，提供具备二阶洞察的趋势分析。
- **notebooklm-skill-master**: “主权 AI”知识挂载点，基于自有文档库提供确定性问答。
- **xray-article**: 文章“智慧 X 光机”，提炼跨领域可迁移的认知骨架与智慧公式。
- **url-to-markdown**: 高保真网页内容矿工，支持 CDP 渲染与登录后页面抓取。
- **yahoo-finance**: 全球金融市场数据接入点，支持历史趋势与基本面分析。
- **tuanbiaodownloader**: 行业标准（团体标准）自动化采集与 PDF 合并工具。

### C. 数据治理与工程 (Data Engineering & Processing)
- **xlsx / spreadsheet**: 财务级数据治理引擎，确保公式透明与零错误交付。
- **pdf**: 全方位 PDF 自动化处理，涵盖表格提取、OCR 增强与水印注入。
- **docx**: 精准的 XML 级文档重构引擎，支持追踪修订审计。
- **markdown-converter**: 异构格式“炼金术师”，将混乱的二进制文件统一转换为 Markdown 语义层。
- **document-summarizer**: 医疗信息化文档摘要、本体驱动标签生成与合规性审计。

### D. 叙事、创意与视觉 (Narrative & Creative)
- **multi-agent-writer**: 咨询级协作写作流，强制执行“金字塔原理”、“结论先行”与“证据展板”设计。
- **personal-writing-assistant**: 穿透力文章生成器，动词驱动，剔除所有“正确的废话”。
- **humanizer-zh-pro**: 中文文本“去 AI 化”编辑器，注入母语温度与真实节奏。
- **pptx / slide-deck**: 视觉叙事架构师，实现 Markdown 向出版级 PPT 的跃迁。
- **article-illustrator / cover-image**: 语义驱动的视觉品牌包装，拒绝平庸隐喻。
- **smart-doc-latex**: 自动化 LaTeX 出版引擎，提供极致的排版美学。

### E. 规范、交互与进化 (Standards & Meta)
- **ui-ux-pro-max**: 设计系统智能，集成 50+ 风格、97 种调色盘与 9 大技术栈。
- **web-design-guidelines**: UI 代码合规性与可访问性 (A11y) 实时扫描审计。
- **agent-browser**: 高可靠浏览器交互代理，通过坐标定位与语义查询执行自动化。
- **skill-creator**: **[Meta]** 技能进化的核心协议，守护 GEB-Flow 体系的分形完整性。
- **monthly-personal-insights**: 战略级元分析，解码人机协作模式并优化交互 ROI。
- **garmin-health-analysis**: 院外体征数据与临床智能分析的桥梁。

## 4. 维护协议 (Maintenance Protocol)
1. **灵肉合一**: 任何脚本功能的迭代必须即时同步至对应的 `README.md`。
2. **标准表头**: 每一个技能内部文件必须包含 `@Input/@Output/@Pos` 等元数据。
3. **元生成**: 新增技能必须调用 `skill-creator` 初始化，严禁手动创建空壳。

---
*Powered by Gemini CLI | Battle-Hardened Strategic Architect Edition*
