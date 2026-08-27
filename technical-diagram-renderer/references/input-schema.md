# 输入契约

本文定义 `scripts/render-diagram.py` 接受的公共输入。命令行中的 `<diagram-type>` 决定图型；JSON 必须是 UTF-8 对象。统一入口依次执行语义规范化、自动布局、SVG 生成和验证。未知字段、未知类型、非法枚举、非有限数值、重复 ID 和悬空关系都应视为错误，不得静默回退。

## 图型与支持层级

| canonical `<diagram-type>` | 输入模式 | 当前语义边界 |
|---|---|---|
| `architecture` | `components` + `connections`，或通用 `nodes` + `arrows` | 组件关系；不推导部署、网络或接口事实 |
| `data-flow` | `external_entities` + `processes` + `data_stores` + `flows`，或通用模式 | 外部实体、处理、数据存储和有标签数据流；不是完整分层 DFD 规范 |
| `flowchart` | `steps` + `flows` | 开始、结束、处理、判断；不实现完整 BPMN、泳道和补偿语义 |
| `sequence` | `participants` + `messages` | 参与者、生命线、同步/异步/返回消息；不实现 `alt`、`opt`、`loop` 等组合片段 |
| `state-machine` | `states` + `transitions` | 初始、普通、终止状态及转换；不验证完整状态机可达性或 UML 守卫语法 |
| `er-diagram` | `entities` + `relationships` | 实体、属性、PK/FK 文本和基数标签；不承诺 Crow's Foot、Chen 或数据库 DDL 等价性 |
| `use-case` | `actors` + `use_cases` + `relations` | 参与者、用例、关联/include/extend；不实现完整 UML 泛化语义 |
| `timeline` | `events` | 有序事件与时间标签；不等同于甘特图或项目排程引擎 |

所有 canonical 类型也兼容通用 `nodes` + `arrows`；同一次输入不要混用语义集合和通用集合。

## 图型别名

| Canonical | 兼容别名 |
|---|---|
| `architecture` | `system-architecture`、`agent-architecture`、`agent`、`memory`、`network-topology`、`comparison`、`comparison-matrix` |
| `data-flow` | `dataflow`、`dfd` |
| `flowchart` | `flow-chart`、`process-flow` |
| `sequence` | `sequence-diagram` |
| `state-machine` | `statechart`、`state-diagram` |
| `er-diagram` | `er`、`erd`、`entity-relationship` |
| `use-case` | `usecase`、`use-case-diagram` |
| `timeline` | 无 |

别名只做输入兼容。例如 `comparison` 仍按架构节点关系处理，不提供表格单元格、权重或评分计算语法。新输入优先使用 canonical 名称。

## 公共顶层字段

| 字段 | 类型 | 要求 |
|---|---|---|
| `title` | string | 可选；简短、事实性标题 |
| `subtitle` | string | 可选；不确定性或范围可放在此处 |
| `style` | integer/string | 可选；仅 1–7 或脚本声明的精确样式名，默认 1 |
| `width`, `height` | finite number | 可选；必须大于 0 |
| `containers` | array<object> | 可选；分组或层级容器 |
| `nodes`, `arrows` | array<object> | 通用模式使用；必须是对象数组 |
| `layout` | object | 可选；通用节点图的自动布局设置 |
| `legend` | array<object> | 可选；使用两种及以上线型或颜色时建议提供 |
| `footer` | string | 可选；可用于来源、版本或“待确认”说明 |
| `style_overrides` | object | 可选；只接受渲染器白名单中的样式键和值，优先使用内置样式 |

所有坐标、尺寸、半径、透明度和路线点必须是有限数值；不得使用 `NaN`、`Infinity`、数字字符串或负尺寸。文本字段不得包含 XML 控制字符。颜色、滤镜、marker 和 dash 只能使用脚本允许的安全格式；禁止事件属性、`script`、`foreignObject`、外部 URL、`javascript:` 和任意 `url()`。

## 通用节点图

### 节点

```json
{
  "id": "clinical-data-platform",
  "kind": "rect",
  "x": 360,
  "y": 220,
  "width": 220,
  "height": 76,
  "label": "临床数据平台",
  "sublabel": "已确认范围",
  "type_label": "DATA"
}
```

