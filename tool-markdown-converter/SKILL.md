---
name: markdown-converter
description: Markdown 原质炼金术。当用户上传杂乱富文本、带图文档、甚至是需要“清洗数据”为纯净格式时，务必调用。该技能利用 MarkItDown 将异构文件统一转化为极致干净的 Markdown 语义层，为下游逻辑分析提供无噪音输入。
triggers: ["把这个文档转换成极其纯净的MD", "用MarkItDown提炼这段带图的内容", "格式化这份杂乱的笔记", "清洗富文本转为原质字符"]
---

<strategy-gene>
Keywords: Markdown 转换, 文档清洗, 富文本, MarkItDown
Summary: 将异构文档清洗为干净 Markdown 语义层，服务后续分析。
Strategy:
1. 识别输入格式、附件、图片和表格需求。
2. 使用转换脚本或可用解析器生成 Markdown。
3. 检查标题层级、表格、链接、图片引用和噪音残留。
AVOID: 禁止把转换失败伪装成摘要；禁止丢失关键表格或标题结构。
</strategy-gene>

# Markdown Converter (The Format Alchemist)

将多种异构文件格式统一转换为 Markdown 语义层，为下游分析提供结构化输入。

## When to Use
- 当用户上传杂乱富文本、Office 文件、PDF、ZIP 或图片，并要求转成 Markdown 时使用。
- 本技能负责格式转换与结构保留，不负责深入内容分析。

## Core Capabilities
*   **Omni-Format Support**: 支持 Office 家族 (Word, PPT, Excel)、PDF、ZIP 及图片 (OCR)。
*   **Structure Preservation**: 自动提取标题、列表、表格及元数据。
*   **Media Transcription**: 支持音频/视频的元数据提取与转录（依赖底层插件）。

## Workflow

### 1. Standard Conversion (推荐)
直接调用包装脚本，它会自动通过本地全局环境调用 `markitdown` 进行安全转换。

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
*   **E-Books**: .mobi, .azw3 (自动挂载底层 Calibre `ebook-convert` 强行脱壳截取纯文本)
*   **Archive**: ZIP (自动遍历并合并内容)
*   **Unsupported / Need Pre-Processing**: .djvu (纯扫描图格式，需用户手动转为 PDF 后使用 Azure 模式)

## Best Practices for Agents
1.  **Read First**: 遇到二进制文件（如 .docx）时，不要盲目 `read_file`，先调用此技能转换为 Markdown。
2.  **Size Limits Managed**: 底层脚本已实现防爆仓机制。若文档超出 10 万字符，会自动截断并在头部输出系统警告。无需大模型手动预判长度。
3.  **Telemetry Automated**: 脚本执行完毕后会自动在 `MEMORY/skill_audit/telemetry/` 目录下生成 JSON 日志，大模型**绝对禁止**再手动去写日志文件。

!!! Maintenance Protocol: 系统已全局通过 `pip install markitdown[all]` 安装完毕，彻底剥离了对 `uv` 的依赖。

## Resources
- `scripts/converter.py`
- 输入文件与输出 Markdown 文件

## Failure Modes
- 不要直接对二进制文件做原始读取。
- 转换失败时必须给出真实依赖或格式原因。

## Output Contract
- 输出必须是结构化 Markdown，而不是原始二进制内容。
- 支持格式应按技能说明执行，不要静默跳过不支持类型。

## 历史失效先验 (Gotchas)
- [已修复] 早期版本过度依赖 `uvx` 导致环境报错，现已切为全局原生 pip 环境。
- [已修复] 早期 ZIP 转换容易造成 Token 爆仓，现已在 Python 层物理截断。
- [已修复] 早期让 Agent 手写日志容易引发幻觉，现已实现底层自动化。
