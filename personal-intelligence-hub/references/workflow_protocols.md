# 分阶段执行协议

仅供父任务按 SKILL.md 的阶段路由读取指定节；不向代理展开。命令沿用 SKILL.md 的 run-scoped execution_cli_path 约定。现有字段合同仍以既有 JSON/schema/helper 为准。

## supplement

若 prepare 返回 `supplement_request_path`：读取 `references/subagent_prompts.json`，按 request 中每个 gap 的 `lane` 调用对应代理：

- `TechRadar`：通用技术；
- `HealthcareRadar`：医疗 AI 与医疗数字化；
- `Sentinel`：政策、支付、采购与竞对；
- `Ranger`：失败、漏洞、处罚与执行摩擦。

按 `execution_policy` 使用最小任务包启动代理：任务只传已登记请求路径、明确分派的 `gap_id`/`lane`、execution packet 的预算和停止条件。每个 worker 首先运行 run-scoped packet 绑定的 `scripts/supplement_agent.py context`；该帮助脚本在本地校验 request、manifest、prompt 与 lane slice 的路径和 SHA-256，只输出当前 gap 的紧凑上下文。代理不得直接展开完整 request、prompt config、candidate pool、history snapshot、其他 gap 的 slice 或脚本源码。运行时支持上下文继承控制时必须关闭完整会话历史继承。严格按 request 的确定性 `launch_plan` 执行：第一 wave 只运行 1 条 canary gap；若其为基础设施失败，停止后续 fanout 并进入 reconciler。canary 通过后，余下 gap 最多 3 个并行，不得把两个 lane 混入同一代理。已经分派的检索不得由根任务重复执行。

补检代理只在发现阻断时发送中间状态；其余情况在来源核验结束时固定 `completed_at`，只把动态字段写入 execution packet 授权的 draft 路径，随后运行 packet 绑定的 `scripts/supplement_agent.py finalize`。帮助脚本确定性装配静态哈希、`event_id`、coverage 与 provenance；成功后代理发送一次 `draft_ready` 控制消息（绝对路径与 SHA-256）并结束。`source_checked` 后禁止继续检索，必须在 `finalization.grace_seconds` 内完成上述收口。`verify-bound` 是受控文档访问探针：HTTP 成功本身不证明正文事实、发布日期或原始来源类型；空正文、登录页、软 404、Anubis 挑战页和不可识别文档记为 blocked，日期缺失/无效/超窗单独记为 `date_disqualified`，不回填窗口日期。正常代理仍可把实际读取的可识别文档、独立日期元数据和已有来源类型写入动态 draft。代理不得写最终路径；父任务必须用确定性 finalizer 验证全部 drafts，再逐文件原子提升并登记 aggregate。语义与红队代理另按对应阶段发送不含业务内容的有限里程碑心跳。

每个代理必须先处理绑定的基线候选，再补充检索；context 返回 `required_bound_candidate_urls` 时，必须在开放检索前逐个核验，并为每个 URL 保留 verified 或 blocked 终态。通过访问、日期、领域和来源质量门的绑定候选必须以相同 `candidate_id` 与 URL 重新登记到 `candidates`，以携带文章级 `source_type` 与 `event_identity`；deterministic finalizer 负责生成 `event_id`，不得因不知道哈希算法而省略。不得绕过基线直接做开放式搜索。所有运行时间戳必须来自实际时钟，不得填入整点占位或未来时间。当前资讯必须联网核验，优先监管、政府、公司公告、采购原文、论文、标准和项目主页。新闻与评论只作线索或独立佐证。HTTP 3xx 不是正文核验终态：仅沿 HTTP(S) Location 有界跟随最多 5 跳，保留原始 requested URL 与最终 final URL；只有最终落点取得可识别正文才算 verified。

`max_urls` 按访问次数（`access_log` 条目数）计数，不按唯一 URL 数计数；同一 URL 的正文复检同样消耗预算。首次访问时应读取并保留正文、日期和来源证据；`verify-bound` 只输出探针结果，不提供正文事实证明，若后续需要重读须预留预算，预算耗尽时排除未核验主张。帮助脚本在请求数超限或输入 URL 重复时于联网与写入前拒绝；finalize 超限时保留完整 draft，不得删去早期记录或改按唯一 URL 计数。

