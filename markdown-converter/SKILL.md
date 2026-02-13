---
name: markdown-converter
description: Convert any document (PDF, DOCX, PPTX, XLSX), image, or media file to clean Markdown. Powered by Microsoft MarkItDown. Use when you need to "read" non-text files for analysis.
---

# Markdown Converter (The Format Alchemist)

将多种异构文件格式统一转换为 Markdown 语义层，为下游分析提供结构化输入。

## Core Capabilities
*   **Omni-Format Support**: 支持 Office 家族 (Word, PPT, Excel)、PDF、ZIP 及图片 (OCR)。
*   **Structure Preservation**: 自动提取标题、列表、表格及元数据。
*   **Media Transcription**: 支持音频/视频的元数据提取与转录（依赖底层插件）。

## Execution Workflow

### 0. Pre-flight Check (依赖自愈) [NEW]
若转换 `.docx` 或 `.pptx` 失败，提示缺少依赖，请立即尝试使用以下命令进行修复级运行：
```bash
uvx --with "markitdown[all]" markitdown <INPUT_FILE> -o <OUTPUT_FILE>
```

### 1. Standard Conversion (推荐)
直接调用包装脚本，它会自动处理 `uvx` 环境。

```bash
python scripts/converter.py <INPUT_FILE> [-o <OUTPUT_FILE>]
```

### 2. High-Fidelity Extraction (PDF)
对于复杂的、多栏排版的扫描版 PDF，建议开启 Azure 模式：
```bash
python scripts/converter.py input.pdf -d -e "YOUR_ENDPOINT"
```

## Supported Formats
*   **Documents**: PDF, .docx, .pptx, .xlsx
*   **Data**: CSV, JSON, XML, HTML
*   **Media**: JPG/PNG (OCR), MP3/WAV (Transcription)
*   **Archive**: ZIP (自动遍历并合并内容)

## Best Practices for Agents
1.  **Read First**: 遇到二进制文件（如 .docx）时，不要盲目 `read_file`，先调用此技能转换为 Markdown。
2.  **ZIP Handling**: 转换 ZIP 文件会生成包含所有子文件内容的超长 Markdown，处理时请注意上下文窗口限制。
3.  **Error Diagnosis**: 若脚本提示 `uv not found`，请引导用户安装 `uv` 运行环境。

!!! Maintenance Protocol: 任何涉及 markitdown 版本或插件的变更，必须同步更新 scripts/converter.py。