- `id`：必填、非空、全图唯一。
- `kind`：可选，默认 `rect`。支持 `rect`、`double_rect`、`cylinder`、`document`、`folder`、`terminal`、`hexagon`、`circle_cluster`、`user_avatar`、`bot`、`speech`、`icon_box`、`diamond`、`circle`、`ellipse`、`actor`、`entity`、`state`、`initial`、`final`、`terminator`、`process`、`participant`、`data-store`、`use-case`、`timeline-event`、`milestone`。
- `x`, `y`：可省略一个或两个；缺少任一坐标的节点会进入自动布局。两者都存在时默认保留原坐标。
- `width`, `height`：矩形类节点必须大于 0；圆形节点可使用正数 `r`。
- `label`、`sublabel`、`type_label`：可选文本。长标签应主动换行或扩大节点，不依赖裁切补救。
- `container_id`：可选；用于把节点放入指定容器。兼容字段 `container`、`parent`、`group` 可匹配容器的 `id`、`name` 或 `label`，新输入优先使用稳定的 `container_id` → `containers[].id`。

### 关系

```json
{
  "source": "emr",
  "target": "clinical-data-platform",
  "source_port": "bottom",
  "target_port": "top",
  "flow": "data",
  "label": "标准化病历数据"
}
```

- 优先使用 `source`、`target` 引用节点 ID；两端必须存在。只有明确需要自由线段时才使用完整的 `x1/y1/x2/y2` 坐标端点。
- `source_port`、`target_port` 可为 `left`、`right`、`top`、`bottom`、`top-left`、`top-right`、`bottom-left`、`bottom-right`。
- `flow` 可为 `control`、`write`、`read`、`data`、`async`、`feedback`、`neutral`；兼容值 `main`、`api` 会归一为 `control`。
- `route_points` 是有限坐标对数组，例如 `[[240,180],[240,300]]`。人工路线也必须保持正交且不得穿过节点。
- `dashed`、`label`、`label_dx`、`label_dy`、`corridor_x`、`corridor_y` 是可选路由或标注提示，不得用来掩盖错误拓扑。

### 自动布局

```json
{
  "layout": {
    "auto": true,
    "direction": "TB",
    "horizontal_gap": 80,
    "vertical_gap": 100,
    "minimum_gap": 32,
    "preserve_aspect": true,
    "preserve_route_hints": false
  }
}
```

- `layout.auto: true` 会重排通用 `nodes` 中的全部节点；省略或为 false 时，只为缺少 `x` 或 `y` 的节点补齐布局。
- `layout.direction` 仅为 `TB`（上到下）或 `LR`（左到右）。间距字段必须是正的有限数值。
- `preserve_aspect` 默认 true；`preserve_route_hints` 默认 false。节点移动后默认清理旧的 `route_points`、`corridor_x` 和 `corridor_y`，避免沿用失效路线。
- 单个节点可用 `node.layout.auto: true` 明确允许重排。旧字段 `auto_place` 仅为兼容输入，新输入不再使用。
- 自动布局会补充缺失的尺寸、必要换行和箭头端口，但不会替代人工拓扑确认。它只处理通用 `nodes`，语义图集合使用各自适配器的布局。
- 固定容器空间不足时，布局器不会擅自改变容器尺寸；它会记录 `container_overflow` 警告并扩展画布以避免裁切。循环关系会稳定降级为同层布局，仍需人工检查阅读顺序。
- 布局器可产生内部 `_layout_stats`（包括放置、保留、循环、端口、路线提示、换行、重叠、容器溢出和画布警告）。该字段用于 QA，不应渲染到图中，也不应被当作业务输入。

### 容器和图例

容器使用唯一空间范围 `x/y/width/height`，可带 `label`、`subtitle`、`header_prefix` 或 `side_label`。容器用于视觉分组，不创建或改变节点关系。

图例项使用 `{ "flow": "data", "label": "数据流" }`。图例必须与实际箭头的颜色和虚实线一致。

## 原生语义输入

### Architecture

```json
{
  "components": [
    {"id": "portal", "label": "患者服务入口", "type": "channel"},
    {"id": "gateway", "label": "API 网关", "type": "edge"}
  ],
  "connections": [
    {"from": "portal", "to": "gateway", "label": "HTTPS", "flow": "control"}
  ]
}
```

`components[]` 至少包含唯一 `id` 和 `label`；可用 `type` 生成类型标签。`connections[]` 可用兼容字段 `relationships`，每条关系的两端必须引用已声明 component。

### Data flow

```json
{
  "external_entities": [{"id": "clinic", "label": "社区机构"}],
  "processes": [{"id": "validate", "label": "校验转诊申请"}],
  "data_stores": [{"id": "registry", "label": "转诊登记库"}],
  "flows": [
    {"from": "clinic", "to": "validate", "label": "转诊申请"},
    {"from": "validate", "to": "registry", "label": "有效记录"}
  ]
}
```