补检不得在同一 gap 内对同一 URL 的永久失败做重试；HTTP 永久响应在所有 gap 中都不得重试。若某次永久失败没有 HTTP 响应，且错误码明确指向本地 TLS、SSL、证书、协议或 curl 传输路径故障，另一 lane 可用不同访问方法做一次恢复核验；必须保留原失败、把聚合覆盖标为 `degraded` 并登记 cross-lane recovery，禁止同 lane、同方法或再次恢复。同一主机连续两次永久失败后必须切换到另一类优先来源，并把失败保留在 `access_log`，不得通过删除失败记录美化覆盖率。只有瞬时超时、限流或可重试 HTTP 状态可在轮次预算内重试；达到 gap 的合格增量或连续检索无增量时立即停止。

每个结果必须符合 `supplement-result/1.0`。代理只提供动态证据字段，帮助脚本装配并校验确定性字段：

- `run_id`、request SHA-256、baseline SHA-256、candidate pool SHA-256、`gap_id`、`lane` 由帮助脚本从已登记 packet 装配；
- 非空实际查询、逐次 `access_log`、候选及来源/日期/访问核验；访问记录同时保留 `requested_url` 与跳转后的 `final_url`，候选的请求 URL 必须匹配候选 URL 并对应 `verified` 日志；
- 从 `access_log` 派生且守恒的 attempted/succeeded/failed 覆盖计数；
- `confidence`、绑定 request/candidate pool/access log 哈希的 `data_provenance`；
- 1..max_turns 的已用轮次、停止条件是否满足、完成时间和状态。

`failure_kind` 使用封闭枚举并由 finalizer 规范化：任何 `degraded`/`failed` 结果都必须有规范化 `failure_kind` 与非空 `failure_reason`；初始化前失败为 `infrastructure` 且 `status=failed`；来源访问导致车道降级为 `source_access`；权威发布日期冲突、无效或超窗为 `published_at_conflict`，后二者必须 `status=degraded`。兼容别名只在帮助脚本内部归一化，正式结果不得写任意字符串。`completed`/`no_increment` 不得包含 failed coverage。只有 `infrastructure` 可登记零尝试、`turns_used=0`、`halt_condition_met=false` 及全空证据；其他失败必须保留真实查询与访问证据。

没有增量时返回 `no_increment` 与空候选，不得补写弱资讯。全部 gap drafts 齐备后验证、发布并登记：

```powershell
python -X utf8 scripts/run_daily.py finalize-supplement --manifest <run_manifest.json> --request <supplement_request.json> --draft <lane-1.draft.json> --draft <lane-2.draft.json>
```

若任一 gap 进入 `degraded_timeout` 或 `declare_lost`，读取已原子保存的逐 gap 状态，并用 reconciler 将成功 drafts 与缺失 gap 的基础设施失败回执一起登记为 degraded aggregate；不得只依赖 CLI stdout。reconciler 先在内存校验全部 gap 与发布目标，再写独立 `supplement_<gap_id>.failure.json`；不得覆盖失败或迟到的原始 draft/result，失败原因保留其路径与 SHA-256。收口回执中的零 coverage 表示零条已通过校验的访问证据，不证明代理没有实际尝试；未校验的候选不得进入下游。校验失败不得改写任何证据或创建失败回执：

```powershell
python -X utf8 scripts/run_daily.py reconcile-supplement --manifest <run_manifest.json> --request <supplement_request.json> --result <ready-lane.draft.json> --progress-state <timed-out-gap-progress-state.json>
```

