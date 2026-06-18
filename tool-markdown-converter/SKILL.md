---
name: tool-markdown-converter
version: 9.0.0
tier: action-allowed
description: '文件原质提取器。将异构富文本及二进制文件清洗为纯净 Markdown 语义层。禁止直接使用只读工具强读二进制，禁止将报错伪装为提取结果。'
triggers: ["把这个文档转换成极其纯净的MD", "用MarkItDown提炼这段带图的内容", "格式化这份杂乱的笔记", "清洗富文本转为原质字符"]
---

<strategy-gene>
Keywords: Markdown 转换, 文档清洗, 富文本, MarkItDown
Summary: 将异构文档清洗为干净 Markdown 语义层，服务后续分析。
Strategy:
1. 预处理识别：识别输入格式及转换需求（如 OCR 或高保真 PDF 解析）。
2. 原生执行：利用 un_command 执行底层的 converter.py，必须挂载 UTF-8。
3. 容量控制：由底层脚本执行 10万 字符截断，防止大模型爆仓。
AVOID: 直接读取二进制（如 .docx）；忽略底层脚本错误伪造输出。
</strategy-gene>

# Tool Markdown Converter (文件原质提取器 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. un_command (调用 converter.py 执行转换)

## 1. 核心流程与架构 (The Protocol)

将多种异构文件格式统一转换为 Markdown 语义层，为下游分析提供结构化输入。

### Phase 1: 格式与环境判断
- **二进制拦截**: 遇到 .docx, .pptx, .xlsx, .pdf 等二进制格式，切勿使用 iew_file 盲目读取，必须走本技能管线。
- **环境依赖**: 系统已全局安装 markitdown[all]。

### Phase 2: Standard Conversion
使用 un_command 调用底层转换脚本，前置全局编码锁与绝对物理路径：
`ash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-markdown-converter\scripts\converter.py" <INPUT_FILE> [-o <OUTPUT_FILE>]
`

### Phase 3: High-Fidelity Extraction (高精模式)
对复杂的多栏扫描版 PDF，可开启 Azure 模式（需配置）：
`ash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-markdown-converter\scripts\converter.py" input.pdf -d -e "YOUR_ENDPOINT"
`

## 2. <Domain_Knowledge> (高级语义字典)

### Supported Formats
*   **Documents**: PDF, .docx, .pptx, .xlsx
*   **Data**: CSV, JSON, XML, HTML
*   **Media**: JPG/PNG (OCR), MP3/WAV (Transcription)
*   **E-Books**: .mobi, .azw3 (自动挂载底层 book-convert 脱壳)
*   **Archive**: ZIP (自动遍历合并)
*   **需要预处理**: .djvu (纯扫描图格式，需用户手动转 PDF 后使用高精模式)

## 3. <Contracts> (输出与交付契约)
- **交付内容**：输出必须是结构化 Markdown 文件路径或预览。
- **自动化遥测契约**：底层脚本执行完毕后会自动在 MEMORY/skill_audit/telemetry/ 生成 JSON 日志，大模型**无须**手动写入遥测。
- **防爆仓防线**：文档超出 10 万字符会自动被脚本截断并输出头部警告，模型无需自行判断长度。

## 4. <Failure_Taxonomy> (失败分类学)
- **原始读取崩溃**：未经过此转换器直接对二进制文件使用文件浏览工具。
- **手动造轮子**：忽视底层的自动化 Telemetry 落盘功能，自行调用文件工具写日志。
- **沉默降级**：转换失败时未将报错抛出，反而依靠模型自行幻想文件摘要。
