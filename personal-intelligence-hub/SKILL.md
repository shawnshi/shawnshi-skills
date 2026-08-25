---
name: personal-intelligence-hub
description: 对技术与医疗数字化开展基线优先的多来源扫描、缺口补检、事件级历史去重、证据核验、动态领域配比、语义评估和逻辑红队，并事务化生成带来源的日简报。用于“今日资讯简报”“昨日资讯简报”“情报扫描”“战略简报”“过去一周动态”“竞争信号”等需要当前外部信息和行动判断的请求；正式日简报按合同自动保存。
---

# 技术与医疗数字化资讯简报

## 适用合同

1. 当前正式产物使用 `references/briefing_schema.json` 1.4；历史 v1.0/v1.1、`references/briefing_schema_v1.2.json` 及 `references/briefing_schema_v1.3.json` 由冻结 validator 只读回放，不改写旧档。
2. 用户只说“今日资讯简报”时：报告日为 Asia/Shanghai 当日，窗口为报告日及之前 6 日，共 7 个日历日；地域为中国、美国与全球。
3. 默认领域请求比例为技术 60%、医疗数字化 40%。用户指定主题或比例时覆盖默认值并记录来源与理由。
4. 正式日简报默认自动保存。用户明确要求不保存时，在两份回执登记后运行 `python -X utf8 scripts/run_daily.py preview --manifest <run_manifest.json> --refined <refined_core.json>`；只返回通过门禁的确定性 Markdown，不调用归档步骤。
5. 临时探针和测试只写当前任务隔离 scratch；正式新闻产物只写授权新闻目录。运行中间态默认写入 `~/MEMORY/brain/personal-intelligence-hub/runtime`，只有显式设置 `PIH_RUNTIME_DIR` 才可覆盖，不得回退到系统临时目录。

## 开始前读取

按需读取以下直接合同，不要凭记忆猜字段：

- `references/strategic_focus.json`
- `references/quality_standard.md`
- `references/briefing_schema.json`
- `references/subagent_prompts.json`
- 生成 Markdown 前读取 `references/briefing_template.md`

运行脚本前检查 `requirements.txt` 与当前环境。不要自动安装依赖或修改全局配置。

## 唯一生产流程

### 1. 建立运行并先完成基线

使用统一入口：

```powershell
python -X utf8 scripts/run_daily.py prepare --report-date YYYY-MM-DD --timezone Asia/Shanghai
```

该命令必须依次完成：

1. 创建不可变 `run_manifest.json`，锁定 `run_id`、报告日、时区、窗口、主题、地域、请求比例、SKILL/资源清单 SHA-256 及技能全树摘要；
2. 从正式新闻 JSON 确定性重建并登记完整 history v2 快照，同时按 `dedupe_days` 生成并登记紧凑评审切片；完整快照用于归档一致性，语义代理只读取切片；目标报告日的旧档只进入替换哈希前置条件，不进入本次去重池；
3. 先使用 `references/karpathy_feeds.json` 执行基线扫描；
4. 将未知或无效发布日期放入 quarantine，记录来源覆盖和守恒候选漏斗；
5. 将基线制成带 `candidate_id` 与 `candidate_object_sha256` 的 `candidates_only` 启发式候选池；
6. 根据领域供给、来源成功率、日期有效率、政策竞对和风险反证缺口生成 `supplement_request.json`。

基线阶段未达到 `completed` 或 `degraded` 前，不得启动补充检索。启发式候选只用于排序和发现缺口，不得直接成为最终事实、等级、推断、置信度或归档内容。

基线抓取对网络异常、408、425、429 与 5xx 保留退避重试；对 4xx 永久响应及确定性的本地 TLS、证书或协议配置错误不做同参数重复请求，立即计入失败覆盖并交由缺口补检处理。全局并发限制为 1..32，同一主机最多占用 4 个连接，避免单一来源挤占全部扫描槽位。全扫描默认以 300 秒为总时限，可用 `--scan-deadline-seconds` 在 `0 < 秒数 ≤ 3600` 范围内调整；到期只取消未完成来源，并把每个来源记为结构化 `TIMEOUT` 覆盖失败，已完成来源与候选必须保留。取消清理默认只等待 2 秒，仍未退出的异常任务计入 `cancellation_pending_sources`，不得阻塞本阶段产物。基线元数据记录实际 `elapsed_seconds`、配置时限和超时来源数。不得通过删源、缩小扫描面或隐去超时换取耗时下降。

