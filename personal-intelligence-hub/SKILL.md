---
name: personal-intelligence-hub
description: 基线优先生成技术与医疗数字化资讯简报，按缺口补检、事件去重、语义评估和独立红队核验来源；正式日简报自动保存。用于今日/昨日资讯简报、情报扫描、战略简报、过去一周动态和竞争信号。
---

# 技术与医疗数字化资讯简报

## 适用合同

1. 当前正式产物使用 `references/briefing_schema.json` 1.4；历史 v1.0/v1.1、`references/briefing_schema_v1.2.json` 及 `references/briefing_schema_v1.3.json` 由冻结 validator 只读回放，不改写旧档。
2. 用户只说“今日资讯简报”时：报告日为 Asia/Shanghai 当日，默认窗口为报告日及之前 2 日，共 3 个日历日；如审核去重后条目不足 10 条，且非用户显式指定，则新起一轮扩充至 7 个日历日，不再兜底补充；地域为中国、美国与全球。
3. 默认领域请求比例为技术 60%、医疗数字化 40%。用户指定主题或比例时覆盖默认值并记录来源与理由。
4. 正式日简报默认自动保存。用户明确要求不保存时，在两份回执登记后运行 `python -X utf8 scripts/run_daily.py preview --manifest <run_manifest.json> --refined <refined_core.json>`；只返回通过门禁的确定性 Markdown，不调用归档步骤。
5. 临时探针和测试只写当前任务隔离 scratch；正式新闻产物只写授权新闻目录。运行中间态默认写入 `~/MEMORY/brain/personal-intelligence-hub/runtime`，只有显式设置 `PIH_RUNTIME_DIR` 才可覆盖，不得回退到系统临时目录。

## 开始前读取

父任务只读取当前阶段所需合同，不无条件加载整套 references；代理遵守阶段 packet 的紧凑输入限制，不继承父任务阅读范围：

- 建立运行前：`references/strategic_focus.json`；判定证据与候选门槛时：`references/quality_standard.md`。
- 生成/校验当前结构时：`references/briefing_schema.json`；生成 Markdown 前：`references/briefing_template.md`。
- 补检或评审分派时：`references/subagent_prompts.json` 的对应代理、common contract 与 execution_policy 分支。
- 详细执行协议集中于 `references/workflow_protocols.md`；按下方阶段指定的命名节读取（从对应 `##` 标题至下一 `##`），不预读整份。`runtime` 仅在要启动/恢复/结算代理时读取，`archive` 仅在正式归档/恢复时读取。

运行脚本前检查 `requirements.txt` 与当前环境。不要自动安装依赖或修改全局配置。

## 唯一生产流程

### 1. 建立运行并先完成基线

使用统一入口：

```powershell
python -X utf8 scripts/run_daily.py prepare --report-date YYYY-MM-DD --timezone Asia/Shanghai --article-broker-version 3
```

记录返回的 `execution_cli_path`。下文所有 `python -X utf8 scripts/run_daily.py ...` 在生产 run 中均表示 `python -X utf8 <execution_cli_path> ...`；不得在 prepare 后改回安装目录脚本。

该命令必须依次完成：

1. 创建不可变 `run_manifest.json`，锁定 `run_id`、报告日、时区、窗口、主题、地域和请求比例；同时把资源清单声明的完整技能 bundle 复制到 run 内只读语义快照，并返回 `execution_cli_path`。prepare 之后所有命令和代理 helper 必须使用该 run-scoped CLI/bundle；安装目录后续变化不得使在途 run 漂移，也不得继续用已变化的安装目录 CLI 操作旧 run；
2. 从正式新闻 JSON 确定性重建并登记完整 history v2 快照，同时按 `dedupe_days` 生成并登记紧凑评审切片；完整快照用于归档一致性，语义代理只读取切片；目标报告日的旧档只进入替换哈希前置条件，不进入本次去重池；
3. 先使用 `references/karpathy_feeds.json` 执行基线扫描；
4. 将未知或无效发布日期放入 quarantine，记录来源覆盖和守恒候选漏斗；
5. 将基线制成带 `candidate_id` 与 `candidate_object_sha256` 的 `candidates_only` 启发式候选池；
6. 根据已经完成文章级访问核验的一手候选供给、低于阈值的来源成功率、政策竞对和风险反证缺口生成 `supplement_request.json`；未核验的启发式候选不得冒充可入选供给。日期有效率不足继续作为 coverage/data gap 披露，不为无法通过少量联网补检修复的全局日期指标额外启动 integrity 代理。

