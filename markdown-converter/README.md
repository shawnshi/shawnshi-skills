# markdown-converter
<!-- Input: Binary documents (PDF, DOCX, ZIP), media files. -->
<!-- Output: Clean, structured Markdown semantics. -->
<!-- Pos: Data Ingestion Layer (The Alchemist). -->
<!-- Maintenance Protocol: Keep 'scripts/converter.py' synced with MarkItDown updates. -->

## 核心功能
异构文件格式的“炼金术师”。将混乱的二进制文件统一转换为 Markdown 语义层，为下游的大模型推理提供结构化底座。

## 战略契约
1. **结构保真**: 转换过程中必须保留标题层级、列表逻辑与表格语义，严禁将表格展平为纯文本。
2. **深度提取**: 对复杂排版的 PDF 必须尝试多栏解析与图像 OCR 结合。
3. **ZIP 遍历**: 处理压缩包时必须自动执行分形递归，生成完整的目录树内容。
