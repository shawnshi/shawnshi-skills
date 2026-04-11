# Semantic Color System (MANDATORY)

**This section is CONSTITUTIONAL — it overrides any color values found in upstream references.** When upstream references show `fillColor=#dae8fc;strokeColor=#6c8ebf` (draw.io default blue) or any other ad-hoc color, replace them with the semantic colors defined below.

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

### Flow Semantics (Connector Styles)

Apply these styles to edges to encode data movement and control logic.

| Operation | Stroke Color | Dash Pattern | Arrow Style | Rationale |
|-----------|--------------|--------------|-------------|-----------|
| **Primary Data Flow** | `#808080` | Solid | Standard | Main request/response chain. |
| **Memory Read** | `#6c8ebf` | Solid | Standard | Retrieving context from storage (Arctic Blue). |
| **Memory Write** | `#6c8ebf` | `5 3` (Dashed) | Standard | Storing/Updating state. |
| **Trigger / Control** | `#b85450` | Solid | Standard | Lifecycle control or alerts (Cherry Pink). |
| **Feedback / Loop** | `#808080` | Solid | Curved | Iterative reasoning or refinement loops. |

### Visual Style Support (Theme Overrides)

The skill supports professional themes via the `--style` flag. When a style is specified, override the Base/Core/Active/External colors as defined in the corresponding style reference:

- **Blueprint**: Background `#0a1628`, high-contrast cyan strokes (`#00FFFF`), monospace font.
- **Dark Terminal**: Background `#0f0f1a`, neon green strokes (`#00FF00`), SF Mono font.

### Iron Rules

1. **同类同构 (Homogeneous Coloring)**: Components of the same type MUST use the same semantic role color. If you have 5 microservices, ALL 5 use Core (清豆绿). No exceptions.
2. **Edges use Flow Semantics**: Color edges based on their operation type (Read/Write/Trigger). Fall back to medium gray (`strokeColor=#808080`) for general flows.
3. **Retina Quality**: All diagrams should be exported with scale 2.0 (200%) by default.
4. **Containers/swimlanes reuse the 6-color palette**: A swimlane grouping microservices uses Core; a swimlane grouping databases uses Active; a boundary around external systems uses External. Apply the semantic role of the dominant children.
5. **Trust boundary rule**: Internal trusted systems use solid fills (Base/Core/Active). External untrusted systems use External (浅丁香紫). This is a hard security-semantic distinction.
6. **When in doubt, use Base** (莫兰迪灰蓝). Never fall back to draw.io default blue `#dae8fc`.

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
`rounded=1;whiteSpace=wrap;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;`

**Database cylinder:**
`shape=cylinder3;whiteSpace=wrap;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;`

**External service:**
`rounded=1;whiteSpace=wrap;fillColor=#f3e5f5;strokeColor=#9673a6;fontColor=#666666;dashed=1;`

**Alert/error node:**
`rounded=1;whiteSpace=wrap;fillColor=#ffebee;strokeColor=#b85450;fontColor=#333333;`

**Legacy node:**
`rounded=1;whiteSpace=wrap;fillColor=#f5f5f5;strokeColor=#b3b3b3;fontColor=#999999;dashed=1;`

**Swimlane container (Core group):**
`swimlane;startSize=30;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;`

**Edge (all edges):**
`edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#808080;fontColor=#666666;`