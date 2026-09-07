# 协作审计工作流

只在需要事件级指标、现场计量、等待与重试分析、子代理效率、授权审计或保存报告时读取本文件。一般历史审计不强制新建遥测；无既有计量证据时如实报告缺口。

## 1. 建立范围

1. 定义根任务、时间范围、会话或仓库、数据来源和目标指标。
2. 区分只读审计与已授权整改；只读审计不新增批准回合。
3. 列出缺失时段、不可访问来源和可能改变结论的未知项。

## 2. 收集与标准化

所有冻结、标准化与回执文件只写入当前任务已授权的隔离 scratch；不修改来源或默认落入报告目录。只读且未授权临时写入时，使用既有稳定快照／事件，或披露无法冻结、标准化的限制，不默认为采样授权。活动来源需要冻结而又无可用快照时，不直接聚合活动文件。

```powershell
python scripts/freeze_jsonl_snapshot.py --source <ACTIVE_JSONL> --output <SESSION_SCRATCH>/activity.snapshot.jsonl --receipt <SESSION_SCRATCH>/activity.snapshot.receipt.json
```

报告必须披露冻结时间、源文件捕获字节数、稳定前缀终点、快照 SHA-256、记录数和是否排除了尾部不完整记录。

只读取用户提供、已连接授权或当前工作区内的证据。按 [SCHEMA.md](SCHEMA.md) 标准化事件，保留来源和行号，不回显提示词正文、凭据或私人内容。活动 JSONL 可能被运行时持续追加，必须先通过 `scripts/freeze_jsonl_snapshot.py` 冻结完整换行前缀；冻结器不重复解析 JSON 语义。提供回执时，快照先发布、回执最后发布并作为提交标记；聚合、引证和行号全部绑定已验证回执中的快照 SHA-256，不直接绑定活动文件。

Codex rollout 快照必须先执行现有标准化器，不得使用临时编写、未经测试的替代脚本：

```powershell
python scripts/standardize_codex_rollout.py --input <snapshot.jsonl> --output <events.jsonl> --summary <standardize-summary.json> --start <ISO8601> --end <ISO8601>
```

已有技能、授权或上下文恢复回执时再分别添加 `--skill-receipts`、`--authorization-receipts`、`--context-receipts`。标准化器不得从自然语言推断授权，不得把工具输入、输出或业务正文写入事件。它仅在实际 `diary_ops.py` 执行载荷中接受白名单回执，兼容新式 `diary-write-scope-v1` 与历史 `schema_version: 2 + component: diary_ops`；冲突回执失败关闭。只读查看 `generate_resource_manifests.ps1` 不算写入；实际调用该脚本和 `apply_patch` 才生成写入意图。

对 JSON/JSONL 输入运行：

```powershell
python generate_final_report.py --input <evidence-path> --strict
```

需要保存 JSON 时必须由用户指定输出位置，再添加 `--output <report.json>`。`--strict` 遇到跳过文件或记录、非事件信封、等待同键时间回退或缺失时间时返回 2；零条有效记录返回 1。部分覆盖不能宣告审计完成。CLI 对 JSONL 使用流式聚合，不把全部事件字典保留到内存。

## 3. 五类控制

### 等待

- 根任务同时最多保留一个等待调用。
- 有独立本地工作可推进时先工作，不为查看进度而等待。
- 等待超时不等于子代理失败；以状态变化、最终回包和产物验证判断。
- 同一 `state_version` 连续两次超时后，只读一次代理状态；若仍无变化，停止轮询并转做本地工作或结束等待。
- 第三次及以后同状态超时必须记入 `wait_gate_breach_count`；降低平均等待时长不能抵消门禁违例。
- 同一根任务和执行者内的等待时间必须单调；缺失或回退时，重复等待、连续超时和门禁违例指标不得继续给出数值。

### 技能载入

#### 历史审计（默认）

不因完整读取任一技能而运行计量脚本或追加遥测。仅消费既有、可定位到被审计时段的回执；缺少正式回执或 Token 字段就披露缺口，不用本轮补写回执证明历史载入、重复率或上下文恢复。读取技能的要求与写计量回执是两个独立条件。

#### 显式计量／授权现场采样

