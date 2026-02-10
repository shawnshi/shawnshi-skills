# Gemini 技能仓库 (Shawn Shi)

本项目包含了为 Gemini CLI 智能体定制的一系列专业技能。每个技能都提供了特定的功能增强，旨在优化人机协作效率与决策质量。

## 安装方法

你可以通过 Gemini CLI 的官方命令将本仓库中的技能安装到你的环境中：

### 1. 安装整个仓库
```bash
gemini skills install https://github.com/shawnshi/shawnshi-skills.git
```

### 2. 安装特定技能
如果你只想安装其中的某一个技能，可以使用 `--path` 参数。例如安装 `research-analyst`：
```bash
gemini skills install https://github.com/shawnshi/shawnshi-skills.git --path research-analyst
```

## 已上线技能

| 技能名称 | 功能描述 |
| :--- | :--- |
| **DiaryAudit** | 管理个人日记条目并使用结构化提示执行认知审计（周、月、年）。 |
| **agent-browser** | 自动化浏览器交互，用于网页测试、表单填写、截图和数据抓取。 |
| **baoyu-article-illustrator** | 分析文章结构，识别需要视觉辅助的位置，生成具有类型x风格一致性的插图。 |
| **baoyu-cover-image** | 为文章生成四维定制化（类型、风格、文字、情绪）封面图。 |
| **baoyu-slide-deck** | 将 Markdown 内容转换为专业的演示文稿（PPTX/PDF），支持智能摘要和可编辑文本。 |
| **baoyu-url-to-markdown** | 获取任何 URL（包括重 JavaScript 或登录限制页面）并转换为纯 Markdown。 |
| **brainstorming** | 在实施前将抽象想法转化为具体的工程设计规范（第一性原理、权衡分析）。 |
| **document-summarizer** | 批量总结 PDF/DOCX/PPTX/XLSX 文件，并带有智能中文摘要和标签。 |
| **docx** | 创建、读取、编辑或操作 Word 文档（.docx），支持格式化、修订跟踪和模板处理。 |
| **garmin-health-analysis** | 自然地与 Garmin 数据对话，访问 20+ 指标并生成交互式健康看板。 |
| **humanizer-zh-pro** | 专业的中文文本去 AI 化编辑器，消除机械感、翻译腔与虚假的逻辑词。 |
| **markdown-converter** | 将任何文档、图像或媒体文件转换为纯净的 Markdown 语义层。 |
| **medical-solution-writer** | 医疗数字化解决方案专家，基于 Text-to-Action 范式 design 转型规划。 |
| **monthly-personal-insights** | 战略元分析师，通过 Facet 分析审计 30 天表现，最小化系统熵。 |
| **morphism-mapper-master** | 范畴论映射器，将问题结构映射到异构领域（如热力学）以生成创新方案。 |
| **multi-agent-writer** | 高密度协作写作工作流，具备红队测试、大纲确认和深度逻辑审计。 |
| **news-aggregator-skill** | 综合新闻聚合器，抓取、过滤并深度分析 8 个来源的实时内容。 |
| **notebooklm-skill-master** | 使用 Google NotebookLM 深度查询自有文档，支持浏览器自动化与持久化认证。 |
| **pdf** | 全能 PDF 处理工具，包括阅读、提取、合并、拆分、表单填写和 OCR。 |
| **personal-writing-assistant** | 高级写作助手，生成具有洞察力、共鸣和逻辑严密性的战略文章。 |
| **planning-with-files** | 实现 Manus 风格的文件驱动型计划系统，用于处理复杂的多步任务。 |
| **pptx** | 全面处理 PowerPoint 文件，包括读取内容、从模板编辑或从头创建。 |
| **research-analyst** | 执行万字级深度研究的专家系统，支持分章生产、状态管理与物理拼接。 |
| **skill-creator** | 创建与升级 Gemini 技能的核心指南，确保符合 GEB-Flow 协议标准。 |
| **smart-doc-latex** | 智能文档转 LaTeX 引擎，将普通文档转换为专业排版的 PDF（学术、简历、书籍风格）。 |
| **spreadsheet** | 使用 Python 创建、编辑或分析电子表格，保护公式、引用与格式。 |
| **tuanbiaodownloader** | 批量下载团体标准图像并自动合并为 PDF，支持 ID 智能提取。 |
| **ui-ux-pro-max** | UI/UX 设计情报库，包含 50+ 风格、97 调色板、20 种图表及 99 条 UX 准则。 |
| **web-design-guidelines** | 根据 Web 界面指南审查 UI 代码的合规性、可访问性和设计质量。 |
| **xlsx** | 处理 Excel 电子表格的核心技能，确保零公式错误并保留现有模板规范。 |
| **xray-article** | 智慧 X 光机，通过 4 层漏斗方法论扫描文章以提取智慧核心 and 认知骨架。 |
| **yahoo-finance** | 获取股票价格、基本面、新闻及历史趋势，支持多代码查询与 JSON 输出。 |

## 激活与使用

安装完成后，在 Gemini CLI 会话中，通过以下指令激活特定技能：

```bash
activate_skill <技能名称>
```

详情请参阅各技能目录下的 `SKILL.md` 文件，了解具体的配置与指令。
