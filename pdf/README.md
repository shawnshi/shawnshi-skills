# pdf
<!-- Input: PDF paths, manipulation specs (merge/split/rotate/OCR). -->
<!-- Output: Processed PDF files, extracted text/tables/images. -->
<!-- Pos: Data Processing Layer (The PDF Engineer). -->
<!-- Maintenance Protocol: Sync subscript/superscript logic in 'reportlab' templates. -->

## 核心功能
全方位的 PDF 自动化处理引擎。支持从基础的合并拆分到高级的表格提取、水印注入及扫描件 OCR 增强。

## 战略契约
1. **排版严谨性**: 严禁在生成 PDF 时使用 Unicode 下标/上标符号（会导致黑块），必须通过 ReportLab 的 XML 标记实现。
2. **结构保真**: 提取表格时优先使用 `pdfplumber` 的高级定位逻辑，确保数据可被 Pandas 准确解析。
3. **安全审计**: 支持对加密 PDF 的处理与解密，所有操作痕迹需在 `REFERENCE.md` 中可追溯。
