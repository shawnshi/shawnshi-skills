---
name: personal-intelligence-hub
description: 生成基线优先、跨技术与医疗数字化并带历史去重的日资讯简报；区别管理周刊、事件雷达和论文综述。正式简报自动保存，生产预览仍产生运行中间态。当用户要求生成当日资讯简报、基线优先日报或跨技术／医疗数字化速览时使用。
---

# 技术与医疗数字化资讯简报

## 适用合同

1. 当前正式产物使用 `references/briefing_schema.json` 1.4；历史 v1.0/v1.1、`references/briefing_schema_v1.2.json` 及 `references/briefing_schema_v1.3.json` 由冻结 validator 只读回放，不改写旧档。
2. 用户只说“今日资讯简报”时：报告日为 Asia/Shanghai 当日，默认窗口为报告日及之前 2 日，共 3 个日历日；如审核去重后条目不足 10 条，且非用户显式指定，则新起一轮扩充至 7 个日历日，不再兜底补充；地域为中国、美国与全球。
3. 默认领域请求比例为技术 60%、医疗数字化 40%。用户指定主题或比例时覆盖默认值并记录来源与理由。
4. 正式日简报默认自动保存。用户明确要求不保存时，在两份回执登记后运行 `python -X utf8 scripts/run_daily.py preview --manifest <run_manifest.json> --refined <refined_core.json>`；只返回通过门禁的确定性 Markdown，不调用归档步骤。注意：preview 不保存仅保证不向新闻目录写入正式三件套与历史索引，但运行前置步骤仍会在 runtime 目录产生必要中间态文件；若用户要求全程物理零磁盘写入，不得启动生产前置流程。
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

运行 prepare 前必须读取 `references/workflow_protocols.md` 的 `baseline` 节，核对冻结、网络/超时与覆盖保留合同，再使用统一入口：

```powershell
python -X utf8 scripts/run_daily.py prepare --report-date YYYY-MM-DD --timezone Asia/Shanghai --article-broker-version 3
```

记录返回的 `execution_cli_path`。下文所有 `python -X utf8 scripts/run_daily.py ...` 在生产 run 中均表示 `python -X utf8 <execution_cli_path> ...`；不得在 prepare 后改回安装目录脚本。

prepare 必须冻结 run/bundle/历史与候选血缘，再完成基线扫描和缺口登记；基线未达 completed/degraded 前不启动补检，启发式候选不得直接成为最终事实或归档内容。完整网络、超时、覆盖与失败保护见执行前必读的 baseline 节。

“昨日资讯简报”显式传入昨日日期。不得用运行时滚动窗口或当前日期命名昨日文件。

### 2. 只针对缺口调用补检代理

进入本阶段前，父任务读取 `references/workflow_protocols.md` 的 `supplement` 节；有补检请求时，再读 `runtime` 节，完成预算预留后才可启动。代理只接收已登记最小 packet，不得加载本参考文档或主会话历史。seal 会启动 300 秒 finalization grace：父任务必须在 seal 后立即完成该 gap 的 `finalize --parent`，不得先用其他 gap 的 broker 操作；同一命令内完成两步用 `python -X utf8 scripts/supplement_seal.py --request <supplement_request.json> --gap-id <gap_id>`（draft 未就绪时它只报告 grace 截止时间）。reserve-fetch 只接受 required bound URL 或已记录 search receipt 发现的 URL；未尝试但非 required 的 bound 候选不可抓取。600 秒 source 时钟自 `broker-checkpoint` 起算，不得先批量 checkpoint 多条 gap 再逐条收尾，否则未开跑的车道会提前到期。父任务 fallback 的顺序必须是 seal → 写 draft → finalize；先写 draft 会让 seal 被 guard 拒绝（draft/result 已存在）。

