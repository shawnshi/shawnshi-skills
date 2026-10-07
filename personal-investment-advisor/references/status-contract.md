# 状态与失败关闭契约

## 顶层工作流状态

- `complete`：本次声明范围内的必需门禁、证据与计算均闭合。
- `incomplete`：流程已运行，但至少一个必需阶段未完成；Daily Sync 的 Thesis 未评估属于此状态。
- `insufficient_evidence`：输入可解析，但证据不足以支持声明。
- `failed`：输入、身份、计算或运行发生硬失败。

脚本可保留业务 `detail_status`，但不得用自然语言 `unknown`、`data_gap` 或历史上的 `ok` 模糊顶层闭合度。兼容读取旧归档时必须显式标出兼容模式，不能把旧状态升级为当前完成。

公开状态必须同时聚合顶层 `status`、所有 `stages[].status` 与逐层 `exit_code`、`completeness.complete`、`valid`，不能因为顶层已经是非完成状态就跳过子阶段。严重度固定为 `failed` 高于 `insufficient_evidence`，后者高于 `incomplete`，最后才是 `complete`；任一层出现 `invalid`、`failed` 或 `valid=false`，最终状态均为 `failed`。

`stages` 若存在必须是列表（空列表表示未声明子阶段），每项必须是含已知 `status` 的对象；逐层递归聚合该对象的 `valid`、`errors`、`completeness` 和子阶段。缺失或未知状态、畸形阶段、超过 64 层的嵌套均失败关闭。`errors` 非空与当前层完成状态矛盾时判定失败；独立未完成工作中的缺口说明不自动升级为执行失败。

子进程负退出码或退出码大于等于 3 是硬失败，优先于证据不足，包括筛选路由。筛选的业务 `pass`/`fail` 在退出码为 0 时都表示描述性筛选完成，而非执行失败；未知或畸形筛选项仍失败关闭。普通子进程退出码 1 不能伴随完成状态；退出码 2 不能伴随完成或未完成状态。证据不足可保留其独立状态，不掩盖硬退出失败。

## 运行清单（run inventory）

`daily-run` 的 `out/daily_run_summary.json` 必须自带运行清单，且**每一条中止路径都要带**，否则早期中止的运行会看不出自己少了什么：

- `run_inventory.decision_scope` 与 `stage_scopes`：本轮范围，以及每个已运行阶段的范围内。
- `run_inventory.requested_stages` / `stages_run` / `stages_not_run`：未运行阶段必须带原因（`skipped_by_flag:<flag>` 或 `not_reached_due_to_upstream_incomplete`），不得留空位或省略字段让读者误以为“该类结果为空”。调用方显式关掉的阶段也需出现在 `stages_not_run`，尽管它不会进入 `requested_stages`。
- `run_inventory.valid_until`：取最短报价窗口的**保守下界**（`valid_until_basis=conservative_shortest_quote_window`），同时给出 `freshness.window_seconds_by_market_state` 与 `latest_valid_until`。窗口来自 `quote_evidence_contract`，不得手写常量；只读 `valid_until` 的调用方按失败关闭方向取值。
困难等级固定为三层，不可自下而上降级：机器前置条件（可从 run 制品判定）、人工门（账户规则与成本模型，恒为 pending）、以及结构性未知（恒存 `account_rules_not_verified` / `cost_model_not_sourced`）。`daily-run --actionability-assessment` 的一步式组合沿用同一契约：gate 原生 `market_closed`/`insufficient_evidence` 映射为 `insufficient_evidence`（exit 2），`invalid_input` 与未识别原生状态映射为 `failed`（exit 3）；不得把“当前不可执行”写成“本轮失败”，也不得把未识别状态默认为 `complete`。
- `status_consistency`：顶层状态与阶段推导状态（`status_from_stages`）的对照。顶层可以比阶段更严（例如显式 `insufficient_evidence`），但不得比任何失败阶段更软；`consistent=false` 即契约冲突，调用方须失败关闭。
- `residual_unknowns`：**本轮未建立的东西**，逐条带 `kind` / `stage` / `detail` / `statement`。来源：未完成阶段、阶段错误、未证明的覆盖探针、观察阀值未定义的标的、以及“本轮整体未完成”（`run_not_complete`）。两项结构性未知恒存在：`account_rules_not_verified`（不连券商，规则、可卖数量、当日限额未核验）与 `cost_model_not_sourced`（佣金/价差/冲击/卖出税只在 actionability gate 显式提供时才参与计算）。行情与全部阶段都 `complete` **不等于**已建立可交易结论；`residual_unknowns` 缺字段或为空列表均按缺口处理，不得读作“零未知”。
- 就绪汇总（`pia.py readiness`，只读）：`ready_for_human_review` = 全部**机器可核验**前置条件成立且人工门已具名（仍非下单授权）；`not_ready` = 至少一项机器前置条件未核验/未提供，或本轮未完成、范围未声明/冲突、`residual_unknowns` 未声明；`failed` = 输入缺失、范围冲突或无法识别的原生状态。人工门（`HUMAN_GATE_PREREQUISITES`，目前为账户规则与成本模型）不得计入机器前置条件的“已核验”，也不得因此把 run 读作“零未知”。
- `previous_run` 与 `out/run_replay_history.jsonl`：同一 `--task-dir` 就地重跑时，被替换的上一轮 run 必须留下可查身份（`summary_sha256` / `generated_at` / `status` / `detail_status`）。重跑会覆盖本目录的 summary/weights/daily_sync，因此这一记录在**动任何文件之前**捕获，且中止路径同样落盘；单次调用只 append 一行（重写 summary 不再加行）。首轮无 `previous_run`，也不创建该文件。要保留上一轮结论应拷到新目录，而不是依赖重跑。
- 跨运行差分（`pia.py history diff`）：三个比较段（`weights`/`boundaries`/`quotes`）各为 `computed` / `not_requested` / `not_comparable`，且**不可比较时必须为 `null`**（空集合会被读成“无变化”）。缺口分两级：`gaps`（阻塞，退出码 2、`diff_partial`）与 `warnings`（非阻塞，`complete_with_warnings` / `diff_computed_with_warnings`、退出码 0）；仅当缺失侧在 `run_inventory.stages_not_run` 里自己声明了原因时，`boundaries`/`quotes` 的缺失才可降为 `warnings`，`weights` 永不软化，未声明的缺失一律阻塞。`--strict` 关闭降级；`--sections` 限定哪些段可以阻塞（未请求即 `not_requested`）；全部被请求段都不可比较时为 `nothing_comparable`（退出码 2，不得读作干净的零差分）。路由层把 `complete_with_warnings` 映射为 `complete` 但保留 `result.warnings`，避免软化被读成无保留结论。`run_inventory` 是这套降级的唯一证据来源：旧 run 无此声明，其缺失仍按阻塞处理。

每个 `stages[]` 项也携带自身 `decision_scope`，因此报告不再需要猜测本轮范围，也不得自行声明范围。

## 结论强度

`unknown` 可用于自然语言说明未知结论，`not_applicable` 可用于不适用的方法项，二者都不能代替顶层工作流状态。缺失、冲突、陈旧或无法定位到原始来源的数据不得用零值、默认通过或模拟结果替代。

## 退出码

稳定 CLI 的退出码映射由 `scripts/status_contract.py` 统一提供。只有 `complete` 返回成功；`incomplete`、`insufficient_evidence` 与 `failed` 均返回非零，并保留结构化状态与原因，供调用方区分重试、补证和硬失败。