只有任务明确要求计量或目标确需现场采样，且当前授权覆盖采样和临时写入时，才在完整读取选定技能后运行：

```powershell
python scripts/skill_load_receipt.py --skill-path <SKILL.md> --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --event-id <THIS_LOAD_EVENT_ID> --output <SESSION_SCRATCH>/skill-load.jsonl
```

使用本次采样真实的根任务、执行者、epoch 和时间，不借用历史身份；隔离输出，不追加历史证据文件。报告单列现场样本、采样条件与历史覆盖，禁止合并冒充历史事实。Python 3、`tiktoken` 及本地 `cl100k_base` 缓存须可用；缺依赖或缓存时说明限制，不自动安装或联网下载，不以字符数估算 Token。计量口径、哈希、锁和幂等规则见下列要求与 SCHEMA。

#### 共同验证要求

- 继续遵守每回合完整读取已选择技能的要求。
- 只把同一 `root_task_id + actor_id + context_epoch + skill_name + skill_sha256` 的再次全文读取算作重复。
- `SKILL.md` 保留核心工作流和资源路由；详细 Schema、模板、变体与示例按需读取。
- 上下文压缩次数只反映观察到的事件。讨论技能与压缩的关系前核验共同时间范围、Token 口径和替代解释；占比存在也不能证明归因。
- 原始命令推断的 `skill_load_candidate` 与正式 `skill_load` 回执分开；确切匹配还要求正式回执的 `candidate_event_id` 指向同根任务、执行者、epoch、技能名称及路径哈希下的候选发生 ID。可用 `--candidate-event-id` 传入真实绑定；未绑定回执的业务范围配对只表示数量上限，报告须同列确切发生覆盖率。不要用当前文件哈希反填历史候选。
- 正式回执同时保存规范化路径哈希、内容哈希、Token、tokenizer 和 `event_identity: occurrence`。同一次真实载入的交付重放复用 `--event-id`；不同真实载入用不同 ID，同业务键重复载入因此可计数。省略 ID 表示一次新的现场发生，不是重放。不要仅因“脚本运行了两次”就宣称真实读了两次。
- 历史回执可能有业务键派生的旧 event_id，缺少发生身份时重复率为 `null`，同时披露观察数、未核验发生数和候选覆盖。不得批量为旧回执生成 ID。
- 本地回执 `token_measurement_basis: skill_text` 只测文本体积。不得直接除以账单输入 Token；只有 SCHEMA 中 tokenizer、`model_input` 基础、范围与完整包含关系均被明确计量时才计算占比，否则显示 `null`、原因及覆盖。混合口径分组报告文本体积，不估算成本节省。

### 错误与重试

- 每次失败先分类并生成错误签名，再决定重试、降级或停止。
- 每次重试只验证一个清晰假设，并记录变化；不得通过换组件或改错误标签规避重试预算。
- 第二次出现相同组件、操作和错误签名后停止盲试。
- 连接器 EOF 后，读取操作最多降级一次；写操作先确认远端副作用状态，未知时不得重放。
- 包装层分类以实际执行载荷为界并先移除 ANSI。`no_match`、预期 `validation_guard` 是可观测 outcome，不是执行器故障；语法、路径、工具接口、Unicode、Python traceback、嵌套工具和无法细分的脚本失败使用稳定签名分别计数。

### 子代理

- 仅按相互独立的证据面拆分，不把阻塞主任务的紧急步骤外包。
- 任务包传文件指针、哈希或行号、授权边界、最大回合、二元停止条件和回包 Schema。
- 任务包足以自洽时使用最小 fork；不能安全重述用户约束时传递必要的近期回合。
- 主任务继续处理本地工作；只接收结构化状态和证据指针，不回传完整历史或大段原文。
- rollout 的首条 `session_meta` 定义该文件 actor；全历史 fork 中内嵌的父线程 `session_meta` 只能作为历史证据，不能重新绑定当前 rollout 的执行者。

### 写入授权

- 只读审计不请求写入确认，也不生成持久报告。
- 用户已明确要求的范围内本地可逆编辑不追加确认。
- 外部、不可逆或长期记忆写入按动作、目标和载荷生成授权指纹；任何变化都需要重新确认。
- 连接器返回不确定结果时先查状态，不能把超时当成未写入。

