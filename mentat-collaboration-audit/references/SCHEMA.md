# 协作审计事件与报告合同

只有在输入为结构化遥测、需要复算指标或用户要求 JSON 制品时读取本文件。自然语言审计不应为了套用 Schema 而伪造事件。

## 1. 根任务

`root_task_id` 表示一项用户目标对应的完整任务。自动续跑、工具回调和上下文压缩仍属于同一个根任务，不能拆成多个样本。最终答复本身不证明任务已通过验收；显式结局与验收连接见 §10，失败、阻塞、放弃和未完成任务仍保留。

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
| --- | --- | --- |
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

一般历史审计只消费既有回执，不要求每次读技能创建遥测。只有任务明确要求计量或确需现场采样，且当前授权覆盖采样和临时写入时，才由 `scripts/skill_load_receipt.py` 在隔离 scratch 中以 UTF-8 JSONL 追加正式回执；使用本次采样真实身份与时间，不追加历史证据文件或把新回执当作历史事实。新回执包含 `event_identity: occurrence`，`event_id` 表示一次真实载入，而不是上述业务键。可选 `--event-id`／`build_receipt(..., event_id=...)` 接收调用方为本次真实载入保存的稳定 ID；同一根任务、执行者下重放该 ID 且业务字段、候选绑定、Token 口径一致时返回成功但不追加，冲突则报错。省略 ID 会为本次新载入生成 UUID，不能用省略 ID 的再次调用重放旧交付。同业务键的两次真实载入必须使用不同 ID。写入使用同目录排他锁、刷新和 `fsync`，锁竞争或已有文件非法时失败关闭。`skill_path_sha256` 对解析后的规范化绝对路径计算，事件中不保存原始路径。

历史回执缺少 `event_identity: occurrence` 时，即使存在旧版按内容和 epoch 拼接的 `event_id`，也不能证明发生次数。历史记录仍可读取，不补造 ID 或载入次数；`append_receipt` 对调用方传入的旧格式回执保留原业务键幂等方式，但不把它升级成发生次数证据。新标准化候选带 occurrence 标记，旧候选不反填。聚合器仅对已标记的同根任务、执行者、事件类型和 ID 去交付重放；技能回执／候选冲突计入 `event_identity_conflict_count`，撤回首个版本的正式载入、配对与分组 Token 贡献，两个版本均不能证明真实发生。冲突载入保留一项不可核验观察，重复率、候选覆盖率与 Token 占比失败关闭。`record_count` 和组件统计仍表示输入记录数，不是去重后的发生次数。

`skill_tokens` 必须同时记录 `tokenizer`。本地回执统一使用 `cl100k_base` 和 `token_measurement_basis: skill_text`，用于同一口径下比较技能文本体积；它不是模型输入账单 Token。已分类的计数失败保留 `token_measurement_status: error` 与异常类型 `token_measurement_error_type`，Token 字段保持缺失；未分类异常向调用方传播，不得使用字符数估算。

候选载入与正式回执必须分开计数。可选 `--candidate-event-id`／`candidate_event_id` 将正式回执绑定到同一根任务、执行者、epoch、技能名称和路径哈希下的确切候选 ID；双方均具备发生身份时，按一对一上限计入 `occurrence_matched_candidate_count` 与 `occurrence_receipt_coverage`。显式绑定不能错配到其他候选。只有字段缺失时才允许未绑定配对；显式 `candidate_event_id` 必须是非空白字符串，其他类型、空串或空白串均不得贡献候选覆盖，并产生 `invalid_candidate_binding` coverage 问题，使 coverage 为 `partial`、严格 CLI 返回 2。

兼容字段 `verified_candidate_count/receipt_coverage` 先进行上述确切匹配，再将未绑定的正式回执与剩余同业务范围候选配对。存在后一类匹配时，`receipt_pairing_basis: business_key_upper_bound` 表示数量上限，不证明具体发生对应关系；否则为 `occurrence`。无正式回执时不能使用当前文件 Token 反填。缺少路径哈希、内容哈希、Token、tokenizer，或明确失败的载入进入 `unverifiable_load_count`，不得贡献正式载入数或 Token。

