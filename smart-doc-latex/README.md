# smart-doc-latex
<!-- Input: Markdown/Docx documents, style choices (Academic/CV/Book). -->
<!-- Output: Professional .pdf files, .tex source code. -->
<!-- Pos: Publication Layer (The Engine). -->
<!-- Maintenance Protocol: Update 'scripts/smart_engine.py' for new XeLaTeX macro packages. -->

## 核心功能
自动化出版级排版引擎。将普通 Markdown 或 Word 文档转化为具备极高美学标准的 LaTeX PDF，支持从学术论文到个人简历的专业风格映射。

## 战略契约
1. **样式自适应**: 系统必须智能分析文档内容以匹配最佳样式模板（如：识别技能关键词自动切换为 CV 样式）。
2. **透明交付**: 交付 PDF 的同时必须提供 `.tex` 源码，确保用户拥有对排版细节的终极掌控权。
3. **编译容错**: 在环境缺失或编译失败时，必须自动回退至“交付源码”状态，并提供明确的 Overleaf 在线编译指南。
