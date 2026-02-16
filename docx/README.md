# DOCX: 精准 XML 文档工程师

<!-- 
@Input: Content Specs, Target Templates, Formatting Rules
@Output: Structured .docx Files, Tracked Changes (XML Level)
@Pos: [ACE Layer: Action] | [MSL Segment: Deliverable Synthesis]
@Maintenance: Maintain XML repair scripts & office compatibility layer.
@Axioms: Structure Is Code | Typography Is Logic | Atomic Edit
-->

> **核心内核**：高精度 XML 操作引擎，专注于底层结构的重构与验证，确保交付物合规无瑕。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: Word 文档的物理操纵者，通过直接编辑底层 XML 实现精确到像素的排版与修订控制。
- **反向定义**: 它不是一个简单的文档编辑器，而是一个文档编译器。
- **费曼比喻**: 它不是在 Word 界面上用鼠标点点画画，而是直接进入 Word 的“基因组”，通过修改基因（XML 代码）来决定文档长什么样。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“文档结构”、“层级样式”、“修订元数据”等实体。
- **ACE 角色**: 作为 **Output Worker (交付执行者)**。

## 2. 逻辑机制 (Mechanism)
- [Unpack] -> [XML Transformation] -> [Validation] -> [Pack] -> [Compliance Check]

## 3. 策略协议 (Strategic Protocols)
- **排版即逻辑**：强制使用标准样式 ID，严禁手动插入空格或 Unicode 替代符号。
- **修订溯源**：所有编辑操作默认开启修订模式，并使用明确的作者属性。
