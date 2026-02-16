# XLSX: 重装级表格操纵器

<!-- 
@Input: Excel Workbooks, Modification Specs, Template Constraints
@Output: Logic-Preserved XLSX, Verification Logs
@Pos: [ACE Layer: Action/Data] | [MSL Segment: Data Engineering]
@Maintenance: Review formula recalculation logic & Office XML patterns.
@Axioms: Preservation First | Formula Driven | Atomic Verification
-->

> **核心内核**：在不破坏原有模型结构的前提下进行深度操作。强调公式的动态性与排版的职业化标准。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: Excel 低层操纵引擎，专注于处理复杂的逻辑嵌套与跨表引用。
- **反向定义**: 它不是简单的数据填入工具，而是一个具备“结构意识”的表格重构器。
- **费曼比喻**: 就像是一个拥有外科医生级别精度的表格操作员，他能在几千个单元格里精准找到那个公式并修改它，而不动到其他任何地方。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“Excel 实体 (Workbook/Sheet/Cell)”、“公式拓扑”、“样式元数据”。
- **ACE 角色**: 作为 **Data Worker (数据执行者)**。

## 2. 逻辑机制 (Mechanism)
- [Load & Profile] -> [Structural Mutation] -> [Recalculation (LibreOffice)] -> [Error Verification]

## 3. 策略协议 (Strategic Protocols)
- **公式优先 (Formula-First)**：严禁计算结果后硬编码，必须注入 Excel 原生公式以保持模型活力。
- **强制重算验证**：任何修改后必须调用 recalc.py 脚本，并针对 #REF! 等错误进行闭环修复。
