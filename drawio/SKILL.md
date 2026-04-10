---
name: drawio
description: Always use when user asks to create, generate, draw, or design a diagram, flowchart, architecture diagram, ER diagram, sequence diagram, class diagram, network diagram, mockup, wireframe, or UI sketch, or mentions draw.io, drawio, drawoi, .drawio files, or diagram export to PNG/SVG/PDF.
---

# Draw.io Diagram Skill

Generate draw.io diagrams as native `.drawio` files. Optionally export to PNG, SVG, or PDF with the diagram XML embedded (so the exported file remains editable in draw.io).

## How to create a diagram

1. **Generate draw.io XML** in mxGraphModel format for the requested diagram
2. **Write the XML** to a `.drawio` file in the current working directory using the Write tool
3. **If the user requested an export format** (png, svg, pdf), locate the draw.io CLI (see below), export with `--embed-diagram`, then delete the source `.drawio` file. If the CLI is not found, keep the `.drawio` file and tell the user they can install the draw.io desktop app to enable export, or open the `.drawio` file directly
4. **Open the result** — the exported file if exported, or the `.drawio` file otherwise. If the open command fails, print the file path so the user can open it manually

## Diagram Type Router

When the user’s request does not explicitly name a diagram type, infer the type from keywords before generating:

| User Keywords | → Diagram Type |
|--------------|----------------|
| 架构、系统组成、技术栈、部署、拓扑 | Architecture (架构图) |
| 流程、审批、路径、步骤、诊疗、工作流 | Flowchart (流程图) |
| 调用链、消息流、接口交互、API、时序 | Sequence (时序图) |
| 数据模型、实体关系、表结构、ER、字段 | ER Diagram (实体关系图) |
| 时间线、项目计划、里程碑、进度 | Gantt / Timeline (甘特图) |
| 类关系、继承、接口、抽象类 | Class Diagram (类图) |
| 网络、拓扑、机房、服务器 | Network Diagram (网络图) |

Once the type is determined, apply the corresponding **Diagram Type Construction Rules** section. If the request maps to multiple types, ask the user to clarify.

## Choosing the output format

Check the user's request for a format preference. Examples:

- `/drawio create a flowchart` → `flowchart.drawio`
- `/drawio png flowchart for login` → `login-flow.drawio.png`
- `/drawio svg: ER diagram` → `er-diagram.drawio.svg`
- `/drawio pdf architecture overview` → `architecture-overview.drawio.pdf`

If no format is mentioned, just write the `.drawio` file and open it in draw.io. The user can always ask to export later.

### Supported export formats

| Format | Embed XML  | Notes                                    |
|--------|------------|------------------------------------------|
| `png`  | Yes (`-e`) | Viewable everywhere, editable in draw.io |
| `svg`  | Yes (`-e`) | Scalable, editable in draw.io            |
| `pdf`  | Yes (`-e`) | Printable, editable in draw.io           |
| `jpg`  | No         | Lossy, no embedded XML support           |

PNG, SVG, and PDF all support `--embed-diagram` — the exported file contains the full diagram XML, so opening it in draw.io recovers the editable diagram.

## draw.io CLI

The draw.io desktop app includes a command-line interface for exporting.

### Locating the CLI

First, detect the environment, then locate the CLI accordingly:

#### WSL2 (Windows Subsystem for Linux)

WSL2 is detected when `/proc/version` contains `microsoft` or `WSL`:

```bash
grep -qi microsoft /proc/version 2>/dev/null && echo "WSL2"
```

On WSL2, use the Windows draw.io Desktop executable via `/mnt/c/...`:

```bash
DRAWIO_CMD=`/mnt/c/Program Files/draw.io/draw.io.exe`
```

The backtick quoting is required to handle the space in `Program Files` in bash.

If draw.io is installed in a non-default location, check common alternatives:

```bash
# Default install path
`/mnt/c/Program Files/draw.io/draw.io.exe`

# Per-user install (if the above does not exist)
`/mnt/c/Users/$WIN_USER/AppData/Local/Programs/draw.io/draw.io.exe`
```

