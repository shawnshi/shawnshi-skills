# 命令目录

运行前先检查 `scripts/requirements.txt` 与命令 `--help`。不要自动安装依赖或修改全局环境。默认遵循 [free-data-policy.md](free-data-policy.md)，不把付费终端或机构数据库设为前置条件。

## 稳定入口

优先运行 `python scripts/pia.py --help` 查看稳定子命令。该入口只做参数路由和状态归一，不绕过底层业务门禁。若某个子命令尚未接通，必须返回非零和结构化未完成状态。

所有显式文件或目录参数均在调用者工作目录中解析一次，再以绝对路径交给子进程；含空格或中文的路径需按 Shell 规则引用。`calibrate` 的 `PIA_ADVICE_JOURNAL` 环境路径也采用此口径。未提供的路径不触发额外输入发现。

任何暴露 `--decision-scope` 的路由（`daily-run`、`daily-sync`、`edgar-fundamentals`）**默认 `advisory`**；需要只给研究结论时显式传 `research_only`。该默认值不会放宽任何证据门：数据缺口、Thesis 未评估或来源不可核验仍按各命令的失败关闭契约处理。

稳定路由的子进程传输要求 Windows Python >=3.12（本轮验证为 3.13），POSIX 需实际支持非阻塞管道。启动业务子进程前用自有管道探测能力；不支持时返回 `child_transport_unavailable`，不启动业务代码，不归类为无数据。无需新增依赖或全局配置。

stdout、stderr 各限 32 MiB（33,554,432 字节，含边界），轮流以最多 64 KiB 读取；空闲等待最多 5 ms。超过任一上限即丢弃部分输出、返回 `child_output_size_limit` 并终止该子进程，不能将有效 JSON 前缀视为成功。完整有界字节读完后才按 UTF-8 解码，保留原有 `errors="replace"` 语义，分块边界不会破坏多字节字符。业务退出码、非法 JSON、报告文件是否新生成仍独立核验；JSON 报告文件也限 32 MiB，使用上限加一字节读取。

原有 300 秒执行期限不变；超时、容量超限或取消时，最多等待 1 秒终止，再最多等待 1 秒强制结束并回收直接子进程，无法回收属于错误。路由不拥有任意后代进程树；直接子进程退出后只排空当前可读字节，不等待后代持有的管道 EOF。不新增读取线程或临时传输文件。已由明确命令创建的报告可能在失败后保留，失败不授权自动归档、删除或重跑。

## 主动研究的离线交接

`pia.py` 的 stdout 是状态信封，下游输入需要信封中的原始 `result`，不能直接把整个 stdout 当作验证、扫描或构造报告。主动研究四个子命令没有 `--output`；`scenario --output` 是另一个命令的原始结果写出选项，不能用于这条链路。

以下 Python 示例在调用者工作目录中运行四阶段，输入文件名见代码。仅当用户已逐项授权读取这五个输入和创建 `validation.json`、`scan.json`、`construction.json`、`proposal.json` 时运行；示例不增加自动保存权限。可将代码用于已授权的任务脚本，以 `python handoff.py <pia.py 的绝对路径>` 运行。输出采用独占创建，已有文件不覆盖；任何失败都停止下游，保留已完成的独立阶段。写出中断可能留下不完整文件，必须检查后另行授权清理或更换输出路径，不得直接重跑覆盖。

```python
import json
import subprocess
import sys
from pathlib import Path

PIA = Path(sys.argv[1]).resolve(strict=True)


def stage(arguments, output):
    completed = subprocess.run(
        [sys.executable, "-B", str(PIA), *arguments],
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=300,
    )
    envelope = json.loads(completed.stdout)
    if (
        completed.returncode != 0
        or envelope.get("status") != "complete"
        or envelope.get("exit_code") != 0
        or envelope.get("route", {}).get("child_exit_code") != 0
        or not isinstance(envelope.get("result"), dict)
    ):
        raise RuntimeError(f"Stage stopped: {arguments[0]}: {envelope}")
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(envelope["result"], stream, ensure_ascii=False, indent=2)


stage(["alpha-validate", "package.json", "--policy-file", "promotion.json"],
      "validation.json")
stage(["alpha-scan", "package.json", "--validation-report", "validation.json",
       "--policy-file", "scan-policy.json"], "scan.json")
stage(["portfolio-construct", "scan.json", "--policy-file", "construction-policy.json"],
      "construction.json")
stage(["rebalance-proposal", "construction.json", "--policy-file", "proposal-policy.json"],
      "proposal.json")
```

每个入口对每份包、策略或上游报告只读取一次，先对实际解析对象计算规范 JSON SHA-256，再将同一对象交给计算；禁止重新加载路径取哈希或对清洗后的对象补算输入哈希。规范化保持 Unicode、按键排序、使用紧凑分隔符，因此缩进或键顺序不改变摘要。扫描核对验证报告绑定的包摘要，并记录验证报告及扫描策略摘要；构造和提案继续记录其上游报告与策略摘要。包内来源定位和证据哈希仍须由调用者核验；摘要只能绑定内容，不能证明来源真实或给予交易权限。路径在读取前已被他人替换仍可能改变输入，跨文件快照也不是事务；输入需由调用者保持不变，业务哈希门禁保持失败关闭。