“昨日资讯简报”显式传入昨日日期。不得用运行时滚动窗口或当前日期命名昨日文件。

### 2. 只针对缺口调用补检代理

若 prepare 返回 `supplement_request_path`：读取 `references/subagent_prompts.json`，按 request 中每个 gap 的 `lane` 调用对应代理：

- `TechRadar`：通用技术；
- `HealthcareRadar`：医疗 AI 与医疗数字化；
- `Sentinel`：政策、支付、采购与竞对；
- `Ranger`：失败、漏洞、处罚与执行摩擦。

按 `execution_policy` 使用最小任务包启动代理：只传技能与提示词配置路径、run manifest、已登记请求、绑定输入的绝对路径、明确分派的 `gap_id`/`lane` 白名单、逐 gap 唯一输出路径、写入授权、最大轮次和停止条件；不得把候选池、历史快照或完整会话正文复制进任务消息。运行时支持上下文继承控制时必须关闭完整会话历史继承。根任务连同最多 3 个补检工作者并行；出现第 4 个 gap 时，等首个槽位释放后用全新最小上下文启动第四个工作者，不得把两个 lane 混入同一代理。已经分派的检索不得由根任务重复执行。

补检代理只在发现阻断时发送中间状态；其余情况在原子发布后立即发送一次 `artifact_ready` 控制消息，包含绝对路径与 SHA-256，然后结束。结果必须先写到目标文件的同目录临时文件，完成 JSON 与合同自检后再原子替换为唯一输出路径，发布后不得修改。语义与红队代理另按对应阶段发送不含业务内容的有限里程碑心跳。

每个代理必须先处理绑定的基线候选，再补充检索；不得绕过基线直接做开放式搜索。当前资讯必须联网核验，优先监管、政府、公司公告、采购原文、论文、标准和项目主页。新闻与评论只作线索或独立佐证。

补检不得对同一 URL 的永久失败做同参数重试；同一主机连续两次永久失败后必须切换到另一类优先来源，并把失败保留在 `access_log`，不得通过删除失败记录美化覆盖率。只有瞬时超时、限流或可重试 HTTP 状态可在轮次预算内重试；达到 gap 的合格增量或连续检索无增量时立即停止。

每个结果必须符合 `supplement-result/1.0`，原样返回：

- `run_id`、request SHA-256、baseline SHA-256、candidate pool SHA-256、`gap_id`、`lane`；
- 非空实际查询、逐次 `access_log`、候选及来源/日期/访问核验；访问记录同时保留 `requested_url` 与跳转后的 `final_url`，候选的请求 URL 必须匹配候选 URL 并对应 `verified` 日志；
- 从 `access_log` 派生且守恒的 attempted/succeeded/failed 覆盖计数；
- `confidence`、绑定 request/candidate pool/access log 哈希的 `data_provenance`；
- 1..max_turns 的已用轮次、停止条件是否满足、完成时间和状态。

只有代理在任何查询或访问前初始化失败时，才可登记零尝试基础设施失败：`status=failed`、`failure_kind=infrastructure`、非空 `failure_reason`、`turns_used=0`、`halt_condition_met=false`，且 queries、access log、candidates 为空、coverage 全零。其他失败仍必须保留真实查询与访问证据。

没有增量时返回 `no_increment` 与空候选，不得补写弱资讯。全部 gap 结果齐备后登记：

```powershell
python -X utf8 scripts/run_daily.py register-supplement --manifest <run_manifest.json> --request <supplement_request.json> --result <lane-1.json> --result <lane-2.json>
```

等待代理时先完成本地可并行的确定性检查，以原子发布后的 `artifact_ready` 控制消息为主信号。语义代理在输入哈希验证后发送 `review_progress seq=1 phase=input_validated`，在候选选择、血缘与回执映射完成后发送 `review_progress seq=2 phase=lineage_ready`；红队在输入哈希验证后发送 `review_progress seq=1 phase=input_validated`。心跳不得包含候选、结论或回执正文。