#### macOS

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io
```

#### Linux (native)

```bash
drawio   # typically on PATH via snap/apt/flatpak
```

#### Windows (native, non-WSL2)

```
"C:\Program Files\draw.io\draw.io.exe"
```

Use `which drawio` (or `where drawio` on Windows) to check if it's on PATH before falling back to the platform-specific path.

### Export command

```bash
drawio -x -f <format> -e -b 10 -o <output> <input.drawio>
```

**WSL2 example:**

```bash
`/mnt/c/Program Files/draw.io/draw.io.exe` -x -f png -e -b 10 -o diagram.drawio.png diagram.drawio
```

Key flags:
- `-x` / `--export`: export mode
- `-f` / `--format`: output format (png, svg, pdf, jpg)
- `-e` / `--embed-diagram`: embed diagram XML in the output (PNG, SVG, PDF only)
- `-o` / `--output`: output file path
- `-b` / `--border`: border width around diagram (default: 0)
- `-t` / `--transparent`: transparent background (PNG only)
- `-s` / `--scale`: scale the diagram size
- `--width` / `--height`: fit into specified dimensions (preserves aspect ratio)
- `-a` / `--all-pages`: export all pages (PDF only)
- `-p` / `--page-index`: select a specific page (1-based)

### Opening the result

| Environment    | Command                                      |
|----------------|----------------------------------------------|
| macOS          | `open <file>`                                |
| Linux (native) | `xdg-open <file>`                            |
| WSL2           | `cmd.exe /c start "" "$(wslpath -w <file>)"` |
| Windows        | `start <file>`                               |

**WSL2 notes:**
- `wslpath -w <file>` converts a WSL2 path (e.g. `/home/user/diagram.drawio`) to a Windows path (e.g. `C:\Users\...`). This is required because `cmd.exe` cannot resolve `/mnt/c/...` style paths.
- The empty string `""` after `start` is required to prevent `start` from interpreting the filename as a window title.

**WSL2 example:**

```bash
cmd.exe /c start "" "$(wslpath -w diagram.drawio)"
```

## File naming

- Use a descriptive filename based on the diagram content (e.g., `login-flow`, `database-schema`)
- Use lowercase with hyphens for multi-word names
- For export, use double extensions: `name.drawio.png`, `name.drawio.svg`, `name.drawio.pdf` — this signals the file contains embedded diagram XML
- After a successful export, delete the intermediate `.drawio` file — the exported file contains the full diagram

### Output path

- Default output directory: **`C:\Users\shich\.gemini\diagrams\`**
- If the directory does not exist, **create it automatically** before writing
- If the user specifies an explicit path, use that path instead
- **Never** write to `/tmp`, system directories, or the `.gemini` config directory
- Always use **absolute paths** in export and open commands

## XML format

A `.drawio` file is native mxGraphModel XML. Always generate XML directly — Mermaid and CSV formats require server-side conversion and cannot be saved as native files.

### Basic structure

Every diagram must have this structure:

```xml
<mxGraphModel adaptiveColors="auto">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
  </root>
</mxGraphModel>
```

Place all diagram cells inside `<root>` with `parent="1"` (or a container's id for nested elements).

- Cell `id="0"` is the root layer
- Cell `id="1"` is the default parent layer
- All diagram elements use `parent="1"` unless using multiple layers

## Semantic Color System (MANDATORY)

**This section is CONSTITUTIONAL — it overrides any color values found in the upstream xml-reference.md or style-reference.md.** When those references show `fillColor=#dae8fc;strokeColor=#6c8ebf` (draw.io default blue) or any other ad-hoc color, replace them with the semantic colors defined below.

### Color Palette

Every shape in a diagram MUST use one of these 7 semantic roles. No other fill/stroke combinations are permitted.