`skill_load_count` 保留字段完整的正式回执观察数，已识别的重放只计一次；其中 `occurrence_load_count` 才有真实发生身份，余下为 `unverified_occurrence_count`。`observed_duplicate_load_count` 只统计具备发生身份的子集；存在未核验身份、非法载入或交付冲突时，整体 `duplicate_load_count/duplicate_load_rate` 为 `null`。必须同时披露候选与发生身份覆盖，不能把已覆盖子集的重复率推广到全部历史。`loaded_tokens_by_tokenizer` 分口径保存文本观察体积；混合 tokenizer 或交付冲突时 `loaded_tokens` 为 `null`。旧格式观察体积不证明真实载入总量。

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

重试计量不把字段缺失当作行为指责。只有非空且非 `unknown` 的错误类别、非空签名、显式 `hypothesis_changed: false` 和非空 `retry_evidence` 证据指针同时存在，并且没有非空假设变化描述时，才计入 `blind_retry_count`。类别、签名和非空 `hypothesis_delta` 或 `changed_variable` 齐备且不与显式标志冲突时，计入 `rationale_recorded_retry_count`，仅证明记录了理由，不证明理由正确。`hypothesis_changed: false` 与变化描述并存属于冲突；冲突、缺失、空白或类型错误进入 `unverified_retry_count`，冲突另计 `conflicting_retry_evidence_count`。`blind_retry_rate = blind / (blind + rationale_recorded)`，分母为零时是 `null`；必须同报 `retry_classification_coverage = (blind + rationale_recorded) / retry_count`。聚合器不解析自然语言来推断假设是否实际变化，也不替代对指针内容的审查。

已声明发生身份的技能回执、候选或输入 Token 计量出现同 ID 语义冲突时，进入 coverage 的 `event_identity_conflict`；结构化 `hypothesis_changed: false` 与非空变化字段并存，或错误类别别名 `error_category/error_type/failure_type` 的非空值不一致时，进入 `conflicting_retry_evidence`。两者均使 coverage 为 `partial`，严格 CLI 返回 2；完全一致的重放不是错误。历史字段缺失、写入结果未知或 Token 口径不兼容仍是合法输入，只产生未核验或 `null` 指标，不单独触发严格错误。

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

`write_commit_event_count` 是提交类记录数；`write_commit_count` 是其中没有明确矛盾状态的已确认提交数。历史 `write_commit` 类型本身可作为提交声明，但显式 `status/outcome` 不是 `ok/success/completed`，或显式 `side_effect_state` 不是 `committed` 时，不得作为已确认提交。匹配要求授权 ID 满足标准化器既有格式 `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`、合法的 64 位小写十六进制 SHA-256、两个范围哈希逐字相同且无授权冲突；未知或非法冲突标志也不能通过匹配。

意图只有结构化 `side_effect_state: none/not_started/rolled_back`，或存在相同 `root_task_id + actor_id + call_id` 的已确认提交时，才具有可核验结果。失败状态本身不证明没有写入；缺少关联键不得猜配。标准化器仅对结构化 `write_rejected` 回执记录 `not_started`，普通工具失败保持结果缺口。

`authorization_evidence_status` 使用以下新状态（旧聚合结果不自动重写）：

- `no_write_intent_observed`：输入覆盖完整，未观察到写入事件；不是“现实中没有写入”的证明。
- `attempts_without_confirmed_commit`：存在意图但没有确认提交，且已有结构化无写入／回滚结果。
- `outcome_uncertain`：输入覆盖非完整或未知，或仍有缺失／矛盾／未知结果；即使部分提交匹配也不能刷绿。
- `confirmed_commits_matched`：结果均可核验且确认提交的授权指纹均匹配。
- `confirmed_commits_unmatched`：结果均可核验但至少一项确认提交未匹配；不能直接等同实际越权。

`uncertain_write_outcome_count` 保留未核验结果的观察数，`unmatched_write_rate` 只用确认提交作分母。存在结果未知时仍保留确认提交及未匹配计数，不以总体状态覆盖证据。

日记回执只允许从实际 `diary_ops.py scope/replace-date` 调用的执行载荷中读取，并接受两种受限身份：`schema: diary-write-scope-v1`，或历史兼容的 `schema_version: 2` 且 `component: diary_ops`。批准必须是 `approval_request + ready_for_confirmation`；提交必须是 `write_commit + success`；`VALIDATION_FAILED` 仅生成写入尝试和 `validation_guard`，不得生成提交。原始 `target`、`message`、正文和命令不进入事件；目标最多转为哈希。嵌入回执与外部回执冲突时设置 `authorization_conflict=true`，保留两侧有限指纹并移除主绑定字段。

