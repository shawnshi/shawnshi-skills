# 架构追溯矩阵

用矩阵把“为什么建”追溯到“如何验收”。每行只表达一个可验证的业务需求或风险控制目标。

| trace_id | 业务结果/风险 | 现状证据与差距 | 目标能力 | 系统/组件及责任 | 数据与权威源 | 接口/事件契约 | NFR/安全控制 | 交付阶段/依赖 | 验收方法与证据 | owner | status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `{{TRACE_ID}}` | `{{OUTCOME_OR_RISK}}` | `{{EVIDENCE_IDS_AND_GAP}}` | `{{CAPABILITY}}` | `{{COMPONENT_AND_RESPONSIBILITY}}` | `{{DATA_OBJECT_AND_SOURCE}}` | `{{INTERFACE_SCHEMA_VERSION_ERROR_HANDLING}}` | `{{MEASURABLE_NFR_OR_CONTROL}}` | `{{PHASE_AND_DEPENDENCIES}}` | `{{TEST_METHOD_THRESHOLD_EVIDENCE}}` | `{{OWNER}}` | `{{PROPOSED/VERIFIED/DEFERRED}}` |

## 产品适配补充表（仅售前/选型触发）

| requirement_id | 中立要求 | 候选产品与精确版本 | 适配证据 | 部署/许可条件 | 偏离 | PoC/弥补动作 | 承诺边界 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `{{REQ_ID}}` | `{{TESTABLE_REQUIREMENT}}` | `{{PRODUCT_VERSION}}` | `{{EVIDENCE_ID_AS_OF}}` | `{{CONDITIONS}}` | `{{NONE/PARTIAL/UNKNOWN}}` | `{{ACTION_AND_EXIT_CRITERIA}}` | `{{INCLUDED/EXCLUDED/ASSUMED}}` |

## 覆盖检查

- 不存在没有业务目标或风险来源的孤立系统模块。
- 不存在没有系统责任、数据权威源或验收方法的核心需求。
- 每个接口至少说明发起方、接收方、数据对象、版本、错误处理和责任归属。
- 每个关键 NFR 都有指标、单位、工作负载/环境、测试方法和责任人；不用“高可用”“高性能”代替。
- 延后项说明原因、风险承接人和重新准入条件，不用“二期考虑”结束。