canary 终态失败后停止 fanout，调用者确认确未启动的后续 gap 时逐个追加 `--unstarted-gap <gap_id>`。此断言只能覆盖已登记 launch plan 的后续 wave；canary 必须有已绑定的 `degraded_timeout`/`declare_lost` 状态，声明未启动的 gap 不得已有 draft、result、进度或执行遥测（仅预算预留不算已执行）。未启动 gap 以 `failed/infrastructure`、`not_started_after_canary_failure`、零 coverage、零轮次和空候选登记，不得记为 completed/no_increment。没有显式断言的缺失 gap 仍封闭拒绝。失败请求保持封闭；要重跑须新建 run，不能用新版安装脚本修补旧 run 的不可变快照。

## runtime

等待代理时先完成本地可并行的确定性检查，以 `draft_ready`（补检）或原子发布后的 `artifact_ready`（评审）控制消息为主信号。所有里程碑都通过运行时现有的 `contact_supervisor`/supervisor 通道发送，不假定存在名为 `supplement_progress` 或 `review_progress` 的独立工具。补检代理在帮助脚本完成输入哈希验证后发送 `supplement_progress seq=1 phase=input_validated`；完成允许的来源访问后先固定来源核验 `completed_at`，再发送 `supplement_progress seq=2 phase=source_checked`。此后只允许写动态 draft 并运行确定性帮助脚本，不得继续检索或读取合同源码。新序号属于可比较的状态变化并清零该代理的连续静止等待计数。语义代理在紧凑帮助脚本完成全部绑定校验后发送 `review_progress seq=1 phase=input_validated`，在动态语义选择完成后发送 `review_progress seq=2 phase=lineage_ready`；红队在输入哈希验证后发送 `review_progress seq=1 phase=input_validated`。心跳不得包含候选、结论或回执正文。

所有代理必须异步启动。交互会话禁止调用阻塞式 `subagent_wait` 或 `wait_agent`；只允许为已知 run 注册一次非阻塞完成唤醒并结束当前回合，收到完成、阻断或进度事件后再恢复。非交互会话依赖运行时 auto-drain，不自行轮询或休眠。补检必须按 `launch_plan` 把每个 worker 的 `timeout_ms`、`tool_budget`、`token_budget` 与 `cost_budget_usd` 原样传给运行时；`timeout_ms` 包含来源核验预算与独立 finalization grace，`tool_budget.hard` 是运行中可强制的工具调用上限。语义与非确定性红队必须把 execution packet 的 `timeout_ms`、`usage_budget.tokens` 与 `usage_budget.cost_usd` 原样传给运行时。启动前由脚本按全部待启动 worker 的预算 Token 上限预留总额，并额外保留语义与红队合计 70,000 Token、1 美元的下游 headroom；语义与红队各自最多预留 0.5 美元，不能由先启动的语义阶段占用红队份额。无法保留时不得启动补检。预算 Token 固定为运行时 `total_tokens - cache_read_tokens - cache_write_tokens`，原始总 Token 仍单独保留用于可观测性但不重复占用缓存命中的运行预算。预留后会超过 250,000 预算 Token 时不得启动，累计费用达到 3 美元时也不得启动。Token 与费用预算属于启动预留和终态结算门，运行时不保证在已启动代理越界的瞬间中断；不得把它们描述为活动中的硬停止器。活动中的有界停止依赖 `timeout_ms`、`tool_budget`、查询/URL/轮次限制和收口帮助脚本。等待期间先完成本地可并行的确定性检查；每次恢复只读取一次代理状态和一次下述文件观察，并在运行日志可读时读取仅含最新事件 ordinal、时间戳、工具调用计数和已收到里程碑序号的进度指纹。把该指纹交给 `scripts/review_progress_gate.py` 的阶段专属状态文件；它以原子状态机返回 `continue_wait`、`send_reminder`、`verify_artifact`、`degraded_timeout` 或 `declare_lost`。补检必须使用 `--review-kind supplement --progress-id <gap_id>` 与逐 gap 独立状态文件，禁止多个 worker 共享状态。`running` 且进度指纹增长表示进展；单凭没有正式文件或仍为 `running` 不得判定失联。运行时明确报告 timeout 时传入 `--agent-status timed_out`，由状态机登记 `degraded_timeout`，不得继续等待清理终态。为防无效工具循环无限续期，同一里程碑内最多允许 15 次增长检查；达到上限后发送定向提醒，提醒后连续三次仍无新里程碑则执行 `declare_lost`。代理明确失败/退出或提醒后连续三次静止也由状态机判为 `declare_lost`。穿插本地工作、发送说明或恢复回合不会重置预算；只有新控制里程碑才清零无里程碑增长计数。

