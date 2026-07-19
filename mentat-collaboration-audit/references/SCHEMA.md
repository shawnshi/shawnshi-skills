# 协作审计事件与报告合同

只有在输入为结构化遥测、需要复算指标或用户要求 JSON 制品时读取本文件。自然语言审计不应为了套用 Schema 而伪造事件。

## 1. 根任务

`root_task_id` 表示从一项用户目标开始到最终答复完成的完整任务。自动续跑、工具回调和上下文压缩仍属于同一个根任务，不能拆成多个样本。

## 2. 通用事件

JSON 或 JSONL 中每条记录使用一个对象：

```json
{
  "schema_version": 2,
  "event_id": "evt-001",
  "timestamp": "2026-07-19T00:00:00Z",
  "root_task_id": "task-001",
  "actor_id": "root",
  "actor_type": "root",
  "event_type": "tool_call",
  "component": "executor",
  "operation": "read",
  "status": "ok",
  "duration_ms": 120,
  "input_tokens": 100,
  "output_tokens": 20
}
```

最低要求：

- 所有事件包含 `event_type` 和 `root_task_id`。
- 顺序指标要求事件已按时间排列；有跨文件事件时提供 ISO 8601 `timestamp`。
- `actor_type` 使用 `root`、`subagent` 或 `runtime`。
- 缺失值保持缺失，不填 `0`、`unknown` 或虚构哈希。
- 不在事件中记录提示词正文、凭据、私人内容或完整业务载荷。

## 3. 专用事件字段

| `event_type` | 必需或关键字段 | 用途 |
|---|---|---|
| `wait`、`wait_agent` | `state_version`、`status`、`duration_ms`、`local_work_available` | 识别同状态重复等待和有本地工作时的阻塞 |
| `skill_load` | `actor_id`、`context_epoch`、`skill_name`、`skill_sha256`、`skill_tokens` | 识别同一执行上下文中的重复全文载入 |
| `retry` | 错误信封字段 | 识别盲重试、同签名超预算和 EOF 降级缺失 |
| `subagent_spawn` | `fork_turns`、`evidence_pointers`、`max_turns`、`halt_condition`、`output_schema` | 验证最小上下文和停止条件 |
| `approval_request` | `task_mode`、`action`、`target` | 统计只读任务的额外批准回合 |
| `write_attempt`、`write_commit` | `authorization_id`、`write_scope_sha256`、`authorization_scope_sha256` | 验证写入是否绑定有效授权 |
| `context_compacted` | `root_task_id`、`context_epoch` | 计算每个根任务的压缩次数 |

技能重复载入的唯一键为：

```text
root_task_id + actor_id + context_epoch + skill_name + skill_sha256
```

跨回合、跨执行者或上下文压缩后的必要重读不计为重复。指纹回执只能证明相同内容已载入当前上下文，不能绕过每回合读取技能的要求。

## 4. 统一错误信封

执行、补丁和连接器失败使用相同核心字段：

```json
{
  "event_type": "retry",
  "component": "connector",
  "operation": "write",
  "attempt": 2,
  "error_category": "transport",
  "error_signature": "connector_eof",
  "retryable": false,
  "hypothesis_delta": "query remote state before replay",
  "changed_variable": "transport state",
  "side_effect_state": "unknown",
  "idempotency_key": null,
  "fallback": "status_query",
  "stop_reason": null
}
```

`error_category` 使用有限集合：`syntax`、`path`、`permission`、`dependency`、`policy`、`data`、`validation`、`transport`、`timeout`、`rate_limit`、`remote_unavailable`、`business_logic`、`unknown`。

`side_effect_state` 使用：`none`、`not_started`、`committed`、`rolled_back`、`unknown`。

重试规则：

- 重试前记录错误类别、稳定签名和单一可验证假设。
- 同一根任务、组件、操作和错误签名默认只允许一次重试；外部状态明确变化时才能开启新尝试。
- `connector_eof` 的只读操作可换新连接或缩小载荷一次；写操作必须先查远端状态或幂等记录。
- 写入副作用为 `unknown` 且没有状态查询或幂等键时，停止重放。

## 5. 子代理任务包与回包

任务包至少包含：

```json
{
  "objective": "核验指定证据面",
  "scope": ["file-a.jsonl:1-200"],
  "evidence_pointers": [
    {"path": "file-a.jsonl", "sha256": "...", "lines": "1-200"}
  ],
  "authorization": "read_only",
  "fork_turns": "none",
  "max_turns": 3,
  "halt_condition": "所有指定证据均已分类或明确缺失",
  "output_schema": "collaboration_subagent_v1"
}
```

只有任务包已包含全部任务约束时才使用 `fork_turns: none`；否则传递最少的近期回合。文件指针必须在子代理可访问的工作区中，临时复制仍受当前任务写入授权约束。

回包使用：

```json
{
  "status": "pass",
  "payload": {},
  "confidence": 0.95,
  "data_provenance": [],
  "turns_used": 1,
  "halt_condition_met": true,
  "stop_reason": "completed",
  "unresolved": []
}
```

## 6. 授权指纹

`write_scope_sha256` 对规范化后的动作、目标、载荷摘要和授权范围计算 SHA-256。`authorization_scope_sha256` 必须与之完全一致；目标或载荷变化会使原确认失效。

授权类别：

| 类别 | 处理 |
|---|---|
| 只读审计 | 不请求写入批准 |
| 用户已明确要求的范围内本地可逆编辑 | 不增加第二次确认 |
| 外部发送、发布、合并、删除或生产写入 | 目标或载荷未被当前指令明确绑定时，执行前确认 |
| 长期记忆、知识库或偏好写入 | 展示最终摘要、目标和指纹后确认 |
| 写入结果未知 | 先查远端状态；无法核实时停止 |

## 7. 聚合报告

`generate_final_report.py` 输出 `schema_version: 2`，包含：

- `coverage`：输入文件、解析文件、跳过文件、跳过记录和问题明细。
- `components`：调用、失败、实际耗时观察数、平均值、最近秩 P95 和 Token。
- `operational_metrics`：`wait`、`skill_load`、`retry`、`subagent`、`authorization`、`context`。
- `limitations`：缺失字段、顺序和因果限制。

分析层的发现仍需包含 `id`、证据指针、事实、推断、置信度、替代解释、影响、动作、所有者、验证方法和授权类型。不要把聚合器输出直接当作因果结论。