每个阶段最多允许两次、每次不超过 60 秒的 `wait_agent`；若两次都没有新的 `artifact_ready`、阻断消息或可比较的代理状态变化，只允许一次 `list_agents`、一次下述文件观察，并在运行日志可读时读取一次仅含最新事件 ordinal、时间戳、工具调用计数和已收到里程碑序号的进度指纹。把该指纹交给 `scripts/review_progress_gate.py` 的阶段专属状态文件；它以原子状态机返回 `continue_wait`、`send_reminder`、`verify_artifact` 或 `declare_lost`。`running` 且进度指纹增长表示进展，必须继续等待；单凭超时、没有正式文件或仍为 `running` 不得判定失联或中止代理。为防无效工具循环无限续期，同一里程碑内最多允许 15 次增长检查；达到上限后发送定向提醒，提醒后连续三次仍无新里程碑则执行 `declare_lost`。代理明确失败/退出或提醒后连续三次静止也由状态机判为 `declare_lost`。穿插本地工作、发送说明或缩短单次等待不会重置预算；只有新控制里程碑才清零无里程碑增长计数。

```powershell
python -X utf8 scripts/review_progress_gate.py --state <run_dir>/semantic_progress_state.json --manifest <run_manifest.json> --review-kind semantic --agent-status running --event-ordinal <n> --last-event-at <iso_datetime> --tool-call-count <n> --milestone-seq <0|1|2>
```

若调用层无法读取代理内部的事件 ordinal、时间戳或工具调用计数，不得猜测这些值，也不得跳过状态机。改用已登记请求中的 draft 路径生成本地可复算的文件观察指纹；同一命令同时观察 core 与回执 draft，`milestone-seq` 只取已收到的正式里程碑：

```powershell
python -X utf8 scripts/review_progress_gate.py --state <run_dir>/semantic_progress_state.json --manifest <run_manifest.json> --review-kind semantic --agent-status running --milestone-seq <0|1|2> --watch-path <refined-core-draft> --watch-path <semantic-receipt-draft>
```

文件不存在、出现、大小或修改时间变化都会形成新观察指纹；单纯等待时间流逝不会伪造进展。状态机返回 `send_reminder`、`verify_artifact` 或 `declare_lost` 时仍按原合同处理。

仅在通知通道延迟或不可用时，允许执行一次文件观察降级：

```powershell
python -X utf8 scripts/await_artifacts.py --path <lane-1.json> --path <lane-2.json>
```

降级观察最长 10 秒且不得重复轮询；仍未就绪时只发送一次定向提醒。若上述进度指纹规则确认代理失败/失联，当前登记请求必须封闭失败，不得用相同 request、invocation 或输出路径重新启动代理；需要重试时创建全新 run。文件稳定、可解析后立即运行登记命令；只要合同验证通过，就不再等待额外聊天状态。文件存在或控制消息本身都不等于通过，仍须执行正式登记校验。

若 prepare 没有返回 request，说明基线已满足配置要求，脚本已登记结构化 `no_increment`，不要伪造补检结果。

### 3. 事件合并与语义评估

先登记语义评估请求：

```powershell
python -X utf8 scripts/run_daily.py prepare-review --manifest <run_manifest.json> --kind semantic --max-turns 2
```

把返回的 `semantic_review_request.json` 交给独立 `SemanticEvaluator`。`review-request/1.1` 内的 `execution_packet` 是自包含任务包，已固化公共合同、角色合同、进度消息、精确 draft/最终输出路径、写入白名单和验证命令；启动消息只需给出已登记请求的绝对路径与“严格按 execution_packet 执行”，不得再次要求代理读取整份 `SKILL.md`、完整提示词配置或继承主会话历史。请求内 `bound_artifacts` 已绑定基线、候选池、补检聚合、完整历史快照、focus config 与紧凑评审切片的绝对路径和 SHA-256。评估者只读取 `history_review_slice` 做历史去重；完整 `history_snapshot` 只保留为归档溯源绑定，不重复载入。缺失切片的旧运行必须封闭失败并重新 prepare，不得回退加载完整历史。评估者必须原样返回请求中的 challenge、reviewer/invocation 标识与 request SHA-256。

语义代理必须优先复用已登记候选中的日期、URL、访问日志和对象哈希，在本地批量完成门禁、去重、排序、血缘和回执构造；除非登记证据缺失或相互矛盾，不得重新联网访问已经 `verified` 的 URL。一次读取各所需绑定文件，不在聊天或工具输出中回显完整候选池、历史切片、core 或回执。候选的 `published_at` 若为合法 ISO datetime，必须调用 `python -X utf8 scripts/run_daily.py normalize-published-at --value <iso_datetime>`，按其自带时区取日期并规范为严格 `YYYY-MM-DD`；不得把 datetime 原样写入 core。

