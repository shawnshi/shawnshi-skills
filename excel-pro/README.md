# Excel 专家 (excel-pro)

具备双态架构 (Physical State与Logical State) 的 Excel 数据治理与自动化分析工具集。

## 核心能力
- **双层架构解耦**：将底层 XML 物理操纵（Physical State）与高层业务模型逻辑建立（Logical State）解耦分离，防范错误链式崩溃。
- **四阶操作 SOP**：明确涵括需求锚定 (Requirement Alignment)、核心逻辑搭建 (Logic Building)、物理操作写入 (Physical Manipulation) 及重算验证 (Recalculation & Validation) 四个阶段。
- **底层安全保障**：确保所有的脚本修改严格受控，杜绝基于直觉的数据猜想，依赖确定机制（如 Python 级宏模拟运行）进行强校验。

## 使用场景
用于构建复杂的分析仪表板、创建带有底层关联公式或 VLOOKUP/XLOOKUP 宏的数据透视模型、整理杂乱无章的财务甚至人力源头表格时激活。