## 编排与输入生成（2026-09-27 新增）

这三个入口把此前必须手写的胶水步骤变成受门禁约束的命令；它们只消费上游制品、从不发明数值，也不下单或改写持仓。

- `pia.py refresh --positions-file <positions.json> --task-dir <dir> [--cache-dir <dir>] [--fx-observation-file <yf-cny-capture.json>] [--fx-pair USD=CNY=X] [--max-fx-age-hours 72] [--force]`：写入**隔离派生快照** `inputs/positions_fx_snapshot.json` 与 `out/refresh_receipt.json`。只替换 `exchange_rates` 与 `exchange_rate_metadata`，原持仓文件永不改写（回执记录改前/改后哈希）；仅与待替换币种相关的既有契约错误被记录为 `healed_contract_errors` 并被修复，其余错误仍失败关闭；观测缺失或超出 `--max-fx-age-hours` 时返回 `insufficient_data`，绝不用默认汇率补位。
- `pia.py daily-run --positions-file <positions.json> --task-dir <dir> [--cache-dir <dir>] [--dashboard-root <stocks-root>] [--thesis-evidence-file <pack.json>] [--scenario-portfolio <p.json> --scenario-assumptions <a.json>] [--holiday-calendar-file <table>] [--coverage-probe-file <spec.json>] [--risk-history <SYMBOL=file> …] [--risk-diagnostic-out <file>] [--skip-watchlist] [--plan-only] [--now-epoch <epoch>] [--reuse-artifacts] [--record [--ledger <file>]]`：以**单一评估时点**串行执行 refresh → quotes → daily_sync → weights（可选 watchlist / scenario）；带 `--thesis-evidence-file` 时只运行一次带包的 daily_sync，并保留相同内容的兼容制品 `out/daily_sync_with_thesis.json`。行情 `completeness.complete=true` 允许独立计算权重，但 Thesis 未评估时 `daily_sync` 和整轮均为 `incomplete`、退出码 1；无证据包不会假装 Thesis 已评估。行情未闭合或硬失败则依赖阶段不运行；汇总写入 `out/daily_run_summary.json`（含逐阶段状态、制品、越界边界与输入哈希，以及 `run_inventory`：声明范围、逐阶段范围、已运行/未运行阶段及原因、保守的 `valid_until`；并以 `status_consistency` 对照顶层与阶段推导状态）。中止路径（refresh/quote/replay 失败）同样携带该清单，不得只给出半张阶段表。`--plan-only` 只列出计划。`--decision-scope` 默认 `advisory`，需仅研究时显式传 `research_only`；缺证据仍不会将 Thesis 升级为已评估。**重复运行需显式 `--force`**：同一 `--task-dir` 再次运行会被 refresh 阶段的派生汇率快照阻断（exit 3、`derived_snapshot_exists`），因为覆盖的是流水线派生物而非用户输入；已有 `out/quotes.json` 后构建 `thesis-pack` 再回跑的文档化流程应传 `--force`。**连续性与幂等（`--reuse-artifacts` / `--record [--ledger <file>]`）**：`--reuse-artifacts` 让同一任务目录复用自己已有的 `inputs/<派生快照>` 与 `out/quotes.json`（不再重拉），但复用必须可证：行情包必须存在、`portfolio_batch_audit.coverage_complete` 为真，且 `portfolio_snapshot_binding` 与本次持仓快照逐字相符（按 `symbol/quantity/currency/market/asset_type` 规范化）；任一不成立即 exit 3、`reuse_artifacts_unusable`，**不回退去拉新数据**（静默重拉会产出与本轮声明不同的证据）。复用不会静默：阶段记录带 `reused: true`、`detail_status` 为 `reused_derived_snapshot`/`reused_existing_quote_batch`，汇总新增 `reused_artifacts`（含 `reuse_checks`）；报价时效与逐笔合同仍由重放阶段重算，本参数不跳过任何证据门。`--record` 在本轮汇总落盘后将该 run 追加到 append-only 触发器台账（默认 `<task-dir>/../pia_trigger_ledger.jsonl`，可用 `--ledger` 指定，目录需已存在），同摘要重复追加被 `entry_id` 拒为 `already_recorded`；结果写在汇总的 `ledger` 字段（`appended`/`entry_id`），台账写入失败不会把已完成的 run 伪装成失败。**就地重跑会覆盖，但不会静默覆盖**：同一 `--task-dir` 的任何重跑（含 `--reuse-artifacts` 绕过 `derived_snapshot_exists` 的情形）都会重写本目录的 `out/daily_run_summary.json`、`out/weights.json`、`out/daily_sync.json`；因此每次重跑在**动任何东西之前**先记下被替换的 run（`previous_run`：被替换 summary 的 `summary_sha256`/`generated_at`/`status`/`detail_status`），并 append 一行到 `out/run_replay_history.jsonl`（含被替换 summary 的 sha256、本次范围、复用阶段），可串成链；首次运行不产生 `previous_run`、也不创建该文件。中止路径同样记录。“幂等重跑”指的是复用可证而不重拉，**不**意味着上一轮结论会被保留——需要保留时应先拷到新目录。 `--coverage-probe-file <probes.json>` 可挂入**可选的通道覆盖探测阶段**（放在关键路径之后：refresh→quotes→daily_sync→weights→watchlist→coverage-probe→可选 thesis/scenario）；该阶段逐条执行 `coverage-probe`、把每条的判定、计数与查询质量备注写入 `out/coverage_probe_<channel>_<target>.json`，并把未证明项列入 `unproven_probes`。**阶段状态恒为 `complete`**（它的任务是探测，不是证明），因此未证明不会把整轮日报降级为 insufficient_evidence；`--coverage-probe-file` 规格在开跑前校验（探针字段、同类声明、重复项），非法即 exit 3、不启动任何阶段。汇总还写入 `residual_unknowns`（本轮**未建立**的东西：未完成阶段、阶段错误、未证明探针、阀值未定义标的、`run_not_complete`，以及恒存的两条结构性未知 `account_rules_not_verified` / `cost_model_not_sourced`），使“行情与阶段全 complete”不会被读成“已可交易”。
- **单命令就绪（`--actionability-assessment <snapshot.json>`）**：提供一个 A 股条款快照（`pia_cn_actionability_v1`）时，`daily-run` 在末尾增跑 `actionability-gate` 阶段，把 gate 裁决写入 `out/actionability_assessment.json`（gate 读的是输入快照，readiness 读的是这个裁决产物），随后以该 run 自身的制品生成 `out/readiness_rollup.json` 并把它作为 `readiness` 字段附到 `out/daily_run_summary.json`。状态映射显式且失败关闭：gate `complete` → 阶段 `complete`；`market_closed`/`insufficient_evidence` → `insufficient_evidence`（不可执行 ≠ 失败，退出码 2）；`invalid_input` 与任何未识别原生状态 → `failed`（退出码 3）。gate 不是 `complete` 时整轮 `detail_status` 为 `actionability_gate_<原生状态>`（如 `actionability_gate_market_closed`）。不提供该参数时行为与以往一致，`readiness` 字段与 gate 阶段均不出现。无论哪种结果，就绪结论都不是下单授权（`non_executable`、`human_review_required_no_order`），人工门恒列出。
- **已请求阶段失败即整轮不完整**：`daily-run` 记录每个阶段的状态。凡调用方**显式请求**的阶段（watchlist / coverage-probe / risk-diagnostic / thesis / scenario）返回 `insufficient_data`，轮次 `status` 置为 `insufficient_evidence` 且 `detail_status=requested_stage_incomplete:<阶段>`；所有阶段状态还与其退出码、`valid`、`completeness.complete` 合并，硬失败优先，不能由其他完成阶段抵消。coverage-probe 永远等于 `complete`——它的产出本身就是"覆盖已证明与否"这一判定，探测失败不等于任务失败；而 `--risk-history` 请求的风险诊断若无法产出（历史不足/文件缺失），那是真的没有交付物，必须让整轮可见地降级。
- `pia.py dilution --symbol <SYM> … --as-of-date <YYYY-MM-DD> [--class <SYM=stock|fund>] [--lookback-days N] [--threshold R] [--out <file>]`：**A 股股本变动（稀释/增厚）评估**。从 cninfo 股本变动台账（`akshare.stock_share_change_cninfo`，单位万股 → 股）取签名变动与变动原因，逐事件给出生效日、公告日、总股本/流通股本、变动股数与比例、以及事件性质分类（`capital_issuance` 增发/H 股上市、`conversion_or_exercise` 转股/行权、`buyback_or_cancellation` 回购注销、`share_split_equivalent` 转增/送股、`restatement_no_change`、`other_share_count_change`）。**点数时纪律**：事件以**公告日期**判断可见性、以**生效日期**呈现，因此历史回放看不到未来公告。**口径纪律**：转增/送股只改变股本、不改变每股经济含义，故单列 `economic_change_ratio` 与 `economic_direction`，且**重大性只按经济变动判定**（`material_change` / `material_events` / `largest_economic_event`）。ETF/LOF 等开放式基金为 `not_applicable`（份额变动来自申赎，不是稀释），非 A 股为 `not_an_a_share_issuer`；通道返回空或异常为 `insufficient_data`，绝不把缺数据当作零变动。
- `pia.py build {scenario,inverse-vol,thesis-pack,dataset-manifest} --task-dir <dir> …`：从上游制品生成可过门禁的输入。`scenario` 由 `weights.json` + 已确认政策生成 weight_snapshot/情景/约束并把 `dataset://` 绑定复制进任务命名空间；`inverse-vol` 由外部波动率观测生成 `pia_inverse_volatility_policy_v1`（现金桶权重冲突时返回 `cash_bucket_weight_conflict` 而非编造现金目标）；`thesis-pack` 自行计算每个证据原件的 `content_sha256` 并校验 `portfolio_snapshot_binding`；`dataset-manifest` 登记/合并本地制品。
- `pia.py etf-packet --evidence-file <evidence.json> --task-dir <dir> [--symbol …] [--as-of-date …] [--provider-source …] [--provider-source-locator …] [--provider-adjustment …] [--allow-unverified] [--force]`：为 ETF 历史完整性**装配并校验** packet。官方公司行动必须由调用方提供且逐条带 `evidence_file`/`evidence_locator`（工具自行算哈希，绝不从价格序列推导事件）；零结果必须附可审计对照（`official_coverage.control_query.symbol` 不同于标的，且 `channel_scope` 声明通道覆盖范围——通道性零不能冒充“无事件”）；仅在真实门禁 `packet_verified=true` 时写出 packet，否则只留诊断回执（`--allow-unverified` 才保留未验证件）。
- `pia.py history {index,diff} --task-root <pia根目录> [--depth N] [--registry …] [--write] [--from <run>] [--to <run>] [--sections weights,boundaries,quotes] [--strict] [--summary]`：跨运行的注册表与差分。`index` 扫描各运行目录的状态/权重/报价时点/越界边界/阶段状态、制品哈希，以及该 run 自己声明的**未运行阶段及原因**（`run_inventory.stages_not_run`；排序依据按显式程度报告），**默认只读**，`--write` 才落 `pia_run_registry.json`；`diff` 默认比较最近两次运行，输出权重变动（pp）、边界新增/解除与状态迁移、报价时点变化、运行与阶段状态迁移。**比较段三态**：`weights`（主载荷）、`boundaries`、`quotes` 各为 `computed` / `not_requested` / `not_comparable`；无法比较的段**一律置 `null` 而不是空集合/空字典**——否则 `{}` 会被读成“无变化”，`symbols_added/removed` 也会把“某侧没有 weights”误报成“所有标的被移除”。**宽容来自 run 自己的声明，不来自宽松默认**：仅当缺失侧的 `run_inventory.stages_not_run` 给出了原因（`skipped_by_flag:*`、`not_reached_due_to_upstream_incomplete`）时，`boundaries`/`quotes` 的缺失才降级为 `warnings`（`status=complete_with_warnings`、`detail_status=diff_computed_with_warnings`、退出码 0）；`weights` 是差分主载荷，**永不被软化**；未声明的缺失（文件被删、被截断、旧 run 无该声明）仍是 `gaps` / `diff_partial` / 退出码 2。`--strict` 关闭降级（任何缺失都阻塞）。`--sections` 只把你点名的段纳入阻塞：未请求的段报 `not_requested`，既不算完成也不算缺口。**防退化**：所有被请求的段都不可比较时返回 `nothing_comparable` / 退出码 2，不允许宽容退化成一张漂亮的空差分。段缺失与无 `daily_run_summary.json`（仅有 weights 的 rebalance 任务目录）均按警告具名，不伪装成“无变化”。未知段名或空的 `--sections` 提交返回 `failed` / 退出码 3。嵌套运行需显式 `--depth`。路由层把 `complete_with_warnings` 映射为 `complete`（warnings 随 `result` 保留），但退出码非 0 或未知原生状态仍失败关闭。
- `pia.py report --run-dir <dir> [--out <file>] [--expect-scope research_only|advisory|actionable]`：把一次运行的 JSON 制品渲染为**确定性** Markdown（无渲染时间戳，两次渲染字节相同，可哈希/差分），含身份块、run 清单（声明范围、逐阶段范围、已运行/未运行阶段及原因、保守 `valid_until`、状态一致性）、阶段表、行情覆盖与时效（含 provider 回执）、**事件红队（Thesis）**、**仓位限制（策略派生）**、当前权重、观察边界、情景、风险诊断、**覆盖探针**、**残余未知**、**可执行性就绪**与缺口表；渲染器**不新增判断**，缺制品一律写作缺口（`residual_unknowns` 缺失或为空列表均按缺口行处理，不得读成“零未知”）。**可执行性就绪**章节逐条列出前置条件（整体状态、行情覆盖、provider 回执、Thesis 已评估、评估时点是否交易时段、`out/actionability_assessment.json` 裁决、账户规则与成本模型）及三种核验状态（已核验/未核验/未提供），并在存在未核验项时给出“不得读作就绪”的裁决；该制品**可缺且不列入缺口表**（gate 是独立调用），但核验通过也不产生下单授权（`human_review_required_no_order`）。
  - 范围取自制品而非渲染器：优先级 `daily_run_summary` → `weights` → `daily_sync(_with_thesis)`；主制品声明冲突或值非法即 exit 3 且**不写报告**；无主制品声明时渲染为 `unknown` 并 exit 1（仍写出报告以暴露缺口）；`--expect-scope` 不匹配即 exit 3。
  - 非主制品自带的范围标签（如 `out/position_limits.json` 的 `observation_only`）视为**制品本地标签**，在章节标题与 `scope_annotations` 中显式列出，既不静默丢弃也不使一致的 run 失败，也不参与 run 范围解析。
  - 报告 JSON 信封（`--out` 时）另带 `actionable_readiness`：`verdict`（`verified` 仅在全部前置条件已核验时成立）、`unmet`、`prerequisites[{prerequisite,verified,evidence}]`（`verified` ∈ true/false/null，null 即“未提供”）与 `gate_artifact_present`；它只陈述本轮已建立什么，仍然不构成下单授权（`human_review_required_no_order`）。