评估者先把 core 与回执写入各自目标旁的唯一 draft 文件，再运行：

```powershell
python -X utf8 scripts/run_daily.py validate-semantic-draft --manifest <run_manifest.json> --refined <refined_core.draft.json> --semantic-receipt <semantic_receipt.draft.json>
```

只有 draft gate 返回 `status=valid` 才可分别原子提升到最终输出并发送 `artifact_ready`；失败时最多使用第二轮修复已报告的合同错误，不扩展事件。发现证据矛盾时封闭失败，不补写未经登记的外部事实。

draft gate 必须在允许发布前使用绑定的完整 history snapshot 重跑与 forge 相同的事件去重，并按“候选引用对应的全部已登记对象哈希集合”验证血缘；同一 URL 在基线与补检中出现不同合法对象形态时，不得因后写覆盖前写而产生伪血缘失败。

将基线候选与已登记补检候选合并，按以下顺序处理：

1. 验证发布日期、访问回执和直接来源；
2. 先按结构化 `event_id` 合并同一事件；只有任一侧缺少完整语义身份时，才按规范化 URL 与标题指纹兜底，不得把共享稳定 URL 的不同完整事件身份合并；
3. 同一事件的多个来源作为佐证，不重复计数；
4. 区分事实、来源主张、分析推断、行动和未知项；
5. 分别在 `technology` 与 `healthcare_digital` 领域内评分，通用技术不得被强制改写为医疗事件；
6. 依据 manifest 的请求比例选择，不足 10 条时不补数；
7. 生成 1.4 refined core 与 `review-receipt/1.0` 语义回执。

语义回执必须绑定输入 bundle 与 refined 文件 SHA-256，覆盖所有最终条目的完整对象哈希，逐项映射 `candidate_object_sha256 → output_item_sha256`，并提供与最终 `access_check` 对应的访问日志及其哈希。每个最终条目的 `requested_url` 必须匹配条目 URL，`final_url` 仅记录跳转落点，入选条目按唯一映射计数。`model_used=heuristic`、请求挑战不一致、血缘或访问日志不一致时停止。

语义产物原子发布并由就绪信号确认后，不得并行预启动红队，也不得因为评估代理尚未发送额外聊天消息而继续等待。下一步的红队请求命令必须接收语义回执，并在创建请求前于同一进程重新执行同一 semantic draft gate；验证失败时不得留下 `red_team_review_request.json`。

### 4. 逻辑红队

对 refined core 检查反证、日期、来源独立性、重大资讯资格、行动时序和 L4。存在 L4 时，红队状态必须为 `passed` 且条目哈希覆盖所有 L4；没有 L4 时可返回明确的 `not_required` 空覆盖回执。

refined core 与语义回执通过上述校验后先登记红队请求，再把该请求交给独立 `RedTeam`。红队同样只接收已登记请求路径并严格按其中自包含 `execution_packet` 执行，不重复载入整份技能、提示词配置或主会话历史：

```powershell
python -X utf8 scripts/run_daily.py prepare-review --manifest <run_manifest.json> --kind red_team --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --max-turns 2
```

请求会确定性写入 `review_mode`、L4 条目哈希和重大资讯哈希。没有 L4 时，`review_mode=no_l4_fast_path` 且 `max_turns=1`：独立 RedTeam 只复核绑定哈希、无 L4 事实、重大资讯资格、日期/来源独立性与行动时序，复用登记证据且不得联网扩展事件，随后生成 `not_required` 空覆盖回执。存在 L4 时使用完整红队路径，但仍优先复用登记证据，仅在冲突时补充核验。

红队回执必须原样返回 request SHA-256、challenge、reviewer/invocation 标识、轮次与停止状态。不得修改 refined 后继续使用旧请求或回执。产物稳定后直接登记两份回执；登记命令会在写入阶段状态前重新验证两者：

```powershell
python -X utf8 scripts/run_daily.py register-review --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --red-team-receipt <red_team_receipt.json>
```

### 5. 验证并事务化归档

```powershell
python -X utf8 scripts/run_daily.py forge --manifest <run_manifest.json> --refined <refined_core.json>
```

