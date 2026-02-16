# Excel Pro: 数据诚信堡垒

<!-- 
@Input: Heterogeneous Data (CSV/XLSX), Modification Specs, Design Templates
@Output: Logic-Driven Workbooks, Validated Models, Visual QA Reports
@Pos: [ACE Layer: Action/Data] | [MSL Segment: Data Engineering]
@Maintenance: Sync scripts/office/ with latest OOXML standards & repair logic.
@Axioms: No Hardcoding | Formula Recalculation | Structure Fidelity
-->

> **核心内核**：重装级 Excel 治理系统。整合物理层 XML 操纵与逻辑层数据建模，实现从“数据摄取”到“专业模型固化”的全栈闭环。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 数据逻辑的守门员，负责确保 Excel 模型具备“自重算”能力、财务级严谨性与物理层级的结构完整性。
- **反向定义**: 它不是简单的表格填入器，而是一个具备 XML 级精度的数据架构引擎。
- **费曼比喻**: 它像是在 Excel 里装了一个“外科手术台”加一台“超级计算器”。它既能精准修改表格的“基因”（XML），又能确保里面所有的逻辑题（公式）都算得明明白白。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 管理“逻辑拓扑”、“单元格算式”、“合规样式”等数据实体。
- **ACE 角色**: 作为系统的 **Data Architect (数据架构师)**，为临床决策或财务分析提供确定性的计算底座。

## 2. 逻辑机制 (Mechanism)
- [Data Ingestion] -> [Logic Modeling (Pandas)] -> [Physical Mutation (XML)] -> [Formula Recalc] -> [Closure Audit]

## 3. 策略协议 (Strategic Protocols)
- **硬编码熔断**：严禁在逻辑计算单元中直接填入数字，所有参数必须由独立 Assumption 单元格驱动。
- **双态完整性**：修改既有模板前必须先通过 XML Unpack 提取结构，确保样式与宏等高级对象不丢失。
- **自动化重算**：产出后必须强制执行 recalc.py 校验，禁止交付未经过重算验证的逻辑文件。
