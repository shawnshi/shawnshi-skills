---
name: tool-drawio
version: 8.1.0
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
Summary: 将复杂系统、流程或概念转化为可验证的高清 SVG 资产。原生跨平台安全。
Strategy:
1. 获取意图与图谱：确定图类型，调用图谱检索关键实体。
2. 架构骨架映射：匹配图形语义与箭头逻辑。
3. 代码即图表：必须强制通过 Python List 原生注入法（0 依赖）编写 XML/SVG 结构。
AVOID: 禁止直接输出伪代码让用户自己执行；禁止使用 `.sh` 脚本和 `rsvg-convert` 等导致 Windows 宕机的命令。
</strategy-gene>

# Fireworks Tech Graph (SVG 架构渲染仪 V8.1 Native)

> **Vision**: 摒弃残缺不全的模型直出 XML。我们利用系统底层的 Python 沙盒，以代码注入的方式，生成生产级别的技术架构 SVG 原型图。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Entity Sniffing & RAG [Mode: PLANNING]
- **MANDATORY**: Extract core entities from prompt. If applicable, query `vector-lake-mcp` to retrieve private architecture knowledge before planning. Do not rely solely on LLM hallucinations.

### Phase 2: Classification & Structure [Mode: PLANNING]
- Classify diagram type. Load the required style reference (e.g., `references/style-1-flat-icon.md`) to establish the color tokens.
- Map nodes to shapes, arrows to relationships.

### Phase 3: The "Python List Method" (MANDATORY) [Mode: EXECUTION]
- 严禁大模型直接输出带有数万字符的 SVG 原文（极易触发截断错误）。
- **必须通过 `run_command` 调用 Python 沙盒** 动态拼装 SVG。
- **强制使用跨平台安全模板 (0 依赖，原生 XML 防爆)**：
  ```python
  import os, datetime
  import xml.etree.ElementTree as ET
  
  THEME = {"bg": "#ffffff", "primary": "#2563eb", "stroke": "#cbd5e1", "text": "#334155"}
  lines = []
  lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 700">')
  lines.append('  <defs>')
  # ... APPEND ALL YOUR NODES AND ARROWS HERE ...
  lines.append('</svg>')
  
  svg_content = '\n'.join(lines)
  
  try:
      ET.fromstring(svg_content)
  except ET.ParseError as e:
      print(f"SVG Syntax Error: {e}")
      exit(1)
  
  date_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
  output_path = f'C:/Users/shich/.gemini/diagrams/output_{date_str}.svg'
  os.makedirs(os.path.dirname(output_path), exist_ok=True)
  with open(output_path, 'w', encoding='utf-8') as f:
      f.write(svg_content)
  print(f"SVG generated successfully at {output_path}")
  ```

### Phase 4: Delivery & Telemetry [Mode: EXECUTION]
- Execute the script using `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\MEMORY\scratch\diagram_generator.py"`.
- Verify the script output. If valid, deliver the physical absolute path to the user.
- Write metadata via `write_to_file` to `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`.

## 2. <Contracts> (输出与交付契约)

### Diagram Types & Layout Rules
- **Architecture**: Horizontal layers (Top→Bottom). ViewBox `0 0 960 600`. Use `<rect>` dashed containers.
- **Data Flow**: Wider arrows `stroke-width: 2.5` for primary paths. Dashed arrows for control flows.
- **Agent Architecture**: Must feature input layer, agent core (LLM/reasoning), memory layer, tool layer, and cyclic loops.

### Shape Vocabulary
- **LLM / Model**: Rounded rect + accent color.
- **Memory / Store**: Cylinder (`<path>` shapes simulating 3D) / persistent.
- **Tool / Gateway**: Hexagon or gear rect.

### Arrow Semantics (Do Not Only Change Color)
- `Primary data`: Blue `2px solid`
- `Memory read/write`: Green `1.5px solid` / `dashed 5,3`
- `Control / Event`: Orange `1.5px solid` / Gray `dashed 4,2`
- **Labels (CRITICAL)**: MUST have background `<rect fill="canvas_bg" opacity="0.95"/>`. Do NOT let text collide with lines.

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)

- **Unix 幻觉综合征 (OS Deadlock)**：绝对禁止大模型教唆系统去运行 `.sh` 脚本或使用 `rsvg-convert`。当前环境是 Windows，任何试图绕过 Python 原生方法去调用这些 Unix 工具的行为都将导致指令崩溃。
- **物理寻址塌陷 (Pathing Deadlock)**：执行脚本、落盘图像和写入日志时，必须使用带有驱动器盘符的绝对物理路径（例如 `C:\Users\shich\.gemini\...`）。严禁使用旧版的 `~/.gemini` 或 `{root}`。
- **穿模与坐标溢出 (Collision & Overflow)**：
  1. Arrows MUST NOT pass through component interiors (route around with orthogonal paths).
  2. Text MUST NOT overflow box bounds (`text.length × 7px ≤ shape_width - 16px`).
- **语法缺漏 (Syntax Forgery)**：不要犯低级错误。例如：缺少结尾 `</svg>`；使用 `yt-anchor` 替代正确的 `y="60" text-anchor="middle"`；丢掉颜色的 `#` 符号（错误：`fill=fff`，正确：`fill="#ffffff"`）。
- **工具调用越权 (Tool Forgery)**：严禁使用废旧的 `write_file`，日志遥测必须且只能使用合规的 `write_to_file`。