| Role         | Name       | Style String                                               | Use When                                                                                           |
|--------------|------------|------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| **Base**     | 莫兰迪灰蓝 | `fillColor=#e8edf2;strokeColor=#9eafc0;fontColor=#333333;` | Default / stable / general-purpose components (frontend UI, clients, generic boxes)                |
| **Core**     | 清豆绿     | `fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;` | Core processing components (microservices, API gateways, backend services, main business flow)     |
| **Active**   | 极地蓝     | `fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;` | Data infrastructure (databases, message queues, caches, storage) or emphasized/selected components |
| **Alert**    | 淡樱粉     | `fillColor=#ffebee;strokeColor=#b85450;fontColor=#333333;` | Error handling, alerts, circuit breakers, blocked/failed states                                    |
| **Inactive** | 浅灰       | `fillColor=#f5f5f5;strokeColor=#b3b3b3;fontColor=#999999;` | Deprecated, inactive, legacy systems, disabled modules                                             |
| **External** | 浅丁香紫   | `fillColor=#f3e5f5;strokeColor=#9673a6;fontColor=#666666;` | External APIs, third-party SaaS, CDN, any system outside the trust boundary                        |
| **Edge**     | 中灰       | `strokeColor=#808080;fontColor=#666666;`                   | ALL edges/connectors — unified color regardless of connected nodes                                 |

### Semantic Routing Rules

Before assigning a color, classify every component into a semantic role using this routing table:

| Component Type                                                             | → Semantic Role         |
|----------------------------------------------------------------------------|-------------------------|
| Microservices, API Gateway, backend services, business logic               | **Core** (清豆绿)       |
| Databases, message queues (Kafka/RabbitMQ), caches (Redis), object storage | **Active** (极地蓝)     |
| Frontend UI, mobile clients, web browsers, desktop apps                    | **Base** (莫兰迪灰蓝)   |
| Error handlers, alerts, circuit breakers, DLQ, retry/fallback paths        | **Alert** (淡樱粉)      |
| Legacy systems, deprecated modules, to-be-decommissioned services          | **Inactive** (浅灰)     |
| External APIs, third-party SaaS, CDN, payment gateways, OAuth providers    | **External** (浅丁香紫) |

### Iron Rules

1. **同类同构 (Homogeneous Coloring)**: Components of the same type MUST use the same semantic role color. If you have 5 microservices, ALL 5 use Core (清豆绿). No exceptions.
2. **Edges are ALWAYS medium gray** (`strokeColor=#808080;fontColor=#666666;`). Never color-code edges by their connected nodes.
3. **Containers/swimlanes reuse the 6-color palette**: A swimlane grouping microservices uses Core; a swimlane grouping databases uses Active; a boundary around external systems uses External. Apply the semantic role of the dominant children.
4. **Trust boundary rule**: Internal trusted systems use solid fills (Base/Core/Active). External untrusted systems use External (浅丁香紫). This is a hard security-semantic distinction.
5. **When in doubt, use Base** (莫兰迪灰蓝). Never fall back to draw.io default blue `#dae8fc`.

### Font Standard

All text labels MUST use an explicit `fontFamily`. Never rely on browser/system defaults.

| Context           | Style Fragment                            |
|-------------------|-------------------------------------------|
| Default (Latin)   | `fontFamily=Inter;fontSize=12;`           |
| Chinese labels    | `fontFamily=Microsoft YaHei;fontSize=12;` |
| Title / header    | `fontSize=14;fontStyle=1;` (bold)         |
| Annotation / note | `fontSize=10;fontColor=#999999;`          |

Append the appropriate `fontFamily` to every style string in the Quick-copy section below.

### Quick-copy Style Strings

Use these complete style strings as templates:

**Core service node:**
```
rounded=1;whiteSpace=wrap;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;
```

**Database cylinder:**
```
shape=cylinder3;whiteSpace=wrap;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;
```

**External service:**
```
rounded=1;whiteSpace=wrap;fillColor=#f3e5f5;strokeColor=#9673a6;fontColor=#666666;dashed=1;
```

**Alert/error node:**
```
rounded=1;whiteSpace=wrap;fillColor=#ffebee;strokeColor=#b85450;fontColor=#333333;
```

**Legacy node:**
```
rounded=1;whiteSpace=wrap;fillColor=#f5f5f5;strokeColor=#b3b3b3;fontColor=#999999;dashed=1;
```

**Swimlane container (Core group):**
```
swimlane;startSize=30;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;
```

**Edge (all edges):**
```
edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#808080;fontColor=#666666;
```