仅在基线 `completed`/`degraded` 后，按已登记 gap/lane 先核验绑定候选，再补缺口；根任务不重复已分派检索。canary 基础设施失败即停止 fanout；成功后最多 3 个 worker 并行。保留真实日期、访问日志与失败，禁止弱资讯补数。代理只写授权 draft，父任务确定性校验后原子发布；timeout/失联按持久化逐 gap 状态 reconciler 收口，不得只依赖 stdout。

prepare 未返回 request 时，脚本已登记结构化 `no_increment`，不要伪造补检结果。

所有代理异步启动，交互会话禁止阻塞等待或轮询；完成/进度事件后按 `runtime` 节状态机恢复。只凭 running、文件存在或聊天消息不等于进展或完成；正式校验通过后不再等待额外聊天。失败请求封闭，不得复用 request/invocation/输出路径重启；重试创建全新 run。

worker 席位没有公网工具，只有 `contact_supervisor`。分派的 packet 已强制「context 之后第一步就是联系父级要 broker 序列」；父任务收到该请求后应立刻代跑整条 broker 链并回传 sealed 证据，不要让 worker 自行探索。worker 因工具预算耗尽而以 BLOCKED 结束、未交付 draft 时，**不算基础设施失败**，也不触发 `stop_fanout_on_canary_infrastructure_failure` 之外的停滞：按 `workflow_protocols.md` 的父级 fallback 顺序（seal → 写 draft → finalize）接管该 gap，并在最终交付中披露 draft 由父级撰写。

启动前仍执行真实 Token/费用预留与下游 headroom 预留，终态按去缓存预算口径结算；遥测不可用不得估算或释放完整预留。2026-09-16 授权已移除运行级 Token/费用总额上限：预留额度继续登记用于可观测性，触达旧上限不再阻断启动；Token/费用从来不是活动硬停止器，活动中的有界停止依赖 `timeout_ms`、`tool_budget`、查询/URL/轮次限制与收口帮助脚本；详见 `runtime` 节。

### 3. 事件合并与语义评估

进入本阶段前，父任务读取 `references/workflow_protocols.md` 的 `semantic` 节及 `runtime` 节，再 prepare-review。独立 `SemanticEvaluator` 仅运行已绑定 helper、读取紧凑 eligible candidates、写动态草稿并 finalize，不得扩展候选、重读完整上下文或重新联网访问登记 URL。

按访问/日期/来源门、结构化事件身份、独立佐证、领域内排序和请求配比合并；不足 10 条不补数。`single_secondary_allowed=true` 时单一独立二手来源就是合格候选，不得据此自行加严排除。父任务仅在语义代理失联时按 fallback 补写；一旦改动或追加 `selected_items`，必须同时重写 `punchline`/`insights`/`digest`/`market` 使叙述覆盖最终选定集合，并逐条核对每条的 `title_zh`/`summary_zh`/`fact` 与其 `url` 的已核验正文一致（不得把其他条目的正文归到本条目）。确定性 helper 必须重跑历史去重、验证全部候选对象哈希血缘和访问日志；heuristic 或绑定不一致封闭失败。语义 core/receipt 是可重入阶段提交而非跨文件单一原子事务，中断复用已验证字节与原 invocation 恢复。两份产物登记并确认就绪后才能进入红队，不得并行预启动。

### 3a. 决定是否扩大窗口

语义 core 与回执通过门禁后、红队与归档前，运行 run-scoped CLI：

```powershell
python -X utf8 <execution_cli_path> check-expansion --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json>
```

该命令重跑语义证据、历史去重及血缘校验，再按 `top_10` 中的独立事件计数（不是来源候选数）。无效 core/回执返回非零退出码，不扩大窗口。默认 3 日运行少于 10 条时返回 `action=expand` 和 `next_argv`；按该参数数组启动一次新 7 日运行，保留旧运行且不提前归档 3 日结果。`next_command` 仅为 POSIX Shell 展示，不直接粘贴到 PowerShell。显式窗口、已有扩窗链接或 7 日运行不再次扩窗；不足仍少报。只有最终选定运行进入红队与归档。用户可以在看到条目数后显式指定「按现有条目出稿、不扩窗」：这属于第 2 条的「用户显式指定」，可跳过扩窗，但最终回复必须把该偏离、条目数不足 10 的原因和未闭合的领域缺口一并披露。