```powershell
python -X utf8 scripts/review_progress_gate.py --state <run_dir>/semantic_progress_state.json --manifest <run_manifest.json> --review-kind semantic --invocation-id <semantic_request.invocation_id> --request-sha256 <manifest.artifacts.semantic_review_request.artifact_sha256> --agent-status running --event-ordinal <n> --last-event-at <iso_datetime> --tool-call-count <n> --milestone-seq <0|1|2>
```

若调用层无法读取代理内部的事件 ordinal、时间戳或工具调用计数，不得猜测这些值，也不得跳过状态机。改用已登记请求中的 draft 路径生成本地可复算的文件观察指纹；语义阶段只观察 execution packet 授权的 semantic dynamic draft，`milestone-seq` 只取已收到的正式里程碑：

```powershell
python -X utf8 scripts/review_progress_gate.py --state <run_dir>/semantic_progress_state.json --manifest <run_manifest.json> --review-kind semantic --invocation-id <semantic_request.invocation_id> --request-sha256 <manifest.artifacts.semantic_review_request.artifact_sha256> --agent-status running --milestone-seq <0|1|2> --watch-path <semantic-dynamic-draft>
```

文件不存在、出现、大小或修改时间变化都会形成新观察指纹；单纯等待时间流逝不会伪造进展。状态机返回 `send_reminder`、`verify_artifact`、`degraded_timeout` 或 `declare_lost` 时仍按原合同处理。

仅在通知通道延迟或不可用时，允许执行一次文件观察降级：

```powershell
python -X utf8 scripts/await_artifacts.py --path <lane-1.json> --path <lane-2.json>
```

降级观察最长 10 秒且不得重复轮询；仍未就绪时只发送一次定向提醒。若上述进度指纹规则确认代理失败/失联，当前登记请求必须封闭失败，不得用相同 request、invocation 或输出路径重新启动代理；需要重试时创建全新 run。文件稳定、可解析后立即运行登记命令；只要合同验证通过，就不再等待额外聊天状态。文件存在或控制消息本身都不等于通过，仍须执行正式登记校验。

每个子代理进入终态后，只要本地 Pi JSONL 可读，就必须登记不含消息正文的使用量遥测；失败、取消和 timeout 也必须登记。不得把 prompt、工具输出或文件内容复制进遥测：

```powershell
python -X utf8 scripts/session_telemetry.py --manifest <run_manifest.json> --stage <supplemental|semantic_review|red_team> --invocation-id <id> --status <completed|degraded|degraded_timeout|failed|cancelled> --session <local-session.jsonl>
```

补检遥测的 `invocation-id` 必须使用对应 `gap_id`，语义与红队使用已登记 request 的 `invocation_id`。请求登记时，manifest 会在 `telemetry.reservations` 中持久化每次启动的预算 Token/费用预留；没有完全匹配的活动 reservation 时拒绝遥测。每个 session JSONL SHA-256 只能绑定一个 invocation，重复或交叉登记拒绝。可信遥测登记后以 `total_tokens - cache_read_tokens - cache_write_tokens` 结算预算 Token，同时保留原始总 Token，并释放差额。若运行时没有暴露 session 路径，明确标记遥测不可用，不得估算 Token 或费用，且完整预留继续计入运行总预算，后续阶段不得重复取得该额度。若 prepare 没有返回 request，说明基线已满足配置要求，脚本已登记结构化 `no_increment`，不要伪造补检结果。

## semantic

先登记语义评估请求：

```powershell
python -X utf8 scripts/run_daily.py prepare-review --manifest <run_manifest.json> --kind semantic --max-turns 2
```

