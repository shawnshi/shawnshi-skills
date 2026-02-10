---
name: smart-doc-latex
description: Intelligent document-to-LaTeX conversion engine. Converts .docx/.md/.txt to professional PDF/LaTeX using specific styles (Academic, Tech Book, CV). Use when user asks to "generate PDF", "make a resume", "format my thesis", or "publish this book".
---

# Smart Doc LaTeX

自动化出版引擎，将普通文档转换为专业排版的 PDF。

## Capabilities

*   **Multi-Format Input**: 支持 Markdown (.md), Word (.docx), Text (.txt)。
*   **Style Engine**: 内置多种专业样式（Academic, CV, Tech Report, Book）。
*   **Auto-Detection**: 智能分析文档内容，自动匹配最佳样式。
*   **Full Compilation**: 生成 .tex 源码并自动调用 XeLaTeX 编译为 PDF。

## Usage

### 核心指令

```bash
python C:\Users\shich\.gemini\skills\smart-doc-latex\scripts\smart_engine.py --input <input_file> [OPTIONS]
```

### Options

| Flag | Description |
| :--- | :--- |
| `--input` | **[Required]** 输入文件路径。 |
| `--style` | 目标样式：`academic`, `cv`, `tech_report`, `book`, `tech_book`。默认 `auto`。 |
| `--title` | 覆盖文档标题（默认使用文件名）。 |
| `--author` | 覆盖作者名称。 |

## Best Practices for Agents

### 1. Pre-flight Check (环境检查)
在执行转换前，确保系统已安装必要的依赖：
*   **Pandoc**: 用于文档转换 (`pandoc --version`)。
*   **TeX Live / MiKTeX**: 用于 PDF 编译 (`xelatex --version`)。
*   若依赖缺失，应先引导用户安装，或仅生成 `.tex` 源码。

### 2. Style Selection (样式选择)
*   **Explicit**: 如果用户明确说明用途（如“生成简历”），请显式指定 `--style cv`。
*   **Implicit**: 如果用户仅要求“转为 PDF”，使用默认的 `auto` 让引擎自动探测。
*   详细样式定义见 `references/styles.md`。

### 3. Artifact Delivery (产物交付)
执行成功后，务必向用户提供生成文件的**绝对路径**：
*   PDF 文件（最终产物）
*   TeX 文件（中间源码，便于用户手动调整）

## Troubleshooting

*   **Pandoc not found**: 提示用户安装 Pandoc。
*   **Compilation failed**: 
    *   读取同目录下的 `.log` 文件末尾排查错误。
    *   常见原因：缺少宏包（Package missing）。建议用户安装 `texlive-full`。
    *   **Fallback**: 如果编译持续失败，向用户交付生成的 `.tex` 文件，建议其使用 Overleaf 在线编译。
