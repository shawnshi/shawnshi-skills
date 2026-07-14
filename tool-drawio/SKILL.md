---
name: tool-drawio
description: 将系统架构、流程、数据流、时序、状态和实体关系转换为结构化 JSON 与可验证 SVG。当用户要求架构图、流程图、拓扑图、ER 图、时序图或需要把复杂关系可视化时使用。
---

# Technical Diagram Renderer

## Procedure

1. 确认图表类型、受众、输出尺寸、品牌约束和必须保留的节点。缺少关键拓扑时先提出最小问题；其余情况直接生成草图。
2. 将输入整理为唯一节点 ID、简短标签、关系方向和流类型。区分控制流、数据流、读取、异步和反馈。
3. 根据图表类型选择 `templates/` 中的模板，并按需读取：
   - `references/style-diagram-matrix.md`
   - `references/svg-layout-best-practices.md`
   - 与所选风格编号对应的参考说明，例如 [Flat Icon](references/style-1-flat-icon.md)
4. 生成包含 `x`、`y`、`width`、`height` 的 JSON。按层级对齐节点，为长标签换行，避免交叉连线和无意义装饰。
5. 使用 `scripts/generate-from-template.py` 渲染 SVG。先检查 Python 可用性；脚本或依赖不可用时，明确报告并提供结构化 JSON，不伪造已生成文件。
6. 检查 SVG 是否可打开，文本是否截断，箭头是否指向正确节点，视图框是否包含全部元素。必要时调整端口和通道后重渲染。
7. 将最终 SVG 和可复用 JSON 写入用户指定目录或当前工作区，并提供可点击的绝对本地文件链接。

复杂图可以在模块可独立拆分且并行能力可用时并行解析；最终坐标、命名和语义由主线统一。

## Boundaries

- 不把未经确认的业务推断画成既定架构。
- 本地文件使用可点击的绝对 Markdown 链接，不使用本地 URI 方案。
- 不默认登记知识库。只有用户明确要求保存拓扑知识时才同步。
- 仅当关键架构选择存在多种实质性方案时请求确认；普通渲染不设置额外审批。

## Output

交付 SVG、结构化 JSON、图例说明和验证结果。若用户还要求 PNG，再使用可用转换能力生成并验证。