- 就绪汇总：`pia.py readiness --run-dir <dir> [--out <rollup.json>]`（封装 `pia_readiness.py`，**只读**：不重拉数据、不重判、不写回 run 目录）。把已发生的 run 汇总为单一裁决：**机器前置条件**（本轮状态、行情覆盖、provider 回执、Thesis 评估、交易时段、gate 快照）与**人工门**（账户规则与成本模型，run 自身制品永远无法关闭）分开列出；`residual_unknowns` 缺失记作 `residual_unknowns_declared=false` **阻塞项**，绝不读作“零未知”。原生状态 `ready_for_human_review` → `complete`/exit 0（仍为 `human_review_required_no_order`，非下单授权）、`not_ready` → `insufficient_evidence`/exit 2、范围冲突/非法或未知状态 → `failed`/exit 3。该路由**不接受 `--decision-scope`**：范围一律从制品读取，未声明则计为阻塞项。
- `pia.py trigger-ledger {append,list,due,close} …`：运行级触发器台账（append-only，独立于 `advice_journal`）。`append --run-dir <dir> [--task-root <root>|--ledger <file>] [--review-days 90]` 记录该次运行的权重、越界边界（含观测价与报价时点，取自同次运行的权重行）、阶段状态与复核到期日；同一次运行重复追加会被 `entry_id` 抦下（`already_recorded`）；缺边界证据时记 `null` 而非空列表。`due --as-of <date>` 列出到期未复核项，`close --entry-id … --note … --outcome …` 记录复核结论并使其不再出现在 `due`。
- `pia.py thesis-ledger {init,append,show,list} --file <ledger.json> …`：**用户确认的 Thesis 条件版本链**。`append` 必须带 `--confirmed-at`（ISO 日期）与 `--source-locator`（非保留测试定位符），回填（早于最近版本）被拒绝；条件需 `id`/`metric`/`operator`/`due`/`channel`，数值型算子必须有数值阈值（无阈值规则用 `operator=qualitative`）；`show --as-of <date>` 返回**该日生效**的版本（而非最新版），无生效版本或本账本无该标的时返回 `insufficient_data`。写入采用同目录临时文件 + `fsync` + 原子替换。
- `pia.py labels {vocab,check} [--axis …] [--file …] [--previous …]`：**解释性判断词表**。`vocab` 列出某轴的允许标签与定义；`check` 校验一份 label 指派文件：标签必须在词表内、`as_of` 必填、理由必填，需证据的标签必须带 `evidence_ids`，强断言（`fatal_breach`/`materially_weakened`）必须带 `trigger_evidence`；给了 `--previous` 时额外输出**标签漂移**（changed/added/removed）。该入口只校验一致性，不推导标签、也不改写任何机器门禁状态。
- 主动研究四个阶段（`alpha-validate`/`alpha-scan`/`portfolio-construct`/`rebalance-proposal`）新增 `--output <file>` 与 `--force`：路由器把该阶段已解析的 `result` 写成文件（临时文件 + `fsync` + 原子替换，并回读校验 SHA-256），**仅当阶段 `status=complete`** 才写；非 complete 时在 `route.result_skipped_reason` 给出原因；目标路径与任何输入同文件时拒绝写入。
- 政策分母：当已确认策略把现金排除在分母外（80/20 非现金口径）时，`inverse_volatility_policy` 可声明 `denominator: active_non_cash_market_value` 与 `excluded_policy_symbols`（每条带非空原因）；此时 `bucket_targets` 只对非现金范围求和为 1.0、桶成员只需覆盖全部活动非现金标的，`rebalance_weights.py --policy-file` 会回声 `denominator`/`excluded_policy_symbols`/`scope_symbols`。未声明时保持旧契约（每个活动标的恰好一次 + 现金桶唯一头寸）。

