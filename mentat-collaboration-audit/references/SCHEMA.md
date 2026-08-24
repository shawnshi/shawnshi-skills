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
- 顺序指标要求事件已按时间排列；有跨文件事件时提供 ISO 8601 `timestamp`。等待事件在同一 `root_task_id + actor_id` 内缺失时间或发生回退时，重复等待与连续超时指标失败关闭为不可用。
- `actor_type` 使用 `root`、`subagent` 或 `runtime`。
- 缺失值保持缺失，不填 `0`、`unknown` 或虚构哈希。
- 不在事件中记录提示词正文、凭据、私人内容或完整业务载荷。

## 3. 专用事件字段

| `event_type` | 必需或关键字段 | 用途 |
|---|---|---|
| `wait`、`wait_agent` | `state_version`、`status`、`duration_ms`、`local_work_available` | 识别同状态重复等待和有本地工作时的阻塞 |
| `skill_load_candidate` | `actor_id`、`context_epoch`、`skill_name`、`skill_path_sha256` | 记录原始命令中出现的保守读取候选，不证明已完成全文载入 |
| `skill_load` | `actor_id`、`context_epoch`、`skill_name`、`skill_path_sha256`、`skill_sha256`、`skill_tokens`、`tokenizer` | 识别带正式回执的全文载入 |
| `retry` | 错误信封字段 | 识别盲重试、同签名超预算和 EOF 降级缺失 |
| `subagent_spawn` | `fork_turns`、`evidence_pointers`、`max_turns`、`halt_condition`、`output_schema` | 验证最小上下文和停止条件 |
| `approval_request` | `task_mode`、`action`、`target` | 统计只读任务的额外批准回合 |
| `write_attempt`、`write_commit` | `authorization_id`、`write_scope_sha256`、`authorization_scope_sha256` | 验证写入是否绑定有效授权 |
| `context_compacted` | `root_task_id`、`context_epoch` | 计算每个根任务的压缩次数 |
| `context_recovered` | `root_task_id`、`context_epoch`、`recovery_artifact_present`、`required_fields_verified` | 区分恢复制品存在与最小语义状态已经核验 |

技能重复载入的唯一键为：

```text
root_task_id + actor_id + context_epoch + skill_name + skill_sha256
```

跨回合、跨执行者或上下文压缩后的必要重读不计为重复。指纹回执只能证明相同内容已载入当前上下文，不能绕过每回合读取技能的要求。

正式回执由 `scripts/skill_load_receipt.py` 以 UTF-8 JSONL 追加。相同唯一键重复提交时返回成功但不追加；写入使用同目录排他锁、刷新和 `fsync`，锁竞争或已有文件非法时失败关闭。`skill_path_sha256` 对解析后的规范化绝对路径计算，事件中不保存原始路径。

`skill_tokens` 必须同时记录 `tokenizer`。本地回执统一使用 `cl100k_base`，用于同一口径下比较技能文本体积；它不是模型输入账单 Token。若计数器不可用则字段保持缺失，不得使用字符数估算。

候选载入与正式回执必须分开计数。`receipt_coverage` 的分母是 `skill_load_candidate`，分子是同一根任务、执行者、上下文 epoch、技能名称和 `skill_path_sha256` 下可配对的正式 `skill_load`；没有正式回执时不能使用当前文件 Token 反填历史事件。缺少路径哈希、内容哈希、Token 或 tokenizer 的记录进入 `unverifiable_load_count`，不得贡献正式载入数或 Token。

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

包装执行同时保留 `outer_status` 与 `nested_status`。外层显示 `Script completed`，但输出载荷以 `ParserError:`、Python traceback、明确非零退出码或嵌套工具错误开头时，标准事件的顶层 `status` 必须为 `error`，并保留有限 `error_category/error_signature`；不得保存原始错误正文。

当前稳定 `error_signature/outcome` 至少包括：`powershell_parser`、`process_permission`、`process_unavailable`、`patch_context`、`not_git_repo`、`search_path`、`tool_interface`、`unicode_decode`、`python_path`、`python_permission`、`python_dependency`、`python_data`、`python_validation`、`python_exception`、`nested_tool_error`、`script_failed`、`no_match` 和 `validation_guard`。其中 `no_match` 与预期 `validation_guard` 的 `executor_failure=false`、顶层 `status=ok`；它们仍进入 outcome 计数，但不得增加 `tool_failures`。分类只读取包装层最后一个实际 `Output:` 载荷并先移除 ANSI CSI，不扫描被打印的源码或历史日志。

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