## 4. 指标与防刷绿

- 等待同时看重复等待率、同状态超时簇和“有本地工作时等待”的次数；不能只降低等待调用占比。
- 重试同时报告有明确证据的盲重试、理由已记录、未核验和冲突数。`hypothesis_changed: false` 必须有 `retry_evidence` 指针且无相反变化描述，缺字段不能证明盲重试。盲重试率只用可分类子集作分母，必须显示分类覆盖；同签名超预算指标保持原计数口径，不能通过切换组件降低指标。
- 子代理使用 `child_tokens / (root_tokens + child_tokens)` 作为占比；另报 `child_tokens / root_tokens`，不要混称放大率。
- 子代理指标必须与完成率、返工率、质量门禁和相同任务类型的 P95 一起比较。
- 永久写入以授权指纹匹配率验证；“未发现越权”不等于没有事件证据。
- 写入尝试、提交类事件、确认提交、结果未知和授权匹配分别报告。新版状态区分 `no_write_intent_observed`、`attempts_without_confirmed_commit`、`outcome_uncertain`、`confirmed_commits_matched`、`confirmed_commits_unmatched`，不再输出旧 `no_writes/complete/partial`。缺少结果／输入覆盖或冲突时为 `outcome_uncertain`；未匹配也不自动证明实际越权。自然语言不能替代授权指纹。
- 上下文压缩后的恢复制品存在率不等于语义恢复率。只有最小目标、授权边界、已完成步骤和输出路径均经结构化字段核验时，才设置 `required_fields_verified=true`。
- 历史上下文恢复只使用既有回执。只有任务明确要求计量或确需现场采样，且当前授权覆盖采样和临时写入时，才把四类最小字段写入隔离 scratch 状态包并运行 `scripts/context_recovery_receipt.py --state <STATE_JSON> --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --output <SESSION_SCRATCH>/context-recovery.jsonl`；正文仅留在状态包，回执仅保留哈希和计数。新回执不得证明历史恢复。Codex 生命周期接线仅见 [CODEX-HOOKS.md](CODEX-HOOKS.md) 的适用分支。
- P95 样本不足时报告样本数和原始分布，不作稳定趋势判断。

## 5. 形成发现

证据门通过后读取 [ANALYSIS.md](ANALYSIS.md)，按任务收敛、用户介入、返工、自主性校准、维护价值、委派收益、上下文／规则负担、改进实验八个视角分析。先回答已验收与未收敛任务、必要决策、已证实的纠错／恢复负担及上次修复后续，再引用运行统计。保留失败、阻塞、放弃和未完成样本，不只挑成功记录。

可选 `collaboration_annotation` 仅由显式输入提供，合同见 SCHEMA §10；既有标准化器不从提示词自动生成它。原 CLI 会同时输出 `collaboration_analysis`：任务结局须有 settled 与实际验收连接，介入／返工须有原因和出处，整改须有同版本／cohort 的后续可比暴露。无历史注释合法但不可用；非法或冲突的新注释使 coverage partial、严格 CLI 返回 2。报告需展示来源范围、未知标签、可用分母及覆盖，不把实现单测通过称作运行收益；缺后续暴露时复发数／率为 null。

1. 分开写观察事实、计算结果、解释性推断和用户陈述。
2. 每条发现绑定可解析的事件或文件位置、置信度和替代解释。
3. 按安全影响、收益、成本和可逆性排序；连接器未知写入优先于纯效率问题。
4. 把技能可修、编排可修、运行时可修和政策待决分开，不把散文规则当成运行时实现。

## 6. 交付

在当前答复中先回答报告模板的六个结果问题，各结论旁列来源声明／已核验出处、任务／介入／返工／cohort 分母与未知，再给八个视角的发现及支撑运行指标。形成行动时读 [IMPROVEMENT.md](IMPROVEMENT.md)，仅选择下一项最小 SYSTEM 或 USER 实验，保留必要人类决策及安全门。只有用户明确要求文件、仪表盘或整改时才产生对应写入；报告模板位于 [report-template.md](report-template.md)。