已有路径的可读性收紧：`rebalance_weights.py --filepath` 现同时接受 `--positions-file`（同一参数，`--quotes-file` 仍是 daily_sync 报告）；`yf.py` 历史抑制说明直接给出修复参数（`--market` 与 `--asset-type` 或 `--with-portfolio`；ETF 需 `--history-integrity-file`）。

### 复核泳道、节假日日历与报价时效

- `pia.py risk-diagnostic --weights-file <weights.json> --history <SYMBOL=file.json> … [--fx-history <PAIR=file.json> …] [--base-currency <CCY>] [--out <file>]`：**带覆盖声明的部分风险诊断**。读取 `rebalance_weights.py` 的权重（含市值与现金行）与逐标的 `yf.py --price-only --json` 历史，计算年化波动（日简单收益样本标准差 × √252）、共同观测期相关矩阵、以及**在已覆盖子集内重新归一化**的权重与分量风险贡献；输出逐标的排除原因（`no_history_supplied` / `unusable_history` / `cash_excluded_from_risk_diagnostic`）、覆盖非现金市值占比与固定声明（`limited_diagnostic` / `not_risk_parity` / `not_portfolio_risk_contribution` / `coverage_declared`）。可用历史少于 2 个、共同观测不足 31 天或历史文件缺失时失败关闭，并把逐标的排除原因一并返回。该结果**只覆盖所提供的标的**，不得当作组合风险贡献；`pia.py report` 会把它渲染为「风险诊断（部分覆盖）」一节。 现金不再只以"被排除"出现（**现金方案 B**）：本币现金标注为 `base_currency_cash_carries_no_fx_risk` 并给出 `base_currency_cash_excluded_from_equity_risk`；外币现金在提供对应 `--fx-history PAIR=file`（如 `USDCNY`，取自 `yf.py --price-only CNY=X`）时按**同一观测窗口**独立建模为汇率腿（组合占比、汇率年化波动、独立加权波动），否则记为 `cash_fx_exposure_unmeasured:<PAIR>`；`value_coverage` 把组合市值切成"已测量权益 + 未测量权益（列出标的）+ 已建模汇率现金 + 本币现金 + 未测量现金"，`partition_total` 必须为 1，因此剩余的未测量部分不会被误读成无风险；`cash_fx_risk.measured_legs_combination` 只合并**已测量**的两条腿，给出零相关点估计与相关系数 [−1, 1] 区间上下界，并声明未测量权益不在界内。
- `pia.py review-pack --lane <泳道> --run-dir <dir> [--out <brief.md>] [--lanes-file …]`：按 `references/review_lanes.json` 生成**独立复核简报**，声明该泳道所需工具（如 `web_search`）、禁止事项、必答问题与输出契约，并对运行目录下要求存在的制品逐一算出 SHA-256；**任一必需制品缺失则不交付简报**（返回 `required_inputs_missing` 并列出缺口），避免泳道在缺料情况下“空转”出结论（历史事故：三个泳道因 `MISSING_WEB_TOOLS` 停摆且未产出可用证据）。
- `pia.py calendar {build,closed}`：节假日日历。`build --cn-html … --us-html … --cn-locator … --us-locator … --retrieved-at … --out …` **按来源分别解析**（CN 国办发明电通知 / NYSE 节假日表），逐来源带定位符与内容 SHA-256，并内置完整性断言（CN 必须解析出 7 组假期且每组展开天数等于其声明的“共N天”；US 必须看到全部 10 行标签且每年至少 9 个休市日）；断言不过即拒写表。`closed --market CN --start … --end …` 统计区间内的休市日。
- 报价时效的节假日放宽是**显式选择**：`yf.py --holiday-calendar-file <table>`（`pia.py daily-run` 同名参数透传）。当前 US 可在 CLOSED 状态下按 NYSE 休市日放宽上限（最多 10 天）。对 `.SS` 且报价交易所为 SHH/SHG，或 `.SZ` 且报价交易所为 SHZ/SZSE 的标的，可显式传入 `references/market_holidays_sse_szse_2026.json`。它分别从上交所、深交所 2026 年官方公告全件（`references/official_sources/sse_2026_holidays.html`、`szse_2026_holidays.html`；URL/hash 见表）解析，并与原 CN 国务院假日表逐日比对；载入表时还会重读技能目录下命名为 `official_sources/sse_2026_holidays.html`、`szse_2026_holidays.html` 的原件，重新核验哈希及逐日日期；原件缺失、被改写或与表不一致即拒用。只有**该标的对应的交易所来源**闭合且自报价日至评估日之间每天均休市才放宽；一旦出现开市日，即使前面跨过长假也不得延用旧报价。只含上交所来源的 `market_holidays_sse_2026.json` 仍可用于 `.SS`，对 `.SZ` 不生效；仅传 `market_holidays.json`、北交所及其他年份均不放宽，返回来源缺口。表只涵盖公告中的例行休市，不证明临时停市、盘中可交易状态和特殊品种日历。复建使用 `market_calendar.py augment-cn-exchange --table <原表> --exchange SSE|SZSE --exchange-html <已获授权的完整官方原件> --exchange-locator <官方 URL> --retrieved-at <实际取证时刻> --out <新表路径>`；不得覆盖旧表。

