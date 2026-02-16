# Agent Browser: Web 执行层的“语义锚点”

<!-- 
@Input: URL, Actions (Click/Fill/Wait), Selectors (@refs)
@Output: Screenshots, Extracted Data, Execution Status
@Pos: [ACE Layer: Action] | [MSL Segment: Infrastructure]
@Maintenance: Monitor browser driver updates & selector stability patterns.
@Axioms: Snapshot-First | No Blind Retries | Semantic Consistency
-->

> **核心内核**：通过“坐标定位+语义快照”双冗余机制，将模糊的网页交互转化为高可靠的工程级执行指令。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 系统的外部触角，负责将抽象的导航意图翻译为精确的浏览器行为。
- **反向定义**: 它不是一个简单的爬虫，而是一个具备环境感知能力的交互代理。
- **费曼比喻**: 它像是一个戴着增强现实眼镜的机器人，不仅能看到网页，还能识别出哪些是按钮、哪些是输入框，并根据指令精准操作。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 负责处理 Web 实体（Elements, Forms, Network Requests），遵循 W3C 标准。
- **ACE 角色**: 在集群作业中充当 **Worker (执行者)**，负责物理环境的变更与数据回传。

## 2. 逻辑机制 (Mechanism)
- [Intent] -> [Snapshot Analysis] -> [Semantic Mapping] -> [Command Execution] -> [State Verification]

## 3. 策略协议 (Strategic Protocols)
- **语义优先 (Snapshot-First)**：任何操作前强制执行 snapshot，建立基于语义引用句柄的稳定操作环境。
- **失效自校准 (Feedback Loop)**：操作失败时自动触发二次快照分析，定位 DOM 异动根源并实时更新状态共识。