## Layout Guidelines

### Spacing

- Minimum horizontal gap between nodes: **200px**
- Minimum vertical gap between nodes: **120px**
- Align all coordinates to a **10px grid** (x, y, width, height must be multiples of 10)
- Start canvas at **(100, 100)** — never place nodes at origin (0, 0)
- Maximum **4–5 nodes per row** before wrapping to the next row
- Swimlane containers: max width **600px**, expand height as needed

### Complexity Tiers

Before generating, count the estimated node count and apply the corresponding strategy:

| Node Count | Strategy                                                                                 |
|------------|------------------------------------------------------------------------------------------|
| 1–10       | Single layer, flat layout, no containers needed                                          |
| 11–25      | **MUST** use swimlane containers to group related components                             |
| 26–50      | **MUST** use multiple layers + containers + consider multi-page (`<diagram>` per page)   |
| 50+        | **REFUSE** single-diagram generation — split into sub-diagrams by domain/bounded context |

## Multi-page Diagram

A single `.drawio` file can contain multiple pages. Use `<mxfile>` as root instead of `<mxGraphModel>`:

```xml
<mxfile>
  <diagram id="page1" name="逻辑架构">
    <mxGraphModel adaptiveColors="auto">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
  <diagram id="page2" name="部署架构">
    <mxGraphModel adaptiveColors="auto">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

### When to use multi-page

| Scenario                       | Pages                             |
|--------------------------------|-----------------------------------|
| 逻辑架构 + 部署架构 + 数据流图 | 3 pages, one per view             |
| 大系统按子域拆分               | 1 page per bounded context        |
| 现状 (As-Is) vs 目标 (To-Be)   | 2 pages for comparison            |
| 复杂度 Tier 50+ 节点           | Mandatory split into sub-diagrams |

### Multi-page rules

- Each `<diagram>` must have a unique `id` and descriptive Chinese `name`
- Cell IDs only need to be unique within each `<diagram>`, not globally
- The Semantic Color System, Font Standard, and Layout Guidelines apply to **ALL** pages
- For single-page diagrams, continue using `<mxGraphModel>` as root (no `<mxfile>` wrapper needed)

## Diagram Type Construction Rules

The following sections provide type-specific construction rules. Apply the correct section based on the diagram type.

### Flowchart Rules (流程图)

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

### Sequence Diagram Rules (时序图)

#### Participants (参与者)

Each participant is built from two elements stacked vertically:

1. **Header box** (top): rectangle with participant name
2. **Lifeline** (below): vertical dashed edge extending downward

Header style:
```
rounded=1;whiteSpace=wrap;fillColor=#e8edf2;strokeColor=#9eafc0;fontColor=#333333;fontFamily=Microsoft YaHei;fontSize=12;fontStyle=1;
```

Lifeline style (vertical dashed line, no arrows):
```
endArrow=none;startArrow=none;dashed=1;strokeColor=#b3b3b3;
```

#### Layout

- Participants: horizontal row at the top, spacing ≥ 200px
- Messages: horizontal arrows between lifelines, vertical spacing ≥ 40px
- Time flows **top-to-bottom**
- Activation bars: narrow rectangles (width=16) overlaid on lifelines during active processing

#### Message types

| Type              | Chinese  | Edge Style                                                                   |
|-------------------|----------|------------------------------------------------------------------------------|
| Synchronous call  | 同步调用 | `endArrow=block;endFill=1;strokeColor=#808080;` (solid line, filled arrow)   |
| Asynchronous call | 异步调用 | `endArrow=open;endFill=0;strokeColor=#808080;` (solid line, open arrow)      |
| Return message    | 返回消息 | `dashed=1;endArrow=open;endFill=0;strokeColor=#808080;` (dashed, open arrow) |
| Self-call         | 自调用   | Loop-back edge on same lifeline using waypoints                              |

#### Activation bar style
```
rounded=0;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;
```
Width: 16px. Height varies by activity duration.

#### Medical sequence conventions