至少提供一个外部实体、处理或数据存储。每条 `flows[]` 都必须有非空 `label`。兼容字段 `externalEntities`、`dataStores` 仅用于旧输入，新输入使用 snake_case。

### Flowchart

```json
{
  "style": 1,
  "steps": [
    {"id": "start", "type": "start", "label": "开始"},
    {"id": "review", "type": "decision", "label": "资料完整？"},
    {"id": "correct", "type": "process", "label": "补充资料"},
    {"id": "end", "type": "end", "label": "完成"}
  ],
  "flows": [
    {"from": "start", "to": "review"},
    {"from": "review", "to": "end", "label": "是"},
    {"from": "review", "to": "correct", "label": "否"},
    {"from": "correct", "to": "review", "label": "重新提交"}
  ]
}
```

`steps[].type` 仅为 `start`、`end`、`process`、`decision`。必须至少有一个 start 和一个 end；decision 至少有两条出边。每条 `flows[]` 的 `from`、`to` 必须引用已存在的 step。

### Sequence

```json
{
  "participants": [
    {"id": "doctor", "label": "医生站"},
    {"id": "api", "label": "服务接口"}
  ],
  "messages": [
    {"from": "doctor", "to": "api", "type": "sync", "label": "提交请求"},
    {"from": "api", "to": "doctor", "type": "return", "label": "返回结果"}
  ]
}
```

`messages[].type` 仅为 `sync`、`async`、`return`，并按数组顺序从上到下排列。

### State machine

```json
{
  "states": [
    {"id": "initial", "type": "initial", "label": ""},
    {"id": "active", "type": "state", "label": "运行中"},
    {"id": "final", "type": "final", "label": ""}
  ],
  "transitions": [
    {"from": "initial", "to": "active", "label": "启动"},
    {"from": "active", "to": "final", "label": "关闭"}
  ]
}
```

`states[].type` 仅为 `initial`、`state`、`final`。transition 可用 `guard` 和 `action`，显示为 `[guard] / action`；脚本只格式化文本，不执行或证明守卫条件。

### ER diagram

```json
{
  "entities": [
    {
      "id": "patient",
      "label": "Patient",
      "attributes": [
        {"name": "patient_id", "key": "PK", "type": "string"}
      ]
    },
    {
      "id": "encounter",
      "label": "Encounter",
      "attributes": [
        {"name": "patient_id", "key": "FK", "type": "string"}
      ]
    }
  ],
  "relationships": [
    {
      "from": "patient",
      "to": "encounter",
      "from_cardinality": "1",
      "to_cardinality": "0..*",
      "label": "has"
    }
  ]
}
```

`attributes[]` 可为属性名字符串或对象；对象的 `key` 可为 `PK`、`FK`、`UK`、`PK/FK` 或省略。`cardinality` 可为单个显示字符串或 `[from,to]` 两项数组。基数是显示标签，不由脚本验证数据库约束。

### Use case

```json
{
  "actors": [{"id": "patient", "label": "患者"}],
  "use_cases": [{"id": "book", "label": "预约"}],
  "relations": [
    {"from": "patient", "to": "book", "type": "association"}
  ]
}
```

`relations[].type` 可为 `association`、`include`、`extend`。association 必须连接一个 actor 和一个 use case；include/extend 必须连接两个 use case。actor 可用 `side: left|right`；可选 `system` 定义系统边界。兼容字段 `useCases` 和 `relationships` 仅用于旧输入，新输入使用 `use_cases`、`relations`。

### Timeline

```json
{
  "events": [
    {"id": "kickoff", "date": "2026-09", "label": "项目启动"},
    {"id": "pilot", "date": "2026-12", "label": "试点验收", "description": "范围待确认"}
  ]
}
```

事件按输入顺序水平排列。`date`、`time` 或 `timestamp` 只作为显示文本，脚本不解释时区、日期逻辑或工期依赖；当前不支持垂直 timeline。

仓库中的 `fixtures/semantic-*.json` 提供每种 canonical 图型的可运行示例；它们是契约样例，不是业务事实模板。

## 最小通用示例

```json
{
  "title": "门诊数据流（已确认范围）",
  "style": 1,
  "nodes": [
    {"id": "emr", "x": 80, "y": 160, "width": 180, "height": 72, "label": "门诊医生站"},
    {"id": "platform", "x": 420, "y": 160, "width": 200, "height": 72, "label": "临床数据平台"}
  ],
  "arrows": [
    {"source": "emr", "target": "platform", "flow": "data", "label": "门诊病历"}
  ],
  "legend": [
    {"flow": "data", "label": "数据流"}
  ]
}
```