基线阶段未达到 `completed` 或 `degraded` 前，不得启动补充检索。启发式候选只用于排序和发现缺口，不得直接成为最终事实、等级、推断、置信度或归档内容。

基线抓取对网络异常、408、425、429 与 5xx 保留退避重试；对 4xx 永久响应及确定性的本地 TLS、证书或协议配置错误不做同参数重复请求，立即计入失败覆盖并交由缺口补检处理。全局并发限制为 1..32，同一主机最多占用 4 个连接，避免单一来源挤占全部扫描槽位。全扫描默认以 300 秒为总时限，可用 `--scan-deadline-seconds` 在 `0 < 秒数 ≤ 3600` 范围内调整；到期只取消未完成来源，并把每个来源记为结构化 `TIMEOUT` 覆盖失败，已完成来源与候选必须保留。取消清理默认只等待 2 秒，仍未退出的异常任务计入 `cancellation_pending_sources`，不得阻塞本阶段产物。基线元数据记录实际 `elapsed_seconds`、配置时限和超时来源数。不得通过删源、缩小扫描面或隐去超时换取耗时下降。

“昨日资讯简报”显式传入昨日日期。不得用运行时滚动窗口或当前日期命名昨日文件。

### 2. 只针对缺口调用补检代理

进入本阶段前，父任务读取 `references/workflow_protocols.md` 的 `supplement` 节；有补检请求时，再读 `runtime` 节，完成预算预留后才可启动。代理只接收已登记最小 packet，不得加载本参考文档或主会话历史。

仅在基线 `completed`/`degraded` 后，按已登记 gap/lane 先核验绑定候选，再补缺口；根任务不重复已分派检索。canary 基础设施失败即停止 fanout；成功后最多 3 个 worker 并行。保留真实日期、访问日志与失败，禁止弱资讯补数。代理只写授权 draft，父任务确定性校验后原子发布；timeout/失联按持久化逐 gap 状态 reconciler 收口，不得只依赖 stdout。

新 run 默认 article-broker/3.0（也可显式 prepare --article-broker-version 3）。所有 lane 包括四个 required URL 占满预算者都走父级 native fetch_content(mode=readable)，CLI 只 reserve/record；禁止 v3 broker-http、verify-bound 或 portal fallback。先访问 required URLs，再在剩余预算 web_search(includeContent=false) 发现文章。读取 references/workflow_protocols.md 的 v3 receipt/date 合同；旧 run/v2 冻结回放不改写。

prepare 未返回 request 时，脚本已登记结构化 `no_increment`，不要伪造补检结果。

所有代理异步启动，交互会话禁止阻塞等待或轮询；完成/进度事件后按 `runtime` 节状态机恢复。只凭 running、文件存在或聊天消息不等于进展或完成；正式校验通过后不再等待额外聊天。失败请求封闭，不得复用 request/invocation/输出路径重启；重试创建全新 run。

启动前必须执行真实 Token/费用预留与下游 headroom 门，终态按去缓存预算口径结算；遥测不可用不得估算或释放完整预留。Token/费用是启动与结算门，不是活动硬停止器；详见 `runtime` 节。

### 3. 事件合并与语义评估

进入本阶段前，父任务读取 `references/workflow_protocols.md` 的 `semantic` 节及 `runtime` 节，再 prepare-review。独立 `SemanticEvaluator` 仅运行已绑定 helper、读取紧凑 eligible candidates、写动态草稿并 finalize，不得扩展候选、重读完整上下文或重新联网访问登记 URL。

按访问/日期/来源门、结构化事件身份、独立佐证、领域内排序和请求配比合并；不足 10 条不补数。确定性 helper 必须重跑历史去重、验证全部候选对象哈希血缘和访问日志；heuristic 或绑定不一致封闭失败。语义 core/receipt 是可重入阶段提交而非跨文件单一原子事务，中断复用已验证字节与原 invocation 恢复。两份产物登记并确认就绪后才能进入红队，不得并行预启动。

### 3a. 决定是否扩大窗口

语义 core 与回执通过门禁后、红队与归档前，运行 run-scoped CLI：

```powershell
python -X utf8 <execution_cli_path> check-expansion --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json>
```

该命令重跑语义证据、历史去重及血缘校验，再按 `top_10` 中的独立事件计数（不是来源候选数）。无效 core/回执返回非零退出码，不扩大窗口。默认 3 日运行少于 10 条时返回 `action=expand` 和 `next_argv`；按该参数数组启动一次新 7 日运行，保留旧运行且不提前归档 3 日结果。`next_command` 仅为 POSIX Shell 展示，不直接粘贴到 PowerShell。显式窗口、已有扩窗链接或 7 日运行不再次扩窗；不足仍少报。只有最终选定运行进入红队与归档。