- Use system abbreviations as participant names: HIS, LIS, PACS, EMR, ESB, CDR
- Label messages with HL7/FHIR names when applicable (e.g., `ADT^A01`, `Patient/123`, `Bundle`)
- Return messages should include response status (e.g., `ACK^A01`, `200 OK`, `OperationOutcome`)

### ER Diagram Rules (实体关系图)

#### Entity (实体)

Use swimlane + text cell to create standard ER entity boxes:

```xml
<mxCell id="ent1" value="Patient" style="swimlane;fontStyle=1;startSize=26;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Microsoft YaHei;fontSize=12;collapsible=0;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="200" height="160" as="geometry"/>
</mxCell>
<mxCell id="ent1a" value="🔑 patient_id: VARCHAR(36)&#10;name: VARCHAR(100)&#10;gender: CHAR(1)&#10;birth_date: DATE&#10;🔗 org_id: VARCHAR(36)" style="text;align=left;verticalAlign=top;spacingLeft=4;spacingRight=4;overflow=hidden;whiteSpace=wrap;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Consolas;fontSize=11;" vertex="1" parent="ent1">
  <mxGeometry y="26" width="200" height="134" as="geometry"/>
</mxCell>
```

#### Attribute markers

- 🔑 = Primary Key (PK)
- 🔗 = Foreign Key (FK)
- One attribute per line, format: `name: TYPE`, separated by `&#10;`
- Use `fontFamily=Consolas` for attribute text (monospace readability)

#### Relationship cardinality

| Cardinality  | Source Label | Target Label           |
|--------------|--------------|------------------------|
| One-to-One   | 1            | 1                      |
| One-to-Many  | 1            | N                      |
| Many-to-Many | M            | N (use junction table) |

- Identifying relationship: solid edge
- Non-identifying relationship: `dashed=1` edge
- Place cardinality labels near source/target using edge label positioning

#### Medical ER naming conventions

- Entity names: English PascalCase — Patient, Encounter, Observation, DiagnosticReport
- Attribute names: English snake_case — patient_id, birth_date, encounter_type
- FK pattern: `{referenced_entity}_id`
- Common medical entities: Patient, Encounter, Observation, DiagnosticReport, Medication, MedicationRequest, Procedure, Organization, Practitioner, Location, Condition, AllergyIntolerance

### Gantt Chart / Timeline Rules (甘特图/时间轴)

#### Capability boundary

draw.io is **NOT** a native Gantt chart tool. It lacks automatic date axes, dependency arrows, and critical path calculation.

| Complexity | Recommendation |
|-----------|---------------|
| ≤15 tasks, no dependencies | ✅ Use draw.io with the manual construction method below |
| 16–30 tasks with dependencies | ⚠️ Consider Mermaid Gantt (can be imported into draw.io) |
| 30+ tasks, resource allocation | ❌ Use MS Project, GanttProject, or dedicated PM tools |

#### Manual Gantt construction in draw.io

1. **Header row**: Create a horizontal row of text cells for time divisions (months/weeks/sprints)
   - Style: `text;fontSize=11;fontStyle=1;fontFamily=Microsoft YaHei;fontColor=#333333;align=center;fillColor=#e8edf2;strokeColor=#9eafc0;`
   - Width per time unit: 100–120px

2. **Task rows**: Left column = task name (text cell, left-aligned); Right = horizontal bar (rounded rect)
   - Task name style: `text;fontSize=11;fontFamily=Microsoft YaHei;fontColor=#333333;align=left;`
   - Bar style: map to semantic colors by phase:
     - 规划阶段: **Base** 莫兰迪灰蓝
     - 执行阶段: **Core** 清豆绿
     - 验收/上线: **Active** 极地蓝
     - 延期/风险: **Alert** 淡樱粉
   - Bar width = number of time units × unit width

3. **Milestones**: Use diamond shapes at key dates
   - Style: `rhombus;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Microsoft YaHei;fontSize=10;`
   - Size: 20×20px

4. **Layout**: Tasks stacked vertically with 10px gaps; time axis horizontal at the top

## Medical IT Architecture Patterns

When generating architecture diagrams for medical institutions, reference these proven patterns and apply the Semantic Color System accordingly.

