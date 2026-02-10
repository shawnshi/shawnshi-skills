# Gemini 技能仓库 (Shawn Shi)

本项目包含了为 Gemini CLI 智能体定制的一系列专业技能。每个技能都提供了特定的功能增强，旨在优化人机协作效率与决策质量。

## 已上线技能

| 技能名称 | 功能描述 |
| :--- | :--- |
| **DiaryAudit** | Manages personal diary entries and performs cognitive audits (weekly, monthly, annual) using structured prompts. Use when the user asks to update their daily log, or requests a weekly, monthly, or annual review/audit of their diary. |
| **agent-browser** | Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from web pages. |
| **baoyu-article-illustrator** | Analyzes article structure, identifies positions requiring visual aids, generates illustrations with Type × Style two-dimension approach. Use when user asks to "illustrate article", "add images", "generate images for article", or "为文章配图". |
| **baoyu-cover-image** | 为文章生成四维定制化（类型、风格、文字、情绪）封面图。支持 20 种手绘与商业风格。使用场景：文章配图、社交媒体封面、书籍封面。 |
| **baoyu-slide-deck** | Transform Markdown content into professional slide decks (PPTX/PDF). Features "Smart Resume" and "Editable Text". |
| **baoyu-url-to-markdown** | Fetch any URL (including JS-heavy or login-gated pages) and convert to clean markdown. Uses Chrome CDP for high-fidelity rendering. |
| **brainstorming** | "Must be used BEFORE implementation. Turns abstract ideas into concrete design specs through structured dialogue (First Principles, Trade-off Analysis)." |
| **document-summarizer** | Batch summarize PDF/DOCX/PPTX/XLSX files with intelligent Chinese summaries and tags. Use when user asks to "summarize documents", "audit portfolio", "check compliance", or "tag medical files". |
| **docx** | "Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx files). Triggers include: any mention of \"Word doc\", \"word document\", \".docx\", or requests to produce professional documents with formatting like tables of contents, headings, page numbers, or letterheads. Also use when extracting or reorganizing content from .docx files, inserting or replacing images in documents, performing find-and-replace in Word files, working with tracked changes or comments, or converting content into a polished Word document. If the user asks for a \"report\", \"memo\", \"letter\", \"template\", or similar deliverable as a Word or .docx file, use this skill. Do NOT use for PDFs, spreadsheets, Google Docs, or general coding tasks unrelated to document generation." |
| **garmin-health-analysis** | Talk to your Garmin data naturally - "what was my fastest speed snowboarding?", "how did I sleep last night?", "what was my heart rate at 3pm?". Access 20+ metrics (sleep stages, Body Battery, HRV, VO2 max, training readiness, body composition, SPO2), download FIT/GPX files for route analysis, query elevation/pace at any point, and generate interactive health dashboards. From casual "show me this week's workouts" to deep "analyze my recovery vs training load". |
| **humanizer-zh-pro** | 专业的中文文本“去 AI 化”编辑器。消除机械感、翻译腔与虚假的逻辑词。使用场景：改写 AI 稿件、优化汇报、使公文“说人话”。 |
| **markdown-converter** | Convert any document (PDF, DOCX, PPTX, XLSX), image, or media file to clean Markdown. Powered by Microsoft MarkItDown. Use when you need to "read" non-text files for analysis. |
| **medical-solution-writer** | > **Version**: 2.8 \| **Last Updated**: 2026-02-09 \| **Context**: Visual Architecture & Text-to-Action Paradigm |
| **monthly-personal-insights** | Strategic Meta-Analyst that audits 30-day performance using "Facet-based Analysis" to decode user-AI interaction patterns, minimize system entropy, and maximize project velocity. Generates an interactive HTML report. |
| **morphism-mapper-master** | Category Theory Morphism Mapper v2.6 - 将问题结构映射到异构领域（如热力学、生物学），生成非共识创新方案。 |
| **multi-agent-writer** | A high-density collaborative writing workflow using specialized agents (concept-analyzer, thinker-roundtable, writing-assistant). Features V6.2 "Deep Defense" architecture with mandatory Red-Teaming, Outline Confirmation, and Logic Auditing. Use for strategic reports, white papers, and battle-hardened articles. |
| **news-aggregator-skill** | "Comprehensive news aggregator that fetches, filters, and deeply analyzes real-time content from 8 sources (HN, GitHub, 36Kr, etc.). Use for daily scans and trend analysis." |
| **notebooklm-skill-master** | 使用 Google NotebookLM 深度查询自有文档。支持浏览器自动化、库管理与持久化认证。场景：基于文档的深度问答、研究分析。 |
| **pdf** | Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding watermarks, creating new PDFs, filling PDF forms, encrypting/decrypting PDFs, extracting images, and OCR on scanned PDFs to make them searchable. If the user mentions a .pdf file or asks to produce one, use this skill. |
| **personal-writing-assistant** | A sophisticated writing assistant designed to generate insightful, resonant, and logically rigorous articles. Use when user asks for "deep dive", "insight", "strategic analysis", or "write an article about X". |
| **planning-with-files** | Implements Manus-style file-based planning for complex tasks. Creates task_plan.md, findings.md, and progress.md. Use when starting complex multi-step tasks, research projects, or any task requiring >5 tool calls. user-invocable: true |
| **pptx** | "Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions \"deck,\" \"slides,\" \"presentation,\" or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill." |
| **research-analyst** | 执行万字级深度研究的专家系统。V6.0 引擎版，支持分章生产、状态管理与物理拼接，产出高密度战略报告。 |
| **skill-creator** | 创建与升级 Gemini 技能的核心指南。作为 GEB-Flow 协议的守护者，确保新技能具备“分形自描述”与“渐进式披露”的高级架构标准。 |
| **smart-doc-latex** | Intelligent document-to-LaTeX conversion engine. Converts .docx/.md/.txt to professional PDF/LaTeX using specific styles (Academic, Tech Book, CV). Use when user asks to "generate PDF", "make a resume", "format my thesis", or "publish this book". |
| **spreadsheet** | "Use when tasks involve creating, editing, analyzing, or formatting spreadsheets (`.xlsx`, `.csv`, `.tsv`) using Python (`openpyxl`, `pandas`), especially when formulas, references, and formatting need to be preserved and verified." |
| **tuanbiaodownloader** | Batch downloads images from standard repositories (tuanbiao) and automatically merges them into a PDF. Supports ID extraction from URLs. Use when downloading "团体标准" (tuanbiao) or standards from ttbz.org.cn. |
| **ui-ux-pro-max** | "UI/UX design intelligence. 50 styles, 21 palettes, 50 font pairings, 20 charts, 9 stacks (React, Next.js, Vue, Svelte, SwiftUI, React Native, Flutter, Tailwind, shadcn/ui). Actions: plan, build, create, design, implement, review, fix, improve, optimize, enhance, refactor, check UI/UX code. Projects: website, landing page, dashboard, admin panel, e-commerce, SaaS, portfolio, blog, mobile app, .html, .tsx, .vue, .svelte. Elements: button, modal, navbar, sidebar, card, table, form, chart. Styles: glassmorphism, claymorphism, minimalism, brutalism, neumorphism, bento grid, dark mode, responsive, skeuomorphism, flat design. Topics: color palette, accessibility, animation, layout, typography, font pairing, spacing, hover, shadow, gradient. Integrations: shadcn/ui MCP for component search and examples." |
| **web-design-guidelines** | Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices". |
| **xlsx** | "Use this skill any time a spreadsheet file is the primary input or output. This means any task where the user wants to: open, read, edit, or fix an existing .xlsx, .xlsm, .csv, or .tsv file (e.g., adding columns, computing formulas, formatting, charting, cleaning messy data); create a new spreadsheet from scratch or from other data sources; or convert between tabular file formats. Trigger especially when the user references a spreadsheet file by name or path — even casually (like \"the xlsx in my downloads\") — and wants something done to it or produced from it. Also trigger for cleaning or restructuring messy tabular data files (malformed rows, misplaced headers, junk data) into proper spreadsheets. The deliverable must be a spreadsheet file. Do NOT trigger when the primary deliverable is a Word document, HTML report, standalone Python script, database pipeline, or Google Sheets API integration, even if tabular data is involved." |
| **xray-article** | X-ray scans articles to extract wisdom cores using a 4-layer funnel methodology, generating Markdown reports with ASCII art visualizations |
| **yahoo-finance** | 获取股票价格、基本面、新闻及历史趋势。支持多代码查询、自然语言日期解析及 JSON 输出。当用户询问“XX股价是多少”、“查看XX公司的最新新闻”或“分析XX过去一年的表现”时触发。 |

## 使用方法

在 Gemini CLI 会话中，通过以下指令激活特定技能：

`ash
activate_skill <技能名称>
`

详情请参阅各技能目录下的 SKILL.md 文件，了解具体的配置与指令。