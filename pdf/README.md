# PDF: 结构化工程引擎

<!-- 
@Input: Heterogeneous PDF Files (Scanned/Digital), Formatting Specs
@Output: Extracted Tables (Excel/DF), OCR-Enhanced Text, Merged/Split PDF
@Pos: [ACE Layer: Action/Data] | [MSL Segment: Document Engineering]
@Maintenance: Monitor OCR accuracy & table extraction alignment.
@Axioms: Layout Fidelity | Semantic Extraction | Secure Processing
-->

> **核心内核**：非结构化数据的精密手术刀。全方位自动化处理引擎，支持从物理层（合并拆分）到语义层（表格/OCR）的深度操作。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: PDF 资产的操作者，负责打破 PDF 的格式壁垒，将其转化为可供计算的数据。
- **反向定义**: 它不是一个简单的阅读器，而是一个 PDF 编译器与解构器。
- **费曼比喻**: 就像是一个精密的扫描与重组仪，不仅能把几十本书装订成一本，还能把书里复杂的表格精确地抄到 Excel 里。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“文档层级”、“表格拓扑”、“图像语义”等实体。
- **ACE 角色**: 作为 **Data Worker (数据执行者)**。

## 2. 逻辑机制 (Mechanism)
- [Metadata Extraction] -> [Structural Parsing] -> [OCR/Transformation] -> [Output Synthesis]

## 3. 策略协议 (Strategic Protocols)
- **排版保真**：严禁直接使用 Unicode 字符（防黑块），必须通过标准的库标记实现精密布局。
- **结构优先**：优先使用坐标定位（pdfplumber）提取表格，确保数据与 Pandas 无缝兼容。
