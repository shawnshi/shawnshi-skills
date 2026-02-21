---
name: smart-doc-latex
description: Intelligent document-to-LaTeX conversion engine. Converts .docx/.md/.txt to professional PDF/LaTeX using specific styles (Academic, Tech Book, CV). Use when user asks to "generate PDF", "make a resume", "format my thesis", or "publish this book".
---

# Smart Doc LaTeX

自动化出版引擎，将普通文档转换为专业排版的 PDF。

## Capabilities

*   **Multi-Format Input**: 支持 Markdown (.md), Word (.docx), Text (.txt)。
*   **Style Engine**: 内置多种专业样式（Academic, CV, Tech Report, Book, Tech Book）。
*   **Auto-Detection**: 智能分析文档内容，自动匹配最佳样式。
*   **Full Compilation**: 生成 .tex 源码并自动调用 XeLaTeX 编译为 PDF。

## Usage

### 核心引擎 (smart_engine.py)

统一入口，适用于大多数文档转换场景。

```bash
python C:\Users\shich\.gemini\skills\smart-doc-latex\scripts\smart_engine.py --input <input_file> [OPTIONS]
```

| Flag | Description |
| :--- | :--- |
| `--input` | **[Required]** 输入文件路径。 |
| `--style` | 目标样式：`academic`, `cv`, `tech_report`, `book`, `tech_book`。默认 `auto`。 |
| `--title` | 覆盖文档标题（默认使用文件名）。 |
| `--author` | 覆盖作者名称。 |
| `--output` | 输出目录（默认使用输入文件所在目录）。 |

### 辅助脚本

以下脚本用于特定场景，**不经 smart_engine.py 调度**，需独立调用：

| Script | Purpose | Usage |
| :--- | :--- | :--- |
| `convert_to_oreilly.py` | 将 Markdown 直接转为 O'Reilly 风格 LaTeX 书籍 (无需 Pandoc) | `python convert_to_oreilly.py <input.md> <output.tex>` |
| `generate_tech_book.py` | 将 Pandoc 导出的 body .tex 与 tech_book 模板合并 | `python generate_tech_book.py <body.tex> <output.tex> <title> [author]` |
| `process_latex_book.py` | 后处理 Pandoc 导出的 .tex (去 TOC + O'Reilly 封面) | `python process_latex_book.py <input.tex> <output.tex> [title] [author]` |
| `process_idioms.py` | **特殊用途**：解析成语字典 .tex 并重排版 | `python process_idioms.py` (硬编码输入) |

## Best Practices for Agents

### 1. Pre-flight Check (环境检查)
在执行转换前，确保系统已安装必要的依赖：
*   **Pandoc**: 用于文档转换 (`pandoc --version`)。
*   **TeX Live / MiKTeX**: 用于 PDF 编译 (`xelatex --version`)。
*   若依赖缺失，应先引导用户安装，或仅生成 `.tex` 源码。

### 2. Style Selection (样式选择)
*   **Explicit**: 如果用户明确说明用途（如"生成简历"），请显式指定 `--style cv`。
*   **Implicit**: 如果用户仅要求"转为 PDF"，使用默认的 `auto` 让引擎自动探测。
*   详细样式定义见 `references/styles.md`。

### 3. Script Selection (脚本选择)
*   **通用转换**: 优先使用 `smart_engine.py`。
*   **O'Reilly 风格书籍**: 若源文件为 Markdown，使用 `convert_to_oreilly.py`；若已有 Pandoc 中间体，使用 `process_latex_book.py` 或 `generate_tech_book.py`。
*   **成语字典**: 仅在处理成语 .tex 文件时使用 `process_idioms.py`。

### 4. Artifact Delivery (产物交付)
执行成功后，务必向用户提供生成文件的**绝对路径**：
*   PDF 文件（最终产物）
*   TeX 文件（中间源码，便于用户手动调整）

## Troubleshooting

*   **Pandoc not found**: 提示用户安装 Pandoc。
*   **Compilation failed**: 
    *   读取同目录下的 `.log` 文件末尾排查错误。
    *   常见原因：缺少宏包（Package missing）。建议用户安装 `texlive-full`。
    *   **Fallback**: 如果编译持续失败，向用户交付生成的 `.tex` 文件，建议其使用 Overleaf 在线编译。