### Pattern 1: Integration Engine (院内集成平台)

```
[HIS] [LIS] [PACS] [EMR] [护理] → [集成引擎 ESB/MQ] → [CDR 临床数据中心]
```

- Source systems: **Base** 莫兰迪灰蓝
- Integration engine: **Core** 清豆绿
- CDR/Data center: **Active** 极地蓝
- Applicable: 互联互通评测、院内系统集成

### Pattern 2: Internet Hospital Dual-zone (互联网医院双域)

```
公网域(患者端App) ↔ DMZ(API网关/鉴权中心) ↔ 内网域(HIS核心业务)
```

- Public zone: **External** 浅丁香紫 (dashed borders)
- DMZ/Gateway: **Alert** 淡樱粉
- Internal zone: **Core** 清豆绿
- Applicable: 互联网医院合规架构

### Pattern 3: Trusted Data Space (可信数据空间)

```
数据源 → 采集集成 → 核心治理层(数据治理+数据服务+数据沙箱+存储) → 应用服务 ↔ 外部交互
侧栏: 安全保障(身份认证/访问控制/隐私计算/脱敏/审计)
```

- Applicable: 健康医疗数据空间、数据要素流通

### Pattern 4: Medical Group (集团化医院/医共体)

```
总院(数据中心/主HIS) ↔ [分院1] [分院2] [分院3] ↔ [社区卫生中心1] [社区卫生中心2]
```

- Hub: **Core** 清豆绿
- Branch hospitals: **Base** 莫兰迪灰蓝
- Community centers: **Base** 莫兰迪灰蓝 (smaller nodes)
- Applicable: 医联体/医共体、县域医共体

### Pattern 5: Five-level EMR (五级电子病历)

```
采集层 → 存储层 → 共享层 → 利用层 → 智能层
```

- Each level as a horizontal swimlane, color gradient from Base to Core to Active
- Applicable: 电子病历系统评级

## Medical Shape Quick-reference

When generating medical IT diagrams, use these domain-appropriate shapes instead of generic rectangles:

| Scenario | draw.io Style / Shape | Notes |
|----------|----------------------|-------|
| 数据库/数据湖 | `shape=cylinder3;size=10;` | Cylinder is the universal DB symbol |
| 消息队列 (MQ) | `rounded=1;` + label "✉ MQ" | Or search `shape=mxgraph.aws4.sqs` for AWS style |
| API 网关 | `shape=hexagon;` | Hexagon conveys routing/gateway |
| 防火墙/安全网关 | `shape=mxgraph.cisco.firewall;` | Use `search_shapes` for cisco.firewall |
| 云平台 | `shape=cloud;` | Cloud shape for SaaS/PaaS |
| 移动终端 (患者App) | `shape=mxgraph.android.phone2;` | Use `search_shapes` for phone/mobile |
| 医生/患者 (角色) | `shape=mxgraph.general.user;` | Person icon for actors |
| 浏览器/Web | `shape=mxgraph.mockup.containers.browserWindow;` | Browser window shape |
| 服务器/主机 | `shape=mxgraph.cisco.server;` | Server rack icon |
| 文档/报告 | `shape=mxgraph.flowchart.document;` | Document shape |
| 定时任务/调度 | `shape=mxgraph.flowchart.delay;` | Timer/clock shape |
| 监控/仪表盘 | `shape=mxgraph.flowchart.display;` | Display/monitor shape |

**Usage rule**: For standard diagram types (flowcharts, UML, ER, architecture), use basic geometric shapes. Only use extended shape libraries (`mxgraph.*`) when the diagram requires realistic/branded icons (Cisco, AWS, Android, etc.). Use `search_shapes` tool when available to find the exact shape key.

## XML reference

The essential diagram construction rules (color system, layout, font, complexity tiers) are fully embedded in this file and are **self-sufficient** for generating correct diagrams.

For the complete draw.io XML reference including advanced edge routing, containers, layers, tags, metadata, and dark mode colors, fetch the supplementary reference at:
https://raw.githubusercontent.com/jgraph/drawio-mcp/main/shared/xml-reference.md

**If the URL is unreachable**, proceed with the rules below. The following critical construction rules are duplicated here for resilience:

