---
name: excel-pro
description: 重装级 Excel 治理系统。整合物理层 XML 操纵与逻辑层数据建模，实现从数据摄取到专业模型固化的全栈闭环。
language: py
---

# SKILL.md: Excel Pro (数据架构与治理专家)

## 1. 触发逻辑 (Trigger)
- 当用户提出“创建/编辑/分析 Excel”、“处理 .xlsx/.csv”、“建立财务/临床模型”或“修复损坏的表格”时激活。      

## 2. 核心架构 (Architecture)
本技能采用**双态架构 (Dual-State Architecture)**：
- **物理态 (Physical State)**: 通过 scripts/office/ 操纵 XML 结构，负责格式对齐、模板保留、修订痕迹与 XML 修复。
- **逻辑态 (Logical State)**: 通过 scripts/logic/ 结合 Pandas/openpyxl，负责数据清洗、公式生成、逻辑重算与可视化。

## 3. 核心 SOP

### 第一阶段：需求对齐与资产识别
1. **输入分析**：识别是“修改既有模板”还是“生成新分析”。
2. **环境自愈**：检查 libreoffice 是否可用。若不可用，告知用户公式自动重算功能将受限。

### 第二阶段：逻辑建模 (Logic Building)
1. **数据处理**：使用 Pandas 处理大规模数据。
2. **公式注入**：使用 openpyxl 写入原生 Excel 公式。
3. **约束校验**：严禁硬编码。所有参数必须引用 Assumptions 单元格。

### 第三阶段：物理操纵与固化 (Physical Forging)
1. **模板保护**：若修改既有文件，必须先执行 scripts/office/unpack.py 提取 XML。
2. **XML 注入**：在 XML 级别插入复杂对象或修订痕迹。
3. **重新打包**：执行 scripts/office/pack.py 确保文件结构合规。

### 第四阶段：重算与验证 (Recalc & QA)
1. **自动重算**：执行 python scripts/recalc.py 更新所有公式值。
2. **错误审计**：扫描 #REF!, #DIV/0! 等错误并自动定位修复。
3. **视觉校验**：若环境支持，生成缩略图进行视觉 QA。

## 4. 维护与资源
- **底层工具**: scripts/office/ (XML Core).
- **逻辑示例**: scripts/logic/ (Data Processing).
- **样式指南**: references/styling.md.