## 直接门禁与分析命令

- A 股公告事实／更正链：`cn_filing_facts.py <package.json> --verify-raw`，仅在逐个原件路径已获授权时启用原件重验；结构通过不证明摘录语义。
- A 股非金融经营 DCF：`cn_valuation_drivers.py <model.json> <dashboard.json>` 复算 Stock 3.0 EV；需要把收入锚点与公告事实绑定时，显式追加 `--filing-package <facts.json> --verify-filing-raw`（读取包内指定原件）。`source_anchor_status` 区分自报与原件绑定；原 Dashboard 双门另跑。
- A 股行动级条款可行性：`cn_actionability_gate.py <assessment.json> [--holiday-calendar-file <官方交易所休市表>]`；闭市日可只给标的身份，返回 `market_closed/not_actionable`；开市日仍需核对当日规则、行情和资源。不发单，规则原件仍需人工核验。统一入口为 `pia.py actionability-gate --assessment <assessment.json> [--holiday-calendar-file <表>]`：`complete` → exit 0（并附 `human_review_required_no_order` 声明），`market_closed` 与 `insufficient_evidence` → `insufficient_evidence`/exit 2（"当前不可执行"≠"条款可行"），未知原生状态 → `failed`/exit 3。
- 个人风险预算：`personal_risk_budget.py <完整 v2 情景报告> <用户确认预算>`，仅比较已给场景的成本后损失、单标的及现金比例，不推断个人承受能力。
- 证券身份：`instrument_gate.py`
- 美股实时证据：`live_evidence_probe.py`
- 美股免费点时年度财务：`pia.py edgar-fundamentals <代码...> --as-of <ISO 日期> [--user-agent <含真实邮箱的说明>]`；底层为 `sec_edgar_fundamentals.py`，只选取 `filed <= as_of` 的 SEC `companyfacts` 事实，不获取价格
- 研究 Brief：`research_brief_gate.py`
- 财务筛选：`quality_screener.py`
- 通用行情与财务：`yf.py`
- 即期外汇：`yf.py CNY=X --price-only --period 5d --lean --json --cache-dir <task-cache>`；使用带日期的外汇序列，并从最后一个有效观测构造 USD/CNY 快照
- A 股补充数据：`akshare_fetcher.py`
- ETF 历史完整性：`history_integrity_gate.py`
- ETF packet 事件推导、装配与覆盖探测：`pia_etf_packet.py {derive-provider-events,derive-official-events,assemble,coverage-probe}`。`coverage-probe --channel {cninfo,nasdaq} --target <符号> --control <另一符号> --target-class stock|etf --control-class stock|etf --channel-scope "…" --as-of-date … --task-dir …` 用**同类对照**证明通道是否覆盖某类标的：`covered_zero_events`（同类对照 >0 且目标 =0，零才算“无事件”）、`covered_with_events`、`coverage_unproven`（对照为 0 或弱对照）、`channel_unavailable`（传输/解析失败，或 cninfo 经一次重试仍为 165 B 空壳）；只有 `covered_*` 才输出可用 `official_coverage` 块。`assemble` 默认要求官方与提供方事件**逐位相等**；可显式启用容差：`--factor-tolerance <正数> --tolerance-basis relative|absolute --tolerance-justification "…" --tolerance-source <定位符>`，四项缺一即失败关闭；`event_type` 与 `effective_date` 永不容差；命中容差的对写入回执 `event_mismatches.within_tolerance` 并置 `tolerance_used=true`。`derive-provider-events --symbol QQQ --as-of-date … --task-dir … [--window-days 400] [--amount-decimals 3]` 从提供方自己的分红/拆股序列推导 `provider_events`（并落盘带哈希的原始捕获）；`derive-official-events --feed-file <交换行情分红 JSON> …` 从交易所/市场数据源推导 `official_events`；两者均按 `as_of_date` 与窗口过滤、按日期排序。**精度约定**：因子值量化到提供方公布精度（默认 3 位小数，`--amount-decimals`），否则交易所 5 位金额与提供方 3 位金额会逐行不匹配；原始金额保在捕获件中。**独立性声明**：提供方与交易所馈送可能同源，匹配只证明提供方一致，不证明分红本身正确。首次实操结果：QQQ 的 5 条窗口内分红两边完全一致 → `packet_verified=true` → `yf.py --history-integrity-file` 绑定后 `series_bound_verified`、`technical_metrics_allowed=true`、取回 251 行日线（原先 ETF 历史全被抑制）。
- 管理层承诺：`management_claim_tracker.py`
- Dashboard 结构与数学：`dashboard_gate.py`、`dashboard_math_gate.py`
- Dashboard 目录：`dashboard_catalog.py`
- 观察边界：`watchlist_gate.py`（`--derived-limits <position_limits.json>` 可并入政策派生限制；派生类只从该显式文件读取）
- 政策派生限制：`position_limits.py --weights-file <weights.json> --positions-file <portfolio.json> --policy-file <risk_bounds_policy.json> --out <position_limits.json>`（从用户确认政策与本次组合规模自动推算上下限，不逐笔手填）
- 组合情景：`portfolio_scenario_analyzer.py`
- 分配实验：`rebalance_weights.py`
- Alpha 推广门禁：`pia.py alpha-validate <alpha-package> --policy-file <promotion-policy>`
- 主动机会扫描：`pia.py alpha-scan <alpha-package> --validation-report <validation-report> --policy-file <scan-policy>`
- 风险平价与稳健主动候选：`pia.py portfolio-construct <scan-report> --policy-file <construction-policy>`
- 非执行再平衡研究提案：`pia.py rebalance-proposal <construction-report> --policy-file <proposal-policy>`；原生输出仍为研究候选。advisory 可在适用门禁闭合后另行给出供用户手动执行的价格、数量或目标仓位指令，不能只改标签就称就绪，不回写实际持仓。
- 券商 CSV 导入：`broker_sync.py`，仅在用户另行明确授权的真实持仓数据维护任务中运行；不属于 advisory 参数建议的副作用或执行步骤
- Daily Sync：`yf.py --daily-sync --cache-dir <task-cache> [--daily-sync-workers 1..4]` 后接 `daily_sync.py`；采集端使用 `--holiday-calendar-file` 时，离线重放与 `pia.py daily-sync` 必须显式传入同一参数，`pia.py daily-run` 会透传给两个阶段。完成事件红队时再传入 `--thesis-evidence-file`
- 备用行情来源：`yf.py --daily-sync` **默认**在主源传输失败（`error`/`skipped_circuit_open`）后尝试已标注的备用源（CN/US，`quote_fallback.py`），`--no-fallback-source` 关闭。主源已回答（`ok`/`no_data`）的标的**绝不**替换；成功记录带 `quote_provenance`（`tier=secondary`、`source_locator=fallback:tencent:<symbol>`、`unverifiable`），`provider_receipt.fallback` 逐笔记录 `attempted`/`used`/`outcomes`/`coverage_tier`。重放端要求 `data_sources` 与 `quote_provenance` 指向同一来源，否则以 `identity_mismatch` 失败关闭；通过时计入 `secondary_quote_symbols` 与阶段警告但不算主源匹配，报告新增“备用行情来源（主源失败后替代）”章节
- 一手证据采集：`pia.py collect-evidence --task-dir <task> --symbols <symbol...> --window-start <iso> --window-end <iso> [--scope-source <macro|sector|regulatory>=<url>@<published_at>]...`；产出 `evidence/evidence_items.json`（可直接用 `pia.py build thesis-pack --evidence-file` 消费）与 `out/evidence_channel_report.json`。通道故障与空结果分开：`broken` 一律置 `incomplete`（退出码 1）、只对 `broken` 做有界重试，宏观／行业／监管时间戳必须由调用方声明
- 研究日记与结果同步：`advice_journal.py`、`sync_outcomes.py`、`decision_outcome_report.py`
- Dashboard 保存／更新：`save_dashboard.py`，当前明确授权已覆盖持久化时直接运行（含 `advisory` 本地维护），不重复索要批准；具体写入边界见 SKILL.md