### Edge Construction (Critical)

Every edge `mxCell` **MUST** contain a child `<mxGeometry>` element. Self-closing edge cells are **INVALID** and will not render.

```xml
<mxCell id="e1" edge="1" parent="1" source="a" target="b" style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#808080;fontColor=#666666;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

Edge with waypoints (to avoid overlap):
```xml
<mxCell id="e2" edge="1" parent="1" source="a" target="c" style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#808080;fontColor=#666666;">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="300" y="150"/>
      <mxPoint x="300" y="350"/>
    </Array>
  </mxGeometry>
</mxCell>
```

- Use `edgeStyle=orthogonalEdgeStyle` for right-angle connectors (most common)
- Use `exitX`/`exitY` and `entryX`/`entryY` (values 0–1) to control connection points
- Leave at least **20px** of straight segment before target and after source for arrowheads

### Container Construction (Critical)

Set `parent="containerId"` on child cells. Children use **relative coordinates** within the container.

```xml
<mxCell id="grp1" value="Service Group" style="swimlane;startSize=30;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="400" height="300" as="geometry"/>
</mxCell>
<mxCell id="svc1" value="Auth Service" style="rounded=1;whiteSpace=wrap;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;" vertex="1" parent="grp1">
  <mxGeometry x="20" y="40" width="140" height="60" as="geometry"/>
</mxCell>
```

| Container Type    | Style                                           | When to Use                                                     |
|-------------------|-------------------------------------------------|-----------------------------------------------------------------|
| Invisible group   | `group;`                                        | No visible border, container has no connections                 |
| Swimlane (titled) | `swimlane;startSize=30;`                        | Visible title bar/header, container itself may have connections |
| Custom container  | Add `container=1;pointerEvents=0;` to any shape | Any shape acting as a container                                 |

- Always add `pointerEvents=0;` to container styles that should not capture connections
- Children must use coordinates **relative to the container origin**

## Troubleshooting

| Problem                            | Cause                                                                       | Solution                                                                                                |
|------------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| draw.io CLI not found              | Desktop app not installed or not on PATH                                    | Keep the `.drawio` file and tell the user to install the draw.io desktop app, or open the file manually |
| Export produces empty/corrupt file | Invalid XML (e.g. double hyphens in comments, unescaped special characters) | Validate XML well-formedness before writing; see the XML well-formedness section below                  |
| Diagram opens but looks blank      | Missing root cells `id="0"` and `id="1"`                                    | Ensure the basic mxGraphModel structure is complete                                                     |
| Edges not rendering                | Edge mxCell is self-closing (no child mxGeometry element)                   | Every edge must have `<mxGeometry relative="1" as="geometry" />` as a child element                     |
| File won't open after export       | Incorrect file path or missing file association                             | Print the absolute file path so the user can open it manually                                           |

## CRITICAL: XML well-formedness

- **NEVER include ANY XML comments (`<!-- -->`) in the output.** XML comments are strictly forbidden — they waste tokens, can cause parse errors, and serve no purpose in diagram XML.
- Escape special characters in attribute values: `&amp;`, `&lt;`, `&gt;`, `&quot;`
- Always use unique `id` values for each `mxCell`

## Incremental Edit Protocol

When the user requests modifications to an **existing** `.drawio` diagram (e.g., "add a module", "move this", "change the color"), follow this protocol instead of regenerating from scratch:

### Read-Modify-Write Cycle

1. **Read** the existing `.drawio` file using the view/read tool
2. **Parse** the XML mentally — identify all `mxCell` ids, their positions, and parent-child relationships
3. **Modify only the affected cells**:
   - To **add** a node: create a new `mxCell` with an ID that does not conflict with existing IDs (use `new_1`, `new_2`, etc. or descriptive IDs)
   - To **move** a node: change only its `x`/`y` in `mxGeometry`; do NOT change its `id` or `style`
   - To **delete** a node: remove its `mxCell` AND all edges where it appears as `source` or `target`
   - To **restyle** a node: change only the `style` attribute; preserve everything else
4. **Preserve** all unmentioned cells — their IDs, positions, styles, and parent relationships MUST remain identical
5. **Write** the complete modified XML back to the same file path

### Conflict avoidance

- Before adding nodes, scan all existing `id` attributes to avoid collisions
- When adding nodes near existing ones, respect the Layout Guidelines (200px horizontal, 120px vertical gaps)
- When adding nodes to a container, recalculate the container’s `width`/`height` if the new child extends beyond current bounds
- After adding edges, verify that both `source` and `target` IDs exist in the file

### When to full-regenerate instead

- User says "redo", "start over", "重新画"
- The requested change affects >50% of existing nodes
- The diagram type changes (e.g., flowchart → sequence diagram)

## Diagram Quality Standards

### Label Format Standard (中英混排规范)

| Scenario                 | Format                                     | Example                |
|--------------------------|--------------------------------------------|------------------------|
| System with abbreviation | `{EN abbr}&#10;{Chinese name}` (two lines) | `HIS&#10;医院信息系统` |
| Technical component      | `{EN term} {Chinese}` (single line)        | `ETL 批量引擎`         |
| Pure Chinese context     | Chinese, max 8 chars per line              | `数据质量管理`         |
| Pure English context     | PascalCase or kebab-case                   | `AuthService`          |

