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
| **agent-browser** | 自动化浏览器交互，用于网页测试、表单填写、截图和数据抓取。 |
| **article-illustrator** | 分析文章结构，识别需要视觉辅助的位置，生成风格一致的插图。 |
| **auditingdiary** | 管理个人日记条目并执行周期性（周/月/年）认知审计。 |
| **brainstorming** | 在实施前将抽象想法转化为具体的工程设计规范（第一性原理、权衡分析）。 |
| **cover-image** | 为文章生成四维定制化（类型、风格、文字、情绪）封面图。 |
| **document-summarizer** | 批量总结 PDF/DOCX/PPTX/XLSX 文件，具备智能中文摘要和标签功能。 |
| **docx** | 创建、读取、编辑或操作 Word 文档 (.docx)，支持专业格式和修订跟踪。 |
| **garmin-health-analysis** | 自然语言查询 Garmin 健康数据，生成交互式看板及生理智能分析。 |
| **humanizer-zh-pro** | 专业中文文本“去 AI 化”编辑器，消除机械感与翻译腔。 |
| **markdown-converter** | 将 PDF、Office 文档、图片及媒体文件统一转换为纯净的 Markdown。 |
| **medical-solution-writer** | 医疗数字化解决方案专家，基于 Text-to-Action 范式设计转型规划。 |
| **monthly-personal-insights** | 战略元分析师，通过 Facet 分析审计 30 天表现，最小化系统熵。 |
| **morphism-mapper-master** | 范畴论映射器，将问题结构映射到异构领域以生成创新方案。 |
| **multi-agent-writer** | 高密度多智能体协作写作流，具备红队测试与深度逻辑审计功能。 |
| **news-aggregator-skill** | 综合新闻聚合器，实时监测并深度分析全球科技与金融动态。 |
| **notebooklm-skill-master** | 使用 Google NotebookLM 深度查询自有文档，支持浏览器自动化。 |
| **pdf** | 全能 PDF 处理工具：阅读、提取、合并、拆分、旋转、水印、表单填写及 OCR。 |
| **personal-writing-assistant** | 战略写作引擎，生成高密度、高逻辑穿透力的深度文章。 |
| **planning-with-files** | 实现 Manus 风格的文件驱动型计划系统，处理复杂多步任务。 |
| **pptx** | 创建、编辑和操作 PowerPoint 演示文稿，支持模板与内容提取。 |
| **research-analyst** | 工业级深度研究流水线，支持分章撰写、状态管理与逻辑审计。 |
| **skill-creator** | 创建与升级 Gemini 技能的核心指南，确保符合 GEB-Flow 协议。 |
| **slide-deck** | 将 Markdown 内容转化为出版级 PPTX/PDF 演示文稿。 |
| **smart-doc-latex** | 智能文档转 LaTeX 引擎，生成专业排版的 PDF（简历、书籍、报告）。 |
| **spreadsheet** | 创建、编辑、分析和可视化电子表格 (.xlsx, .csv)，保护公式与格式。 |
| **tuanbiaodownloader** | 批量下载团体标准图像并自动合并为 PDF，支持 ID 智能提取。 |
| **ui-ux-pro-max** | UI/UX 设计情报库，提供 50+ 风格、色板、图表及代码实现指南。 |
| **url-to-markdown** | 高保真将任意 URL（含动态/登录页）转换为纯 Markdown。 |
| **web-design-guidelines** | 根据 Web Interface Guidelines 审查 UI 代码的合规性与设计质量。 |
| **xlsx** | 专业 Excel 处理技能，专注于零错误公式与严格的格式合规性。 |
| **xray-article** | 智慧 X 光机，通过四层漏斗扫描文章以提取认知骨架与晶核。 |
| **yahoo-finance** | 获取股票价格、基本面、新闻及历史趋势，支持自然语言查询。 |

## 激活与使用

安装完成后，在 Gemini CLI 会话中，通过以下指令激活特定技能：

```bash
activate_skill <技能名称>
```

详情请参阅各技能目录下的 `SKILL.md` 文件，了解具体的配置与指令。
