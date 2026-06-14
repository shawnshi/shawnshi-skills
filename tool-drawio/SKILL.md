---
name: tool-drawio
version: 8.3.0
description: >-
  Use when the user wants to create any technical diagram - architecture, data
  flow, flowchart, sequence, agent/memory, or concept map - and export as
  SVG+PNG. Trigger on: "画图" "帮我画" "生成图" "做个图" "架构图" "流程图"
  "可视化一下" "出图" "generate diagram" "draw diagram" "visualize" or any
  system/flow description the user wants illustrated.
triggers: ["画图", "架构图", "流程图", "可视化一下", "出图"]
---

<strategy-gene>
Keywords: 架构图, 流程图, draw.io, Mermaid, SVG, PNG
Summary: 将复杂系统、流程或概念通过结构化 JSON 降维，交由底层 Python 引擎渲染为高清 SVG 资产。
Strategy:
1. 意图解析：确定图表类型，选取 7 大视觉厂牌中的一种。
2. 领域先验：根据 6 大架构流派规范（如 Agent 架构、数据流图等）规划横纵向布局。
3. 数据剥离：生成包含 `nodes` 和 `arrows` 的结构化语义 JSON。
4. 原生调用：通过 `run_command` 调用底层 67KB 的 `generate-from-template.py` 物理引擎。
5. 后期微调：如果用户反馈箭头穿模或凌乱，利用 `corridor_x/y` 和 `source/target_port` 强行微调 JSON，再次生成。
</strategy-gene>

# SVG 架构渲染仪 (JSON-Driven Engine V8.3 Native)

> **Vision**: 语义与渲染的绝对解耦。大模型只负责思考高维度的商业/技术架构拓扑（JSON）和箭头排障策略，绝对精准的视觉排版则交给原生的 Python 引擎。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: 确定架构流派与布局范式 [Mode: PLANNING]
- **Architecture Diagram**: 服务/组件。推荐自顶向下或从左到右分层（如：Client → Gateway → Services → DB）。使用 `<rect>` 作为大容器包含子系统。
- **Data Flow Diagram**: 强调数据流转。箭头必须标注数据内容，主链路 `flow: "data"` (粗色)，触发链路 `flow: "control"`。
- **Agent Architecture**: 必须体现这几个分层：Input → Agent Core (LLM/Planner) → Memory (短/长时) → Tools。使用闭环箭头体现 Reasoning 迭代。
- **Memory Architecture**: 明确区分 **写入路径 (Write)** 与 **读取路径 (Read)**。存储介质强制使用 `kind: "cylinder"`。

### Phase 2: Structural JSON Generation [Mode: EXECUTION]
- **大模型只需生成包含布局坐标和语义流的拓扑 JSON**，将其强制写入当前会话的安全沙盒：
  `<appDataDir>\brain\<conversation-id>\scratch\diagram_data.json`
- **坐标规矩**: 节点横向间距保持 80px-120px，纵向间距保持 100px-150px 以留出走线空间。
- **JSON 骨架示例**:
  ```json
  {
    "type": "architecture",
    "nodes": [
      {"id": "user", "label": "用户端", "sublabel": "Mobile/Web", "x": 100, "y": 100, "width": 160, "height": 60, "kind": "user_avatar"},
      {"id": "gateway", "label": "意图网关", "sublabel": "API Router", "x": 360, "y": 100, "width": 160, "height": 60, "kind": "hexagon"}
    ],
    "arrows": [
      {"source": "user", "target": "gateway", "flow": "control", "label": "发起请求"}
    ],
    "legend_box": true
  }
  ```

### Phase 3: Engine Execution (引擎激活) [Mode: EXECUTION]
- 使用 `run_command` 调用原生 Python 渲染引擎。
- **强制要求**：挂载 UTF-8 环境变量；使用纯绝对路径。
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-drawio\scripts\generate-from-template.py" 1 "<appDataDir>\brain\<conversation-id>\scratch\diagram_output.svg" "<appDataDir>\brain\<conversation-id>\scratch\diagram_data.json"
```
*(注：`1` 代表 Flat Icon 风格，可选 `1`-`7`)*

## 2. <Domain_Knowledge> (高级语义字典)

### Style Engine 厂牌库
- `1`: Flat Icon (现代扁平风)
- `2`: Dark Terminal (暗黑极客终端风)
- `3`: Blueprint (工程蓝图线框风)
- `4`: Notion Clean (极简黑白文档风)
- `5`: Glassmorphism (高端毛玻璃风)
- `6`: Claude Official (人文暖色系)
- `7`: OpenAI (生机绿极简风)

### Arrow Semantics (流向与颜色绑定)
- `control` / `api`: 主控制流/API 调用（主色/蓝色系）
- `data` / `write`: 数据转移/写入操作（重色/橙红系）
- `read`: 数据检索/召回（辅助色/绿色系）
- `async`: 异步/事件触发（灰色系，虚线）
- `feedback`: 推理闭环/反馈回路（紫色系）

## 3. 🚨 高阶防穿模与排障指南 (Post-Generation Arrow Optimization)

当用户反馈“线条乱了”、“箭头穿过框了”时，**不要去修改引擎或直接改 SVG**。你只需要修改 JSON 中的 `arrows` 数组，加入以下微调参数，并重新执行 Python 引擎：

| 字段参数 | 适用场景 / 解决方案 | 示例 |
|---|---|---|
| `source_port` / `target_port` | 引擎连线选错了出入口边。可强制设为 `"top"`, `"bottom"`, `"left"`, `"right"`。 | `{"source_port": "bottom", "target_port": "top"}` |
| `corridor_x` | 垂直方向上有多条平行的线条挤在一起。分配独立的垂直通道航段。 | `{"corridor_x": [320]}` (让线条绕到 x=320 走垂直段) |
| `corridor_y` | 水平方向上有多条线条交叉或穿模。分配独立的水平通道。 | `{"corridor_y": [480]}` (让线条下沉到 y=480 走横向段) |
| `route_points` | 系统寻路彻底崩塌时，强行接管路径关键点。 | `{"route_points": [[200,300], [200,450]]}` |

> **提示**：为不同的连线分配不同的 `corridor_y`（如 240, 260, 280），可以完美解决多线重叠的灾难！

## 4. <Contracts> (输出与交付契约)

- **交付链接契约**: 架构图生成成功后，主代理必须通过聊天框向用户输出带有绝对物理路径的 Markdown 预览语法或下载链接（例如：`![系统架构图](file:///<appDataDir>/brain/<conversation-id>/scratch/diagram_output.svg)`），让用户能够一键在界面内查阅。

## 5. <Failure_Taxonomy> (逻辑硬锁)

- **手写大段 XML 的幻觉**：如果有数百行连线需求，老老实实输出 JSON 阵列让引擎去算！绝对禁止直接通过 LLM 拼接 XML。
- **Unix 余孽与相对路径崩溃**：只允许调用 `generate-from-template.py`，禁止调用任何 `.sh` 脚本。JSON 和输出文件必须严密锚定至当前会话的安全沙盒：`<appDataDir>\brain\<conversation-id>\scratch\`，严禁向全局环境写文件。
