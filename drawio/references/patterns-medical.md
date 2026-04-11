# Medical IT Architecture Patterns

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