归档器必须：

1. 重新验证技能全树、资源清单内部哈希、历史快照、运行身份、refined 字节、语义回执和红队回执；
2. 从已登记证据重算 coverage、候选漏斗、重大资讯调比、供给例外和历史重复，再生成最终 `pipeline` 并运行 `briefing_gate.py`；
3. 从同一 JSON payload 确定性渲染 Markdown；
4. 在同一 staging 中准备 JSON、Markdown 和 commit sidecar；
5. 先取得按新闻目录派生的操作系统级排他守卫；Windows 必须使用跨登录会话的 `Global\` mutex 且创建失败时封闭拒绝，不得降级到会话级守卫；目录元数据锁必须带随机 owner token，回收与释放前复核所有权；守卫覆盖旧锁判断、恢复、接管、历史重检和整个提交区，阻断并发接管及跨报告日历史检查竞争；活动进程或无法验证的异地主机锁不得接管，只回收同机已确认死亡且元数据未变化的锁；
6. 最终重读并核对 SHA-256；
7. 在同一守卫内、staging 前从正式档案重建并比对历史快照，逐条重跑事件去重；正式三件套验证成功后仍在该守卫内更新派生的 history v2，随后才释放守卫并登记 archive 阶段；可捕获的中途失败立即回滚，进程中断留下的未完成事务由下次归档先恢复。

不得单独手写正式 Markdown、直接运行旧 `forge.py` 无参入口，或在回执未通过时写入新闻目录。

## 日期、覆盖与事件规则

- 7 日窗口为 `report_date-(days-1)` 至 `report_date`，两端包含。
- `published_at` 必须为窗口内 `YYYY-MM-DD` 已知日期；候选为 ISO datetime 时按其自带时区取日期后规范化。`event_date` 可未知，但不得晚于发布日期。
- GitHub/V2EX 观察时间不得冒充发布日期；Hacker News 时间使用带时区 UTC；所有候选记录 `retrieved_at`。
- 每条正式资讯只能有一个 `primary_domain`；混合事件可填 `secondary_domains`，但只按主领域计数。
- 条目 `confidence`、`corroboration_status` 与运行 `coverage_confidence` 含义不同，不得互相替代。
- `candidate_funnel.observed` 必须等于终态处置之和，retained 必须等于正式条目数。
- 基线全灭、必要车道失败、日期有效率不足或来源访问失败必须降级并披露，不能写成“未发现”。
- 来源均返回成功但零候选时仍为 degraded，不得声明 high coverage。

## 配比与重大资讯

1. 先执行证据门，再执行配比；不使用弱资讯补足比例。
2. 条目数不足 10 时使用最大余数法，例如 7 条为 4:3、5 条为 3:2、3 条为 2:1。
3. 只有“高可信 L3 + 原始来源 + 访问已核验 + 近期决策影响”，或经红队覆盖的 L4，才可标记 `major_signal=true`。
4. 有效比例必须由门禁按合格重大资讯的所属领域与请求比例重算，最多偏移 20 个百分点；两个领域同时有合格重大资讯时维持请求比例。
5. 某领域合格候选不足可跨领域补位，但必须写 `mix.supply_exception`。

## 自动保存与交付

保存目录优先级：用户本次指定目录 > `PIH_NEWS_DIR` > `hub_utils.NEWS_DIR`。不要在技能文档或脚本调用中硬编码用户目录。

文件为：

- `intelligence_YYYYMMDD_briefing.json`
- `intelligence_YYYYMMDD_briefing.md`
- `intelligence_YYYYMMDD_briefing.manifest.json`

同日重跑采用带旧文件哈希前置条件的事务替换。历史日期已有档案时，只有用户明确授权替换后才可在 prepare 增加 `--allow-existing-archive-replacement`。最终回复必须报告三份绝对路径、保留条数、实际比例、来源成功数、日期有效率、补检/红队状态和仍未闭合的数据缺口。证据不足时允许少于 10 条或为空。

自动保存只授权正式新闻文件及新闻目录内的 `.pih_history_v2.json` 去重索引，不授权写入个人长期记忆、知识图谱、邮件、外部发布或其他系统。review challenge 只提供运行内绑定与防重放，不是外部运行时的加密身份签名；执行者仍必须真实调用两个独立评估代理。