授权类别：

| 类别 | 处理 |
| --- | --- |
| 只读审计 | 不请求写入批准 |
| 用户已明确要求的范围内本地可逆编辑 | 不增加第二次确认 |
| 外部发送、发布、合并、删除或生产写入 | 目标或载荷未被当前指令明确绑定时，执行前确认 |
| 长期记忆、知识库或偏好写入 | 展示最终摘要、目标和指纹后确认 |
| 写入结果未知 | 先查远端状态；无法核实时停止 |

## 7. 聚合报告

`generate_final_report.py` 保留 `schema_version: 2`，新增 `metric_semantics_version: 2` 明确本次四项指标修正。缺少该标志的旧报告仍可验证和读取，但属于旧口径，不能从旧数字推导新版的发生次数、盲重试、授权或 Token 结论。验证器对新标志校验对应计数、分母、空值与状态关系；数值 Token 占比还必须与技能节的零未核验、零非法、零冲突证据及非零发生／计量观察一致，分子不得超过分母；不改写旧报告，不接受未识别的口径版本。报告包含：

- `coverage`：输入文件、解析文件、跳过文件、跳过记录和问题明细。
- `components`：调用、失败、实际耗时观察数、平均值、最近秩 P95 和 Token。
- `operational_metrics`：`wait`、`skill_load`、`retry`、`subagent`、`authorization`、`context`。
- `wait` 另报第三次及以后同状态超时的 `wait_gate_breach_count`，以及 `sequence_order_status`、同键时间回退数和缺失时间数；顺序未核验时相关指标为 `null`。
- `skill_load` 分开报告候选数、正式回执数和候选回执覆盖率。
- `authorization` 分开报告尝试数、提交数、未匹配提交率和证据状态。
- `context` 分开报告恢复制品存在覆盖率与 `required_fields_verified=true` 的语义恢复覆盖率。
- `limitations`：缺失字段、顺序和因果限制。

`context.skill_input_token_share` 仅在以下条件全部成立时计算：输入 coverage 为 `complete`；每项正式载入都有无冲突的发生身份；技能和输入计量均显式声明同一个 tokenizer 及 `token_measurement_basis: model_input`；按 `root_task_id + actor_id + token_scope_id` 精确对齐；每个范围恰好一项非负整数输入计量；输入记录同时声明 `skill_tokens_included: true` 与 `skill_load_coverage_complete: true`。这些标志是计量方对完整范围及包含关系的证据声明，不能为取得数值而手工补填。技能总量不得超过对应范围输入总量，总分母必须大于零；混合 tokenizer、范围缺失、多项输入计量、别名计数矛盾等均失败关闭。发生 ID 标记下的输入计量重放只计算一次。显式 `token_measurement_status` 非 `ok` 的输入计量不得贡献占比分母；普通工具执行 `status: error` 不等于计量失败。输入计量交付指纹包含 `token_measurement_status` 和 `token_measurement_error_type`，同 ID 的状态或异常类型变化按 `event_identity_conflict` 处理。历史计量状态字段缺失保持未知，不补造字段，也不单独否定其他兼容证据。

计算成立时保存 `skill_input_token_share_numerator/denominator`、`compatible_scope_count` 和占比。否则占比与两个操作数均为 `null`，`skill_input_token_share_reason` 给出缺口，`skill_input_token_share_coverage` 为 0（无输入观察时为 `null`）。`input_measurement_observation_count` 始终披露观察数。`skill_text` 的本地计量不会满足此合同；标准化器不得从模型名称猜 tokenizer 或替账单补齐口径。文本体积、账单 Token、成本分开报告，不输出估算节省额。

目录输入按行流式解析 JSONL 并执行最小事件信封门禁；缺少非空 `event_type/root_task_id` 的报告、回执或摘要 JSON 进入 coverage 问题，不能作为 `unknown` 组件自摄入。CLI 使用单遍流式聚合状态，只保留顺序键、计数器、指纹集合和计算精确 P95 所需的时延数组；可选协作分析另保留紧凑的有效注释投影与身份指纹，不保留全部普通事件或原始正文。

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

## 9. 生命周期钩子状态（仅 Codex 适配）

