---
name: markdown-converter
description: Markdown 原质炼金术。当用户上传杂乱富文本、带图文档、甚至是需要“清洗数据”为纯净格式时，务必调用。该技能利用 MarkItDown 将异构文件统一转化为极致干净的 Markdown 语义层，为下游逻辑分析提供无噪音输入。
triggers: ["把这个文档转换成极其纯净的MD", "用MarkItDown提炼这段带图的内容", "格式化这份杂乱的笔记", "清洗富文本转为原质字符"]
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

**Telemetry & Metadata (Mandatory):**
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root_dir}/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "office-hours", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
