# spreadsheet
<!-- Input: .xlsx, .csv, .tsv files, manipulation specs. -->
<!-- Output: Analyzed/Formatted workbooks, native Excel charts, PDF renders. -->
<!-- Pos: Data Engineering Layer (The Analyst). -->
<!-- Maintenance Protocol: Update 'scripts/rendering.py' if LibreOffice path changes. -->

## 核心功能
高阶数据表格治理引擎。支持基于 `pandas` 的复杂数据分析（透视、聚合）与基于 `openpyxl` 的原生 Excel 格式修饰、公式注入及图表生成。

## 战略契约
1. **公式化逻辑**: 严禁硬编码派生值，必须使用公式（如 `=SUM(B2:B10)`）以确保数据链路的透明度与可审计性。
2. **专业建模 (IB-style)**: 对于财务/临床模型，必须隐藏网格线，表头需使用深色背景+白色文字，且负数必须标红并加括号。
3. **视觉校验**: 导出前必须执行 PDF 渲染预览，确保在不同平台（Google Docs/Office）下的排版一致性。
