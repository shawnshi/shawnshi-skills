---
name: technical-diagram-renderer
description: 将已确认的系统关系或流程描述规范化为结构化 JSON，并生成经过结构与安全校验的静态 SVG 技术图；按需单向导出基础 .drawio/mxGraph 文件。用于小到中型架构图、数据流图及受支持的语义图，不承诺完整 UML、BPMN 或 ER 标准符合性。
---

# Technical Diagram Renderer

把业务事实转换为可复用 JSON 和静态 SVG；用户需要后续编辑时，可从同一份规范化拓扑单向导出基础 draw.io/mxGraph 文件。

## 工作流

1. 确认受众、图的目的、必须保留的节点和已证实关系。只有缺失信息会改变拓扑时才提最小问题；假设必须标为假设，不能画成既定事实。
2. 选择输入模式并读取 [输入契约](references/input-schema.md)：
   - `architecture`、`data-flow` 等通用节点图使用 `nodes`、`arrows`，适合概念架构和关系表达。
   - `flowchart`、`sequence`、`state-machine`、`er-diagram`、`use-case`、`timeline` 可使用各自的语义对象，由脚本规范化后渲染。
   - 语义适配只覆盖输入契约声明的元素，不等同于完整 UML/BPMN/Chen/Crow's Foot 实现。
3. 从 1–7 号样式中选择风格。先读 [样式与图型矩阵](references/style-diagram-matrix.md)，仅在需要精确视觉控制时再读对应样式文件、[布局规范](references/svg-layout-best-practices.md)；需要图标时再读 [图标规范](references/icons.md)。Style 8 仅为设计参考，生成器不接受该值，不应向用户推荐为可选样式。
4. 优先把输入保存为 JSON 文件，再通过统一入口完成语义规范化、自动布局、渲染、验证和原子发布：

   ```bash
   python3 scripts/render-diagram.py \
     --type <diagram-type> \
     --input <input.json> \
     --output <output-base> \
     --formats svg,json \
     --validate
   ```

   不把未经信任的 JSON 直接拼接进 shell 命令，也不使用 `--no-validate` 交付成品。`generate-from-template.py` 是内部低层生成器，普通任务不要绕过统一入口。脚本或 Python 3.10+ 不可用时，明确报告并交付已完成的 JSON，不声称 SVG 已生成。
5. 按 [输出 QA](references/output-qa.md) 核验退出状态、XML/安全检查、关系方向、裁切、文字和图例。校验失败时修正输入后重新生成，不手工掩盖错误。
6. 默认交付 SVG、作为事实来源的 JSON 和简短 QA 结果。用户明确要求 draw.io 时，把 `--formats` 改为 `svg,json,drawio`；只有用户要求且本地转换器可用时才额外生成 PNG。

## 能力边界

- 适合小到中型静态技术图；复杂网络、竣工图、正式安全拓扑和标准符合性图需要专业工具及人工审查。
- 模板主要定义画布基线，最终节点、关系和样式由结构化输入与渲染器生成。
- `.drawio` 是规范化 JSON 到基础 mxGraph 的单向导出，不导入或回写现有 draw.io 文件，也不保证双向 round-trip。复杂节点、主题视觉和专用语义可能降级为基础形状，交付前必须在 diagrams.net/draw.io 中人工检查。
- 不输出 Visio、Mermaid 或交互图，也不伪造这些格式。
- 不使用名称、配色或说明暗示任何第三方品牌对样式提供官方认可。
- 保留用户的术语、边界和不确定性；不得擅自补充系统、接口、责任或数据流。
