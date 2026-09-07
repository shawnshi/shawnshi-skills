# 私人数据读取合同

根入口选择私人数据读取分支后、任何私人读取前完整读取本文件，并先通过根入口启动门；保存分支也可按根入口指引仅查阅能量模板，不因此获取采集授权。纯当次用户文本草稿不加载本合同、不采集数据。限定默认授权不覆盖用户明确排除的数据源；日记历史只读请求所需目标日期块，不扩展扫描。读取授权不是日记保存授权；只读/不保存请求不生成写入回执。

## 限定读取授权与禁止事项

- 草稿、预览、只读、不保存、不同步、不联网或仅用本地数据请求，不触发本合同的新鲜度同步；使用当前请求已授权的本地证据并披露缺口，不为恢复同步要求用户再次授权。不联网或仅用本地数据时也不得走云端实时回退。此退出条件优先于下文所有同步规则，读取门仍然适用。
- 进入私人数据读取分支生成个人日记时，即默认授权只读获取日记日期及次日日历的最小事件字段，以及最近 3 天 Garmin 健康摘要；不再为这两类限定读取重复询问授权。仅在未命中上述同步退出条件、窗口含当前自然日且必需组件末端陈旧时，还授权直接运行一次两阶段同步（`sync_health_data.py sync --dry-run` 后 `--allow-network --allow-sync`），不再启动 `Codex-Garmin-Health-Sync` 计划任务。权限不足或授权失败不得同步，也不授权注册或修复任务。
- Garmin 必须本地优先，并先通过 canonical `personal-health-analysis` 权威门。未命中同步退出条件且末端陈旧时直接运行两阶段同步一次并重读本地；同步失败保留同步前证据，不重试、不改走实时接口。仅当本次未尝试新鲜度同步且本地明确返回 `no_data` 时，才可使用已有有效凭证对同一 3 天窗口执行一次云端只读查询；`partial` 继续使用本地数据并披露缺口，依赖、Schema、完整性或其他读取错误不得触发云端回退。
- 云端返回 `authentication_required` 时立即停止健康数据读取并披露缺口；Garmin 登录、令牌修复或刷新必须由用户另行明确授权。
- 默认读取授权不包含 Google Workspace 登录、OAuth 客户端或令牌创建/刷新、凭据导出，亦不包含 Garmin 登录、令牌创建或刷新写入、绕过新鲜度门的本地数据库同步、同步任务注册/更新、原始活动文件下载、账户资料、设备闹钟、日历写操作或任何第二处持久化；仅允许一次 canonical 两阶段直同步。
- 日历只能证明安排，不能单独证明实际参加或任务完成。健康指标只作描述性背景，不生成未经验证的能力分数、医学判断、确定因果或强制日程干预。
- 日记中的能量字段必须把机器侧缺失哨兵投影为可读的“状态、原因、仍可观察事实和判断边界”；`采集审计` 必须披露同步资格、是否启动/等待、任务终态、本地重读结果、实时回退是否使用及稳定原因码；`执行带宽` 固定使用 `not_scored` 并解释边界，来源未提供睡眠负债时写 `sleep_debt_h=null` 与 `sleep_debt_status=not_provided_by_source`。不得只写空值或 `[DATA_UNAVAILABLE]`。
- Mentat 日志不自动读取日历或 Garmin；只有个人日记生成流程继承上述限定默认授权。

## 日历与 Garmin 限定读取

1. 个人日记可只读获取日记日期及次日日历的最小字段，以及最近 3 天 Garmin 健康摘要。日历读取顺序固定如下，不得跳步或静默切换数据源：
   1. 先运行 `gws auth status`。只有命令成功、`auth_method=oauth2`、`token_valid=true`，且授权范围包含 Google Calendar 时，才进入查询；只记录资格状态和稳定原因码，不复制用户标识、客户端标识、令牌或凭据路径。
   2. 再分别运行 `gws calendar +agenda --today --timezone Asia/Shanghai --format json` 与 `gws calendar +agenda --tomorrow --timezone Asia/Shanghai --format json`。查询结果只投影日期/起止时间、摘要和日历名称；位置、参与人、描述及其他字段仅在用户当前请求明确需要时读取。
   3. `gws` 不存在、权限检查失败、Calendar scope 缺失、认证失效或查询失败时，立即报告日历证据缺口与稳定原因码；不得自动登录、刷新或修改凭据。
   4. 禁止自动改用 Outlook COM、Microsoft Graph、Windows 日历或其他日历源。只有用户在当前请求中明确指定并授权其他来源时，才可改用该来源。
2. Garmin 先通过 canonical `personal-health-analysis` 的 `runtime-authority.json` 门，再执行本地读取命令中的 `--source local --allow-health-data`。返回 `partial` 时保留已有证据并披露缺口；返回 `no_data` 时不得伪造观测。
3. Current-date freshness gate：只有未命中上述同步退出条件、窗口含当前日且必需组件末端陈旧时，允许一次 `sync_health_data.py sync --dry-run`，通过后再执行一次带 `--allow-network --allow-sync --allow-health-data` 的同步并本地重读；without retry。同步失败后不得改走实时接口。
4. 仅当本次没有尝试同步、本地明确为 `no_data`、用户已授权联网且 `runtime_preflight.py --mode live` 通过时，才允许一次同窗口 `--source live --allow-network --allow-health-data`。`authentication_required`、`RUNTIME_CONTRACT_MISMATCH`、Schema 或完整性错误立即失败关闭。
5. 不注册、更新或修复计划任务，不调用 `Codex-Garmin-Health-Sync`，不执行 Garmin 登录、令牌写入或原始活动下载。

## 能量管理（描述性生理背景）

只有实际读取健康摘要时才填充本节健康字段；没有健康读取需求时不得为填模板强行采集。完整八章日记仍保留能量章节并注明未读取及判断边界。生成后运行适用的 `audit_gate.py --enforce-template-fields`。

- **数据范围与来源**：记录请求窗口、实际观测窗口、来源和读写边界。
- **组件覆盖与新鲜度**：分别说明 sleep、hrv、body_battery、heart_rate、stress 的末端日期。
- **采集审计**：`sync_eligible=<true|false>; sync_attempted=<started|waited_existing|direct|not_attempted>; task_status=<success|failed|timeout|invalid|start_failed|interrupted_or_terminated|not_checked>; local_reread=<accepted|rejected|not_run>; local_status=<complete|partial|no_data|read_error|not_run>; live_fallback=<used|not_used>; reason=<稳定原因码>`
- **睡眠观察**：只记录来源实际提供的数值、状态和日期。
- **HRV 与静息心率观察**：保持描述性，不生成诊断。
- **Body Battery 与压力观察**：不把共享上游信号重复合成为总分。
- **执行带宽**：固定为 `not_scored`，不得出现 score、value、level 或 color。
- **睡眠负债**：来源未提供时使用 `sleep_debt_h=null; sleep_debt_status=not_provided_by_source; method=none; baseline_h=null; window_days=null`。
- **摩擦解构**：分开记录任务负荷、主观感受、生理观察和外部约束。
- **交叉归因**：说明日期是否同期，并保留替代解释。
- **干预指令**：仅给出触发条件、最小动作和完成标准，不自动调整会议、训练或重要事项。
- **数据缺口与不可判断事项**：明确缺失组件、日期和判断边界。