把返回的 `semantic_review_request.json` 交给独立 `SemanticEvaluator`。启动消息只要求运行 `execution_packet.agent_helper.context_command`；该命令在本地校验 request、manifest、prompt 与全部 `bound_artifacts` 的路径及 SHA-256，只返回具备登记访问证据、已经过历史去重的紧凑候选。代理不得直接读取完整 request、baseline、history snapshot/slice、candidate pool、supplement、briefing schema、旧 run、prompt config、脚本源码或主会话历史。缺失帮助脚本或任一绑定不一致时必须封闭失败并重新 prepare。

语义代理只负责在 helper 返回的 `eligible_candidates` 中执行门禁、排序、事件身份、L1-L4、中文判断和行动建议，并只写 `semantic-dynamic/1.0` 草稿。动态草稿不得生成静态 run/hash、coverage、candidate funnel、mix、pipeline、access log、lineage或回执字段；不得重新联网访问已登记 URL。写完后立即运行 `execution_packet.agent_helper.finalize_command`（同 `validation_command`）：

```powershell
python -X utf8 scripts/semantic_agent.py finalize --request <semantic_review_request.json>
```

帮助脚本从已登记候选和动态选择确定性生成 core 与 compact decision，规范日期、计算 event_id、coverage、funnel、mix、血缘、条目哈希、访问日志和 data provenance，执行 semantic gate 后原子发布 core 与完整语义回执并登记。代理最多在当前允许轮次内修复帮助脚本报告的动态字段错误，不扩展候选或读取额外上下文；发现证据矛盾时封闭失败。

draft gate 必须在允许发布前使用绑定的完整 history snapshot 重跑与 forge 相同的事件去重，并按“候选引用对应的全部已登记对象哈希集合”验证血缘；同一 URL 在基线与补检中出现不同合法对象形态时，不得因后写覆盖前写而产生伪血缘失败。

将基线候选与已登记补检候选合并，按以下顺序处理：

1. 验证发布日期、访问回执和直接来源；
2. 先按结构化 `event_id` 合并同一事件；只有任一侧缺少完整语义身份时，才按规范化 URL 与标题指纹兜底，不得把共享稳定 URL 的不同完整事件身份合并；
3. 同一事件的多个来源作为佐证，不重复计数；
4. 区分事实、来源主张、分析推断、行动和未知项；一手来源可单独进入语义候选，二手来源只有在同一结构化事件身份下获得至少两个独立来源及访问回执时才可作为 `multi_independent` 候选组；
5. 分别在 `technology` 与 `healthcare_digital` 领域内评分，通用技术不得被强制改写为医疗事件；临床、肿瘤、指南与临床决策等明确医疗语义必须参与医疗数字化领域计分；
6. 依据 manifest 的请求比例选择，不足 10 条时不补数；
7. 代理生成 1.4 refined core 与 compact semantic decision；脚本生成 `review-receipt/1.0`。

脚本生成的语义回执必须绑定输入 bundle 与 refined 文件 SHA-256，覆盖所有最终条目的完整对象哈希，逐项映射 `candidate_object_sha256 → output_item_sha256`，并提供与最终 `access_check` 对应的访问日志及其哈希。每个最终条目的 `requested_url` 必须匹配条目 URL，`final_url` 仅记录跳转落点，入选条目按唯一映射计数。`model_used=heuristic`、血缘或访问日志不一致时停止。

语义 core 与 receipt 分别原子提升并登记为一个可重入阶段提交；这不是跨文件单一原子事务。第二次提升或登记中断后，同一 invocation 必须复用已验证字节恢复，禁止生成新身份或覆盖不同内容。两份产物完成登记并由就绪信号确认后，不得并行预启动红队，也不得因为评估代理尚未发送额外聊天消息而继续等待。下一步的红队请求命令必须接收语义回执，并在创建请求前于同一进程重新执行同一 semantic draft gate；验证失败时不得留下 `red_team_review_request.json`。

## red-team