`prepare-review --kind red_team` 在确定性快速路径下会自行写入 `output_paths.review_receipt` 并立即登记该阶段。该文件此后是只读归档件：不得重新写入、重新格式化或手工伪造，否则 `forge` 会以 `red_team receipt bytes changed after registration` 永久失败且无修复命令。同样，已登记的 `*_review_request.json` 不可重建（immutable once registered），需要新回执就必须按 recovery 合同开新生命周期。

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

## 显式授权恢复（新生命周期，不改写旧运行）

仅在已有明确恢复授权覆盖原窗口、完整已结算证据且不重扫时，才进入新生命周期恢复；调用任何 recovery_lifecycle 或 late_telemetry 命令前必须完整读取 `references/workflow_protocols.md` 的 `recovery` 节。启动、恢复或结算代理前另读 `runtime` 节；重新独立语义评审及条件红队、旧运行不可改写和原预算门不变。

## 日期、覆盖与事件规则

- 默认 3 日或扩展 7 日窗口为 `report_date-(days-1)` 至 `report_date`，两端包含。
- `published_at` 必须为窗口内 `YYYY-MM-DD` 已知日期；候选为 ISO datetime 时按其自带时区取日期后规范化。`event_date` 可未知，但不得晚于发布日期。
- 发布日期基准（2026-09-14 授权）：正文未产出可识别发布日期、但 `article_core`（除正文日期外的全部文章判据）成立时，登记可改用绑定 lane 已登记的 feed 发布日期，`published_at_proof.parser_rule` 记为 `pool-declared/1`；正文自带日期永不被覆盖，`published_at_source` 仍不得为 unknown/retrieved_at，窗口门不变。
- 标题基准（2026-09-14 授权）：正文抽取标题为空或不落在 8..240 时，`article_core`/`article` 判据可回退使用绑定 lane 已登记的 feed 标题，metadata 记 `title_source=lane-declared/1`；正文标题合法时永不回退。
- 二手佐证降级（2026-09-14 授权）：focus config 的 `corroboration_policy.single_secondary_allowed=true` 时，单一独立二手来源（已验证访问 + 完整事件身份）可作为 `corroboration_status=single_secondary` 入选；`multi_independent` 仍是首选，同一事件不得重复计数，置 false 即恢复严格行为。二手来源仍需 ≥2 个独立来源佐证，门槛不变。
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

## 维护说明（修改本技能后必做）

`resource-manifest.json` 为 `SKILL.md`、`references/**`、`scripts/**` 等声明文件登记了内容哈希，未同步时任何调用都会以 `skill resource manifest hash mismatch` 失败。改动本技能任何声明文件后，在技能库根目录运行资源清单生成器（该工具的 `generate` / `check` 子命令，参数 `--root . --include-skill personal-intelligence-hub`），再用它的 `check` 子命令确认 `stale=0`。

不要在本文件里写技能根目录以外的相对路径：生成器会把 `scripts/...` 这类 token 记入 `declared_local_dependencies`，而校验器只在技能根内解析，两边基准不一致时同一文件会被同时记为“存在于库根”和“技能根内缺失”，从而报上述哈希不符。

同类陷阱：`atomic_dump_json` 使用文本模式写入，Windows 下落盘为 CRLF。用 Python 重写已登记的 JSON 回执时必须保持同样的换行与缩进，否则哈希不一致，`forge` 会以 `receipt bytes changed after registration` 永久失败。诊断与回归用 `python -m pytest -q scripts/`；测试中任何 `subprocess.run(..., text=True)` 都要加 `encoding="utf8"`，否则中文输出在 cp1252 本地化下会触发 UnicodeDecodeError。

