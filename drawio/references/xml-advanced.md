# XML Advanced Features

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

### Multi-page Diagram

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

### Multi-page Example (Architecture & Data Flow)

```xml
<mxfile>
  <diagram id="logic" name="逻辑架构">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- Page 1 content here -->
      </root>
    </mxGraphModel>
  </diagram>
  <diagram id="dataflow" name="数据流图">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- Page 2 content here -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

### Semantic Arrow XML Snippets

**Primary Flow (Gray):**
```xml
<mxCell id="e1" edge="1" parent="1" source="s" target="t" style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#808080;strokeWidth=2;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

**Memory Read (Arctic Blue):**
```xml
<mxCell id="e2" edge="1" parent="1" source="s" target="t" style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#6c8ebf;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

**Memory Write (Dashed Blue):**
```xml
<mxCell id="e3" edge="1" parent="1" source="s" target="t" style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#6c8ebf;dashed=1;dashPattern=5 3;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

**Feedback Loop (Curved):**
```xml
<mxCell id="e4" edge="1" parent="1" source="s" target="t" style="edgeStyle=orthogonalEdgeStyle;curved=1;strokeColor=#808080;">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

### Multi-page rules

- Each `<diagram>` must have a unique `id` and descriptive Chinese `name`
- Cell IDs only need to be unique within each `<diagram>`, not globally
- The Semantic Color System, Font Standard, and Layout Guidelines apply to **ALL** pages
- For single-page diagrams, continue using `<mxGraphModel>` as root (no `<mxfile>` wrapper needed)