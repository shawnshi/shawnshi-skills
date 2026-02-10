# _DIR_META.md

## Architecture Vision
自动化文档出版引擎。
将非结构化或半结构化文本（Markdown, Docx）通过语义映射转换为出版级质量的 PDF/LaTeX，实现“内容与样式分离”的工业化文档生产。

## Member Index
- `SKILL.md`: [Required] 技能核心指令、触发逻辑及工作流定义。
- `scripts/`: [Bundled Resources] 转换引擎核心代码。
  - `smart_engine.py`: 统一执行入口，负责参数解析与管线调度。
- `references/`: [Knowledge Base] 样式定义与领域知识。
  - `styles.md`: 支持的文档样式（Book, CV, Academic）详解。
- `templates/`: [Assets] LaTeX 模板库。
- `agents/`: [Recommended] UI 适配与提示词配置。

> ⚠️ **Protocol**: 任何样式库的增删或脚本接口的变更，必须同步更新此文件及 `references/styles.md`。
