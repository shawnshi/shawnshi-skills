---
name: tool-drawio
version: 8.2.0
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
2. 数据剥离：大模型仅负责生成包含 `nodes` 和 `arrows` 的结构化语义 JSON。
3. 原生调用：通过 `run_command` 调用底层的 `generate-from-template.py` 物理引擎执行排版渲染。
AVOID: 绝对禁止大模型手写复杂的 SVG 字符串；禁止使用过期的 Unix Bash 脚本；禁止使用非绝对路径。
</strategy-gene>

# SVG 架构渲染仪 (JSON-Driven Engine V8.2 Native)

> **Vision**: 语义与渲染的绝对解耦。大模型只负责思考高维度的商业/技术架构拓扑（JSON），绝对精准的视觉排版、正交寻路与图例挂载则交给原生的 Python 计算池兜底，彻底终结 XML 标签残缺与穿模幻觉。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Context & Mode Selection [Mode: PLANNING]
- **MANDATORY**: 提取核心实体。判断需要何种风格（默认推荐 `1` - Flat Icon，如果用户要暗色推荐 `2` - Dark Terminal，高级感可用 `5` - Glassmorphism）。

### Phase 2: Structural JSON Generation [Mode: EXECUTION]
- **大模型只需生成极其简单的拓扑 JSON**，通过 `write_to_file` 工具将其写入防爆隔离区：
  `C:\Users\shich\.gemini\MEMORY\scratch\diagram_data.json`
- **JSON 骨架示例**:
  ```json
  {
    "type": "architecture",
    "nodes": [
      {"id": "user", "label": "用户", "sublabel": "移动端APP", "x": 100, "y": 100, "width": 160, "height": 60, "kind": "rect"},
      {"id": "db", "label": "Logic Lake", "sublabel": "知识图谱", "x": 400, "y": 100, "width": 160, "height": 80, "kind": "cylinder"}
    ],
    "arrows": [
      {"source": "user", "target": "db", "flow": "control", "label": "查询请求"}
    ],
    "legend_box": true
  }
  ```

### Phase 3: Engine Execution (引擎激活与上锁) [Mode: EXECUTION]
- 必须使用 `run_command` 调用底层重达 63KB 的渲染引擎进行渲染。
- **必须挂载 UTF-8 安全锁与全绝对物理路径**：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-drawio\scripts\generate-from-template.py" 1 "C:\Users\shich\.gemini\MEMORY\diagrams\output_[TIMESTAMP].svg" "C:\Users\shich\.gemini\MEMORY\scratch\diagram_data.json"
```
*(注：命令中的 `1` 代表 style-1-flat-icon，可替换为 1-7。`[TIMESTAMP]` 请替换为实际时间戳。)*

### Phase 4: Delivery
- 将成功落盘的 SVG 文件物理路径交付给用户，并渲染到蓝图。

## 2. <Contracts> (输出与交付契约)

### Style Engine 词典 (预置 7 大视觉厂牌)
- `1`: Flat Icon (默认。现代科技扁平风)
- `2`: Dark Terminal (深色极客终端风)
- `3`: Blueprint (工程蓝图线框风)
- `4`: Notion Clean (极简黑白线条风)
- `5`: Glassmorphism (高端毛玻璃悬浮风)
- `6`: Claude Official (古典人文暖色系)
- `7`: OpenAI (硅谷生机绿极简风)

### Shape 语义映射
- 数据库/图谱：强制使用 `kind: "cylinder"`
- 网关/路由枢纽：强制使用 `kind: "hexagon"`
- 智能体/服务单元：强制使用 `kind: "rect"` 或 `kind: "bot"`
- 角色/用户节点：强制使用 `kind: "user_avatar"`

### Flow (箭头颜色逻辑锁定)
- `control` / `api`: 控制流 / 主 API 调用（主色）
- `write` / `data`: 数据写入 / 流转（副色/橙红组）
- `read`: 记忆与检索读取（绿色/辅助色组）
*(底层引擎会基于选择的 Style 自动把这些 flow 标签映射为对应的颜色，并自动生成 Legend 图例，无需大模型操心)*

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)

- **手写 XML 幻觉 (Hardcode Deadlock)**：严禁大模型退化为纯文本大批量拼接 SVG 字符串。如果有数百行 SVG，必须老老实实输出 JSON 并交由 `generate-from-template.py` 去算。
- **路径与宏塌陷 (Macro Crash)**：严禁使用相对路径和 `{root_dir}` 宏。JSON 数据源必须使用 `MEMORY\scratch\...`，SVG 产出物必须放入 `MEMORY\diagrams\...`，渲染脚本必须指向 `config\skills\tool-drawio\scripts\...`。
- **穿模灾难 (Collision)**：即便底层自带正交寻路算法，在设定 JSON 的 `x` 和 `y` 时，也要保持各层级节点之间合理的水平与垂直间距（如间距 200px+）。不要将不同层级的 node 的坐标挤压在一起。
- **Unix 余孽 (Bash Invocation)**：绝对禁止尝试调用诸如 `generate-diagram.sh` 或使用 `rsvg-convert` 工具，这是必炸的 Windows 死锁。只能调用 Python 引擎。