新运行 Token 总上限为 1,000,000；每条补检预留 150,000，语义评审 200,000，红队 100,000，下游 headroom 合计 300,000。费用总上限仍为 3 美元；原有访问、工具、超时与结算门保留。旧快照及遥测不得按新上限改写。

### 4. 逻辑红队

进入本阶段前，父任务读取 `references/workflow_protocols.md` 的 `red-team` 节；需要独立代理时同时读取 `runtime` 节。创建请求前同进程重跑 semantic draft gate，失败不得留下红队请求。

L4 必须 passed 且覆盖所有 L4；无 L4 但有重大资讯或冲突必须 targeted passed 且精确覆盖两者哈希并集。仅 no-L4/no-major/no-conflict 的确定性 fast path 可 not_required，禁止启动代理或联网。其余真实调用独立 RedTeam，先复用登记证据，仅冲突时补核验。refined 变更后不能沿用旧请求/回执；draft gate valid 后才原子发布，正式登记时再次验证两份回执。

### 5. 验证并事务化归档

```powershell
python -X utf8 scripts/run_daily.py forge --manifest <run_manifest.json> --refined <refined_core.json>
```

调用 forge 前读取 `references/workflow_protocols.md` 的 `archive` 节；用户要求不保存时只用上方 preview 合同，不执行归档。归档必须重验全树/清单/历史/身份/证据/回执、重算 coverage/漏斗/配比/去重并过 gate，Markdown 由同一 JSON 确定性渲染。

操作系统排他守卫覆盖恢复、历史重检和提交，锁不得越权接管；三件套事务提交，history v2 是同守卫内独立可恢复更新，不得宣称四者单一原子写。失败回滚或明确未完成，恢复及登记成功前不得宣称完成。Windows Global mutex、owner token、哈希前置条件、后置动作复验与恢复详见 `archive` 节。

不得单独手写正式 Markdown、直接运行旧 `forge.py` 无参入口，或在回执未通过时写入新闻目录。

## 日期、覆盖与事件规则

- 默认 3 日或扩展 7 日窗口为 `report_date-(days-1)` 至 `report_date`，两端包含。
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

正式目标三件套中任一文件已存在时，prepare 默认单航班拒绝新 run；只有用户明确授权替换后才可增加 `--allow-existing-archive-replacement`，同日也不自动豁免。显式替换采用旧文件哈希前置条件的事务提交。最终回复必须报告三份绝对路径、保留条数、实际比例、来源成功数、日期有效率、补检/红队状态和仍未闭合的数据缺口。证据不足时允许少于 10 条或为空。

自动保存只授权正式新闻文件及新闻目录内的 `.pih_history_v2.json` 去重索引，不授权写入个人长期记忆、知识图谱、邮件、外部发布或其他系统。review challenge 只提供运行内绑定与防重放，不是外部运行时的加密身份签名；执行者必须真实调用独立 SemanticEvaluator；仅在 `deterministic_fast_path=false` 时另行调用独立 RedTeam。确定性快速路径以已登记的 NoL4Gate 回执满足红队阶段，不启动第二个代理；L4、重大资讯及冲突的红队要求不变。

Stage-C broker v2 continuation: parent must consume `next_action` on each operation; first 403 means choose an alternative original-source URL or purposeful different search, not silent closure. `broker-seal` requires ledger-grounded stop eligibility. Exact all-good bound-only evidence, or v3-only fully settled exact-required `bound_budget_exhausted` evidence, may close without artificial search; the latter preserves failures/successes and requires degraded coverage for exclusions (zero eligible: degraded/low). Date/source/lineage/semantic gates remain unchanged. Expired/error/pending evidence is retained for failed reconciliation, never backdated. See workflow_protocols.md Stage-C; New v3 runs use source600/grace300 (launch timeout 900000ms); 1.4, other budgets and old frozen runs remain unchanged.

### Timely parent finalization receipt (new native v3 only)

New native-v3 requests carry finalization.parent_receipt_version=1. The bound finalize --parent validates within the unchanged 300s grace and atomically journals parent-supplement-finalization/1.0 in run_manifest.parent_supplement_finalizations[gap_id], binding run/request/packet SHA, sealed broker evidence and completed_at, actual finalized_at, original/final draft SHA and exact final bytes. Retry the same CLI after interruption: only the journaled source/final bytes recover, without a new clock. Later finalize-supplement accepts unchanged timely-attested bytes while revalidating semantic/proof/terminal gates. Missing receipts retain strict grace; v2 and old frozen requests are unchanged. Never synthesize receipts for old events or use mtime; no budgets increase.