默认模板缺证据时明确显示不可用／未知，不是完成审计。可在原有 `--markdown-template`／`--html-template` 中依据已核验的显式证据填写六问、八视角及覆盖；保留建议占位符，不分别手写建议表。旧聚合 JSON 验证器不认证 `collaboration_analysis` 扩展或保存后的篡改；应从授权输入严格聚合并人工核验指针。`report_pair.py` 不消费该扩展自动填报，只验证建议同源及提交完整性，不认证正文事实；没有新增报告 API。

需要持久化 MD/HTML 时，先运行：

```powershell
python scripts/report_output.py --period <1d|7d|30d|90d|year>
```

然后在会话 `scratch` 建立唯一 canonical manifest，并运行：

```powershell
python scripts/report_pair.py --manifest <manifest.json> --markdown <allocated.md> --html <allocated.html> [--previous-manifest <previous.json>] [--markdown-template <filled.md>] [--html-template <filled.html>]
```

默认归档目录为当前工作区的 `output/mentat-collaboration-audit`。建议编号、状态、验证结果、标准和证据只能在 manifest 中维护；脚本先验证 MD/HTML 可见内容一致，再写入并刷新隐藏暂存文件，排他发布 MD/HTML，最后发布 receipt 作为提交标记。上一批编号不得消失或静默换义。写后复算三份文件哈希、确认 HTML 自包含，并对大屏做一次视觉检查。原始事件、聚合 JSON、manifest、模板和调试文件仍放在当前会话 `scratch`，除非用户另行指定持久化目标。

## 7. 验证与归档合同

### 验证分层

- 硬错误：文件缺失或不可读、JSON 非法、Schema 版本或必需字段错误、字段类型错误、覆盖状态与问题清单矛盾。
- 软提示：固定章节或条目数不足、摘要较短、数字比例、关键词覆盖、措辞和建议数量。
- 人工判断：根因、因果、优先级、方案收益和政策建议。校验脚本不得替代这些判断。

### 报告归档契约

- 协作审计产出的 `.md` 和 `.html` 默认保存在当前工作区的 `output/mentat-collaboration-audit`。
- 用户显式指定的 `--output-dir` 优先。只有本次任务明确选择既有配置时，才可加 `--use-configured-output-dir` 读取 `MENTAT_AUDIT_REPORT_DIR`；环境变量本身不授权改变写入位置。
- 同一次审计的 Markdown 与 HTML 必须共享主干，例如 `collaboration_audit_7d_20260727_101530.md` 与 `.html`。
- 原始会话、标准事件集、聚合 JSON、提示词正文、凭据和调试文件不得默认写入报告目录；中间态放入当前会话的 `scratch`，JSON持久化仍需用户指定路径。
- 普通只读审计不自动落盘。用户提出“生成报告、面板、大屏并保存”即授权保存该次请求的本地MD/HTML，不授权整改、外部发布、长期记忆或Vector Lake写入。

### 完成检查

- 每个结论都引用日志位置、时间点、调用记录或可复算指标。
- 报告披露分子、分母、样本量、缺失数据和跳过记录；严格聚合无未解释失败。新版聚合带 `metric_semantics_version: 2`，旧无标志报告只读兼容，不能将旧指标直接混入新口径趋势。解析 coverage 完整不表示发生身份、重试理由或 Token 口径完整，仍须检查各项证据覆盖。
- Codex rollout 回放中，嵌套错误不得保留为顶层成功；写入提交数为 0 时必须同时证明标准化器没有识别到写入意图，否则不得给出授权假绿结论。
- `skill_load_candidate` 不能冒充正式 `skill_load`；只有带路径哈希、内容哈希、Token 与 tokenizer 的回执进入正式载入指标。
- 上下文恢复存在率与最小目标、授权、完成步骤和输出路径的语义核验率分开报告。
- 修改建议必须由 canonical manifest 同源生成；MD/HTML 中的 `R-xx` 集合、顺序、状态、验证结果、标准和证据全部一致，且回执哈希与落盘字节复算一致。
- 不使用不存在的数据填充图表或指标。
- 敏感信息已删除或遮蔽。
- 未经明确授权，没有执行任何修复、持久化或配置修改。
- 持久化任务的MD/HTML位于同一归档目录、共享主干、均非空，并返回实际存在的绝对路径链接。