Codex rollout 标准化先在调用处生成 `write_attempt`，只在对应输出被判定为成功时生成 `write_commit`。目标集合和载荷仅以 SHA-256 进入事件。授权回执通过 `call_id` 绑定，并至少包含 `authorization_id` 与 `authorization_scope_sha256`；缺失或摘要不一致时，提交保持未匹配。自然语言批准不得由标准化器自行解释成授权指纹。

日记回执只允许从实际 `diary_ops.py scope/replace-date` 调用的执行载荷中读取，并接受两种受限身份：`schema: diary-write-scope-v1`，或历史兼容的 `schema_version: 2` 且 `component: diary_ops`。批准必须是 `approval_request + ready_for_confirmation`；提交必须是 `write_commit + success`；`VALIDATION_FAILED` 仅生成写入尝试和 `validation_guard`，不得生成提交。原始 `target`、`message`、正文和命令不进入事件；目标最多转为哈希。嵌入回执与外部回执冲突时设置 `authorization_conflict=true`，保留两侧有限指纹并移除主绑定字段。

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
- `wait` 另报第三次及以后同状态超时的 `wait_gate_breach_count`，以及 `sequence_order_status`、同键时间回退数和缺失时间数；顺序未核验时相关指标为 `null`。
- `skill_load` 分开报告候选数、正式回执数和候选回执覆盖率。
- `authorization` 分开报告尝试数、提交数、未匹配提交率和证据状态。
- `context` 分开报告恢复制品存在覆盖率与 `required_fields_verified=true` 的语义恢复覆盖率。
- `limitations`：缺失字段、顺序和因果限制。

目录输入按行流式解析 JSONL 并执行最小事件信封门禁；缺少非空 `event_type/root_task_id` 的报告、回执或摘要 JSON 进入 coverage 问题，不能作为 `unknown` 组件自摄入。CLI 使用单遍流式聚合状态，只保留顺序键、计数器、指纹集合和计算精确 P95 所需的时延数组。

分析层的发现仍需包含 `id`、证据指针、事实、推断、置信度、替代解释、影响、动作、所有者、验证方法和授权类型。不要把聚合器输出直接当作因果结论。

## 8. 修改建议 canonical manifest

`scripts/report_pair.py` 消费的 manifest 至少包含：

```json
{
  "report_id": "collaboration-audit-7d-20260816-remediation-v1",
  "previous_report_id": null,
  "title": "协作审计整改复核",
  "recommendations": [
    {
      "id": "R-01",
      "finding_ids": ["F-01"],
      "action": "解析结构化授权和写入回执",
      "implementation_layer": "telemetry",
      "owner": "mentat-collaboration-audit",
      "status": "validated",
      "authorization": "approved",
      "validation": {
        "criterion": "冻结快照中的目标提交保留一致授权哈希",
        "result": "pass",
        "evidence": ["aggregate.fixed.json"]
      },
      "closure_reason": "",
      "closure_evidence": []
    }
  ]
}
```

`id` 使用稳定 `R-xx`，`finding_ids` 使用 `F-xx`。状态限定为 `not_started/in_progress/implemented/validated/blocked/superseded/rejected`；验证结果限定为 `not_run/pass/fail/blocked`。`validated` 必须对应 `pass` 且证据非空；`superseded/rejected` 必须给出关闭原因与证据。提供上一批 manifest 时，旧编号不能消失，同一编号的发现、动作、层级和所有者不能静默漂移。

成对回执记录 manifest、上一批 manifest、Markdown、HTML 和验证器 SHA-256，以及建议编号集合与 pair projection 哈希。两种格式必须同目录、同主干、从同一 manifest 生成；建议表可见字段不一致或 HTML 外链资源存在时阻断写入。

## 9. 生命周期钩子状态

等待钩子运行态只保存哈希后的会话／回合键、可比较状态指纹、相同超时计数和一次状态探针标记。压缩前状态包必须恰好包含 `objective`、`authorization_scope`、`completed_steps`、`output_paths`；`PreCompact` 运行态只保存状态 SHA-256、完成步骤数、输出路径数和 `required_fields_verified`。`SessionStart(source=compact)` 只有在同一会话状态包未变化时才返回正文并声明核验成功。运行态不得保存原始会话 ID、工具输入输出、提示词、凭据、状态包路径或业务正文。
