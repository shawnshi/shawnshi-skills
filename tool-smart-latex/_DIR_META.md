# _DIR_META.md

## Architecture Vision
自动化文档出版引擎。
将非结构化或半结构化文本（Markdown, Docx）通过语义映射转换为出版级质量的 PDF/LaTeX，实现"内容与样式分离"的工业化文档生产。

## Member Index
- `SKILL.md`: [Required] 技能核心指令、触发逻辑及工作流定义。
- `scripts/`: [Bundled Resources] 转换引擎核心代码。
  - `smart_engine.py`: **统一执行入口**，负责参数解析、样式检测与管线调度。
  - `convert_to_oreilly.py`: 独立脚本 — Markdown 直转 O'Reilly 风格 LaTeX (内置 Markdown 解析器，不依赖 Pandoc)。
  - `generate_tech_book.py`: 独立脚本 — 将 Pandoc 导出的 body .tex 与 tech_book 模板合并。
  - `process_latex_book.py`: 独立脚本 — 对 Pandoc 导出的完整 .tex 进行后处理 (去 TOC、注入 O'Reilly 封面)。
  - `process_idioms.py`: 特殊用途脚本 — 解析成语字典 .tex 文件并重排版为精美书籍。
- `references/`: [Knowledge Base] 样式定义与领域知识。
  - `styles.md`: 支持的文档样式（Book, CV, Academic, Tech Book, Tech Report）详解及自动检测逻辑。
- `templates/`: [Assets] LaTeX 模板库 (academic, book, cv, tech_book, tech_report)。
- `agents/`: [Recommended] UI 适配与提示词配置。

> ⚠️ **Protocol**: 任何样式库的增删或脚本接口的变更，必须同步更新此文件及 `references/styles.md`。