仅在宿主实际提供对应 Hooks 能力且任务需要时适用，接线与生效证据见 [CODEX-HOOKS.md](CODEX-HOOKS.md)。Pi 不凭脚本、安装或配置推定生效；这些字段不是一般审计的新增遥测要求。

等待钩子运行态只保存哈希后的会话／回合键、可比较状态指纹、相同超时计数和一次状态探针标记。压缩前状态包必须恰好包含 `objective`、`authorization_scope`、`completed_steps`、`output_paths`；`PreCompact` 运行态只保存状态 SHA-256、完成步骤数、输出路径数和 `required_fields_verified`。`SessionStart(source=compact)` 只有在同一会话状态包未变化时才返回正文并声明核验成功。运行态不得保存原始会话 ID、工具输入输出、提示词、凭据、状态包路径或业务正文。

## 10. 可选协作证据连接（analysis version 1）

该合同仅消费调用方显式提供的既有结构化注释，不是采集 API、历史回填要求或自动分类器。不改变 `schema_version: 2`、`metric_semantics_version: 2` 及既有指标字段。聚合结果新增可选顶层 `collaboration_analysis`，内部 `analysis_version: 1` 独立演化。既有报告验证器仍验证原有字段并兼容此扩展，但不认证新分析内容；新注释的结构与确定性语义在聚合入口验证，保存后篡改扩展字段不在旧验证器覆盖内。

新事件的公共信封：

```json
{
  "event_type": "collaboration_annotation",
  "event_identity": "occurrence",
  "event_id": "synthetic-outcome-1",
  "root_task_id": "synthetic-task-1",
  "annotation": {
    "kind": "outcome",
    "provenance": "reviewer",
    "evidence": ["synthetic-events.jsonl:1-3"],
    "result": "success",
    "lifecycle": "settled",
    "lifecycle_source": "runtime_settled",
    "lifecycle_evidence": ["synthetic-runtime.jsonl:3"],
    "acceptance": "passed",
    "acceptance_evidence": ["synthetic-acceptance.json#criterion-1"],
    "deliverable_id": "synthetic-deliverable-1",
    "outcome_version": 1
  }
}
```

此示例完全合成，不是实际会话或验收证明。生产注释必须引用已授权的真实来源；不得为了得到成功率手工补造 settled、passed、比较条件或来源。

### 公共约束

- `annotation` 是封闭字段对象，`kind` 只允许下表五类；不保存提示词、错误正文、原因散文或人格描述。`provenance` 仅为 `user/runtime/reviewer`，表示注释出处角色，不等同已认证身份。
- `evidence` 为非空指针字符串数组；指针格式为无空白的 `source:line[-line]` 或 `source#stable-anchor`。来源名应对应已授权快照或稳定制品，不含私人正文；需要哈希验证时在来源回执中核验。聚合器不打开指针，也不判断被引用内容是否支持标签。
- 新事件的根任务、事件 ID 与专用 ID／cohort／失败签名使用 `[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}`；不把原因散文塞进 ID。版本字段必须是正整数，布尔、浮点、字符串和零均非法。没有输入比例、时长或总量字段，分子、分母全部从有效观察复算。
- `root_task_id + event_id` 定义一次新注释的发生身份，不按 actor 拆分。`annotation` 完全一致的交付重放只保留一次；时间戳或其他传输元数据不参与语义指纹，不用于推定先后。同身份内容冲突时撤回该身份的贡献，相关根任务结局失败关闭；涉及整改／后续观察时相关 cohort 的复发率也失败关闭。
- 普通旧事件无注释是合法缺口，返回 unavailable／unknown／null，不触发严格错误。已声明新类型却缺必需字段、指针非法、标签非法或证据矛盾时，coverage 为 partial，`--strict` 返回 2；空输入仍按原 CLI 返回 1。新注释非法时，该根任务不能继续显示旧成功结论。

### 五类注释