对 refined core 检查反证、日期、来源独立性、重大资讯资格、行动时序和 L4。存在 L4 时，红队状态必须为 `passed` 且条目哈希覆盖所有 L4；没有 L4但存在重大资讯或冲突时执行 targeted review，状态必须为 `passed`，且 reviewed hashes 精确覆盖请求中的重大资讯与冲突哈希并集。只有确定性 no-L4/no-major/no-conflict fast path 可返回 `not_required` 空覆盖回执。

refined core 与语义回执通过上述校验后先登记红队请求，再把该请求交给独立 `RedTeam`。红队同样只接收已登记请求路径并严格按其中自包含 `execution_packet` 执行，不重复载入整份技能、提示词配置或主会话历史：

```powershell
python -X utf8 scripts/run_daily.py prepare-review --manifest <run_manifest.json> --kind red_team --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --max-turns 2
```

请求会确定性写入 `review_mode`、L4 条目哈希、重大资讯哈希和 `deterministic_fast_path`。当无 L4、无重大资讯且语义回执及条目没有冲突标记时，脚本使用 `NoL4Gate` 直接生成 `reviewer_kind=deterministic_gate`、`turns_used=0` 的 `not_required` 回执并登记；不得启动 RedTeam，也不得联网。没有 L4但存在重大资讯或冲突时，保留一轮独立 RedTeam 复核。存在 L4 时使用完整红队路径，优先复用登记证据，仅在冲突时补充核验。

仅当 `deterministic_fast_path=false` 时才执行以下代理步骤。红队回执必须原样返回 request SHA-256、challenge、reviewer/invocation 标识、轮次与停止状态。不得修改 refined 后继续使用旧请求或回执。RedTeam 必须先写入请求指定的 draft path，再执行请求内的 `validation_command`；等价命令如下：

```powershell
python -X utf8 scripts/run_daily.py validate-red-team-draft --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --red-team-receipt <red_team_receipt.draft.json>
```

只有 draft gate 返回 `status=valid` 才可原子提升到最终 `red_team_receipt.json` 并发送 `artifact_ready`。产物稳定后登记两份回执；登记命令会在写入阶段状态前重新验证两者：

```powershell
python -X utf8 scripts/run_daily.py register-review --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --red-team-receipt <red_team_receipt.json>
```

## archive

归档器必须：

1. 重新验证技能全树、资源清单内部哈希、历史快照、运行身份、refined 字节、语义回执和红队回执；
2. 从已登记证据重算 coverage、候选漏斗、重大资讯调比、供给例外和历史重复；候选漏斗必须为每个进入下游的候选保留明确 disposition，并把未访问核验、二手来源缺少独立佐证、历史重复、日期冲突与语义未选择分开计数，再生成最终 `pipeline` 并运行 `briefing_gate.py`；
3. 从同一 JSON payload 确定性渲染 Markdown；
4. 在同一 staging 中准备 JSON、Markdown 和 commit sidecar；
5. 先取得按新闻目录派生的操作系统级排他守卫；Windows 必须使用跨登录会话的 `Global\` mutex 且创建失败时封闭拒绝，不得降级到会话级守卫；目录元数据锁必须带随机 owner token，回收与释放前复核所有权；守卫覆盖旧锁判断、恢复、接管、历史重检和整个提交区，阻断并发接管及跨报告日历史检查竞争；活动进程或无法验证的异地主机锁不得接管，只回收同机已确认死亡且元数据未变化的锁；
6. 最终重读并核对 SHA-256；`postcommit_action` 返回后再次重读正式三件套，任何后置动作导致的字节变化都触发回滚；
7. 在同一守卫内、staging 前从正式档案重建并比对历史快照，逐条重跑事件去重；正式 JSON、Markdown、sidecar 三件套属于事务提交，派生 history v2 是随后在同一守卫内执行的独立可恢复更新，不得把四者声称为单一原子写。history 更新或 archive 登记失败必须保持明确未完成状态，并由下次归档先恢复/重建后再成功登记；可捕获的三件套提交中途失败立即回滚，进程中断留下的未完成事务由下次归档先恢复。