- Wrap labels at **8 Chinese characters** or **16 Latin characters**
- Use `&#10;` for line breaks in non-HTML labels
- Abbreviations (HIS, LIS, PACS, EMR, FHIR, HL7, CDR, ESB) always UPPERCASE

### Diagram Metadata Watermark

Every generated diagram **MUST** include a metadata text cell at the bottom-right corner:

```xml
<mxCell id="meta" value="{图表名称} | {YYYY-MM-DD}" style="text;fontSize=9;fontColor=#b3b3b3;fontFamily=Microsoft YaHei;align=right;verticalAlign=bottom;" vertex="1" parent="1">
  <mxGeometry x="{max_x - 200}" y="{max_y + 30}" width="300" height="20" as="geometry"/>
</mxCell>
```

- Replace `{max_x}` and `{max_y}` with the rightmost and bottommost coordinates of diagram content
- Replace `{YYYY-MM-DD}` with the current date
- This enables traceability for compliance audits

### Pre-delivery Checklist

After generating any diagram, mentally verify ALL of the following before writing the file:

1. All nodes have non-empty labels (no blank `value`)
2. All edges have both `source` and `target` (no dangling connections)
3. Semantic Color Palette consistently applied (no `#dae8fc` blue leakage)
4. No orphan nodes (every node has ≥1 connection, or is inside a container)
5. Title exists and is centered, `fontSize ≥ 18`
6. Color legend exists at bottom (for diagrams using 3+ semantic roles)
7. Metadata watermark exists at bottom-right
8. No node overlap (bounding boxes do not intersect)
9. Decision nodes in flowcharts have labeled branches (是/否)
10. Font is explicitly set on every cell (`fontFamily` present in style)

## Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "drawio", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (NLAH Gotchas)

1. **Self-closing edge cells** — `<mxCell ... edge="1" ... />` will NOT render. Every edge MUST have a child `<mxGeometry relative="1" as="geometry" />`.
2. **Missing root cells** — Forgetting `<mxCell id="0"/>` and `<mxCell id="1" parent="0"/>` produces a blank diagram with no error.
3. **XML comments in output** — Despite what template examples may show, NEVER include `<!-- -->` in generated XML. This violates well-formedness rules.
4. **Duplicate cell IDs** — Each `mxCell` must have a globally unique `id`. Reusing IDs causes random rendering failures with no clear error message.
5. **Node cramming at scale** — For diagrams with 25+ nodes, flat layout degrades rapidly. Enforce Complexity Tiers (see Layout Guidelines).
6. **draw.io default blue leakage** — If you see `#dae8fc` or `#6c8ebf` in your output, you are using upstream defaults instead of the Semantic Color System. Always cross-check.
7. **Edge arrowhead clipping** — If source/target nodes are too close (< 40px gap), orthogonal edge router places bends that clip arrowheads. Increase node spacing or add explicit waypoints.
