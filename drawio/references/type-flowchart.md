# Flowchart Rules (流程图)

#### Standard shape mapping

| Node Type   | Chinese      | draw.io Style                                                                                                                  |
|-------------|--------------|--------------------------------------------------------------------------------------------------------------------------------|
| Start/End   | 开始/结束    | `ellipse;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;fontFamily=Microsoft YaHei;`                                  |
| Process     | 处理步骤     | `rounded=1;whiteSpace=wrap;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;fontFamily=Microsoft YaHei;`                |
| Decision    | 判断/分支    | `rhombus;whiteSpace=wrap;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Microsoft YaHei;`                  |
| Document    | 文档/报告    | `shape=mxgraph.flowchart.document;fillColor=#e8edf2;strokeColor=#9eafc0;fontColor=#333333;fontFamily=Microsoft YaHei;`         |
| Data I/O    | 数据输入输出 | `shape=parallelogram;fillColor=#e8edf2;strokeColor=#9eafc0;fontColor=#333333;fontFamily=Microsoft YaHei;`                      |
| Manual Op   | 手动操作     | `shape=mxgraph.flowchart.manual_operation;fillColor=#ffebee;strokeColor=#b85450;fontColor=#333333;fontFamily=Microsoft YaHei;` |
| Sub-process | 子流程       | `rounded=1;whiteSpace=wrap;strokeWidth=2;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;fontFamily=Microsoft YaHei;`  |

#### Flow direction

- Main flow: **top-to-bottom** (preferred) or left-to-right
- Decision branches: Yes/是 → right or down, No/否 → left or down
- **All decision edges MUST be labeled** ("是/否", "Yes/No", or the specific condition)
- Loop/retry paths: use `dashed=1` on edges
- End nodes: every branch must terminate at an End node or merge back into the main flow

#### Swimlane flowchart (cross-role/cross-department)

- Use horizontal swimlanes to separate roles (医生, 护士, 系统, 患者)
- Style: `swimlane;horizontal=0;startSize=30;` for left-side vertical role labels
- Place process steps within the swimlane of the responsible role
- Edges crossing swimlane boundaries represent handoffs between roles