| kind | 字段与闭集 | 计算边界 |
| --- | --- | --- |
| `outcome` | 必需 `result: success/failed/blocked/abandoned/incomplete/unknown`、`lifecycle: settled/in_progress/unknown`、`acceptance: passed/failed/not_run/unknown`。settled 另需 `lifecycle_source: runtime_settled` 与非空 `lifecycle_evidence`。passed／failed 验收另需 `acceptance_evidence`、所测试的 `deliverable_id`。可选 `outcome_version` | success 只有 settled + passed 同时成立才计数；提前宣布成功但验收未运行是合法 unknown，success + failed 验收是冲突。failed／abandoned 缺 settled 时为 unknown；blocked／incomplete 可为中间状态。生命周期来源可显式 unknown，但不能证明 settled |
| `intervention` | 必需 `reason: necessary_decision/new_requirement/information_completion/repeated_authorization/correction/recovery_nudge/unknown` | 仅统计有来源的标签，不从 `继续` 或批准次数推定目的；必要决策不等同浪费 |
| `rework` | 必需 `reason: changed_requirement/misunderstanding/execution/quality/recovery/unknown`，以及 `original_root_task_id`、`original_deliverable_id`、`revision_id` | 保存原任务／产物连接与原因覆盖；原任务未在输入中不自动补取。一次注释发生使用稳定事件 ID，不能通过新 ID 重放同一交付 |
| `remedy` | 必需 `remedy_id`、`remedy_version`、`failure_signature`、`cohort`、`implementation_validation: passed/failed/not_run/unknown` | 有 canonical manifest 时复用其稳定 `R-xx`；此事件是当前证据输入，不建立新长期台账。实现验证不表示运行收益 |
| `followup` | 必需同一组整改连接字段，以及 `exposure_id`、布尔 `after_remedy`、`comparability: comparable/not_comparable/unknown`、`recurrence: observed/not_observed/unknown`、`operational_validation: passed/failed/not_run/unknown` | `after_remedy` 是由证据支持的先后断言，不是聚合器猜测的时间关系；缺可信关系可显式 false，并排除出后续分母。unknown 可比性／观察不补零 |

outcome 多条完全一致声明合并；不同声明只有全部提供唯一 `outcome_version` 时才选最大版本，不使用文件顺序或未核验时间。相同版本内容不同，或未排序的多个声明，即使只改了证据，也要求调用方澄清，不能猜赢家。

整改使用 `remedy_id + remedy_version + failure_signature + cohort` 精确连接，缺任一匹配时不可用，不跨版本／复杂度 cohort 汇总。相同连接有不同整改声明时冲突；同连接、同 `exposure_id` 的相同观察只计一次，即使交付 ID 不同，观察内容不同则该 cohort 冲突。不同 cohort 的数字不合成为全局绩效。

### 输出口径与可用性

- `status` 区分结构化支持 available、无支持 unavailable、新注释问题 partial；各子节另给可用状态。available 只表示存在部分有效注释，不表示任务全部完成或修复有效。
- `source_coverage_status`、`scope: supplied_records_only`、`evidence_sources` 描述当前输入范围。`annotation_observation_count` 去除已识别重放，保留非法／冲突身份；无有效身份的非法记录仅计输入观察，不能证明发生次数。`valid_annotation_count/annotation_coverage` 表示结构有效且无身份冲突的子集，不保证所有语义连接成立。
- `task_outcomes` 保留所有输入根任务。`accepted_success_rate = accepted_success_count / success_denominator`，分母为已分类的 success、failed、blocked、abandoned、incomplete 根任务数；unknown／conflict 不混入已知分母，但保留在状态计数和 `root_task_count` 中。必须同时展示 `classification_coverage = classified_task_count / root_task_count`；分母为零时为 null，禁止仅展示成功率。
- `user_interventions/rework` 提供有效注释数、非 unknown 的 labeled count、unknown reason count 与 `label_coverage`；全 unknown 或无注释时标签分析 unavailable。这里不是所有用户消息／修订的覆盖率，不估算未注释历史。
- `remediation_followup.cohorts` 提供 supplied exposure count、可比后续 exposure count、已观察复发 denominator。复发率只用具有整改连接、after_remedy 为 true、comparable 且 recurrence 非 unknown 的唯一 exposure。无此观察时 recurrence count／rate 为 null；`observation_coverage` 用可比后续暴露作分母。冲突 cohort 撤回可用分母，保留原始 supplied count 与 conflict 状态。
- `operational_validation_pass_count` 只计已连接的可比后续暴露中的 passed 声明；分母参看 comparable exposure count，不能叫改善率。实现单测通过、未复发或现场验收通过都不单独支持因果收益。

八个视角的替代解释、维护／使用动作与证伪条件见 [ANALYSIS.md](ANALYSIS.md)。其余自主性、委派、上下文负担与实验判断保持来源约束下的定性分析；本扩展不新增自动 NLP、注意力计时、并行加速比或任意综合评分。