需要精确参数时以对应 `--help` 为准；文档中的示例不得覆盖脚本当前契约。

`yf.py` 的所有联网模式都必须先绑定可写 SQLite 缓存。显式 `--cache-dir` 优先，其次使用 `PIA_YFINANCE_CACHE_DIR`，否则落到当前工作目录的 `tmp/pia-yfinance-cache`。缓存目录即使已经存在也要通过实际写入探针；权限、只读文件系统或 SQLite 打开失败属于永久本地错误，同参数不得退避重试。

`scenario --output` 不得解析为组合或假设输入文件；`calibrate --output-path` 不得解析为研究日记。所有整文件写出路径（情景结果、校准报告、券商快照、管理层承诺跟踪和研究日记结果更新）均使用唯一的同目录临时文件、`fsync` 与原子替换，冲突或写出失败时保留原文件。研究日记的追加和读改写还使用跨进程独占锁；锁等待超过 5 秒时失败关闭，不覆盖其他写入者的结果。

## Dashboard 7.2 验收补充

原有 Brief、Dashboard `--strict-current-contract`、数学门和保存 CLI 不变；新语义由显式版本选择。新建/发布前还须在调用方脚本显式调用 `source_timing_contract.verify_source_capture`，对获授权的真实 raw 文件重算完整 SHA 并匹配候选的 source_capture_receipt；参见 company-research 的回执契约。此 helper 无联网、扫描、自动归档或全局路径参数。结构门只核验回执链，不能把自报回执称为已外部核验；保留原件/取证日志供独立审计，旧档加载不自动打开定位符。
