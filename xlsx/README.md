# xlsx
<!-- Input: .xlsx, .xlsm, .csv, .tsv files, model specs. -->
<!-- Output: Professional Excel models, recalculated workbooks. -->
<!-- Pos: Data Integrity Layer (The Heavy-Duty Analyst). -->
<!-- Maintenance Protocol: Update 'scripts/recalc.py' upon LibreOffice macro changes. -->

## 核心功能
重装级 Excel 数据治理引擎。专为财务建模、临床数据清洗及动态系统开发设计，支持基于 `openpyxl` 的深度格式控制与基于 LibreOffice 的全量公式重算。

## 战略契约
1. **动态优先**: 严禁在 Python 中计算结果后硬编码至单元格，必须使用 Excel 原生公式以确保模型的可更新性。
2. **零错误准则**: 交付物必须通过 `recalc.py` 扫描，确保 `#REF!`、`#DIV/0!` 等公式错误为零。
3. **颜色编码规范**: 强制执行行业标准：蓝色代表硬编码输入，黑色代表公式，绿色代表跨表链接。
4. **实证追溯**: 所有的硬编码输入必须在单元格批注中记录数据源（Source: [System], [Date], [URL]）。
