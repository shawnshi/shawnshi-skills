# Garmin Connect 实时访问参考（非官方）

本资料用于显式调用技能后的受控实时读取，以及另行授权的认证或同步。显式调用本技能即授权读取请求窗口内相关健康指标，并在本地明确 `no_data` 时对同一窗口和组件执行一次实时只读回退；未给窗口时默认最近 7 天。技能通过固定版本 `garminconnect==0.3.9` 访问 Garmin Connect 的非公开 Web 接口；该接口可能变化、限流或与 Garmin 使用条款存在冲突。生产集成应优先评估 Garmin Health API 的正式合作路径。

## 授权边界

- `--allow-network` 只允许本次命令联网，不允许读取任意健康数据；CLI 门禁必须保留。
- 技能根据显式调用自动附加 `--allow-health-data`；仅在本地明确 `no_data` 且窗口与组件不变时，再依据同一次技能调用自动附加 `--allow-network`，消费一次实时只读回退能力。两个标志不得跨命令、跨日期或跨用途复用。
- 未指定日期时由技能显式传入默认最近 7 天，不能省略窗口让实时命令自行推断。技能的默认联网授权不包含直接跳过本地读取、认证状态探测、登录、令牌写入、同步、下载或持久化。
- `--allow-token-write` 只用于登录时创建或刷新持久令牌。
- `--allow-download` 只用于指定活动 ID、格式和隔离输出目录。
- `--allow-sync` 只用于执行已生成、未过期且绑定完全一致的 GarminDB 计划。
- 只有本地结果明确为 `no_data`、窗口与组件均已绑定且实时预检通过时，才可消费显式技能调用授予的一次实时只读能力，用 `--fallback-live` 自动切换。用户未缩小指标时，普通面板使用 `sleep,hrv,body_battery,heart_rate,stress`；`activities` 与 `training_load_series` 仍须用户明确请求。`partial`、数据库变化、Schema 错误或其他读取异常不得回退。

这些能力是进程内防误用控制，不是抵御同一进程恶意代码的安全沙箱。

## 当前解释器与可选隔离部署

普通运行不要求技能目录存在虚拟环境。将 `<SKILL_PYTHON>` 解析为本次选定解释器的 `sys.executable` 绝对路径，并用同一解释器运行预检和后续命令。本地路径先运行 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`；本页实时路径先运行 `--mode live`。只有返回 `RUNTIME_READY` 才继续，失败时不自动安装或切换解释器。

只有用户明确要求隔离部署时，才从技能根目录使用已审核的离线纯 Wheel 仓库：

```powershell
./install.ps1 -Offline -Wheelhouse <TRUSTED_WHEELHOUSE>
```

```bash
./install.sh --offline --wheelhouse <TRUSTED_WHEELHOUSE>
```

一步式在线安装已禁用。该工具是可选部署方式，不是普通运行前提。安装先在目标同级暂存目录构建，核对锁文件、平台/Python 标签、`wheelhouse-manifest.json`、每个 Wheel SHA-256、实际 pip 消费哈希和最终安装集合，全部通过才发布。pip 使用 `--isolated --no-index --require-hashes --only-binary=:all: --disable-pip-version-check`。清单仍不是发布者签名；需要来源认证时必须使用技能目录之外的签名和可信公钥。

## 认证

```bash
<SKILL_PYTHON> scripts/garmin_auth.py login --email <EMAIL> --allow-network --allow-token-write
<SKILL_PYTHON> scripts/garmin_auth.py status --allow-network
```

上游登录流程会使用移动 SSO，并可能读取账户 Profile/Settings。技能不再通过 `get_user_summary()` 读取当日健康数据来探测会话。状态检查从持久令牌的临时副本恢复，使令牌刷新不能改写原目录；这不替代 Windows ACL、磁盘加密或凭据管理器。

禁止在文档或分析代码中直接实例化 `Garmin(...)`、直接调用 `client.login()` 或绕过 CLI 签发能力。密码只允许交互输入或进程环境变量，不得出现在命令行、报告、日志和错误消息中。

## 精确范围实时读取

基础指标：

```bash
<SKILL_PYTHON> scripts/garmin_data.py sleep --source live --start 2026-08-08 --end 2026-08-08 --allow-network --allow-health-data
<SKILL_PYTHON> scripts/garmin_data.py hrv --source live --days 7 --allow-network --allow-health-data
```

扩展指标、时间点和活动文件命令见 `advanced_tools.md`。时间点查询要求无歧义的 IANA 本地时刻，容差限定为 0–3600 秒。`--period` 只接受正整数天数（如 `7d`）或 `YTD`，非法、零值和负值直接失败；`YTD` 包含 1 月 1 日与当前日。普通实时面板默认只读取 sleep、hrv、body_battery、heart_rate、stress，或用户指定的更窄子集；activities 与 training_load_series 需明确请求。stress 使用日度压力端点，不读取或返回步数。面板不读取 Profile、体成分、补水、Fitness Age 或设备闹钟。实时分析按用途缩小为：`baseline_change` 读取 sleep/hrv/heart_rate，`readiness` 读取 sleep/hrv/body_battery/stress，`audit` 与 `insight_cn` 读取 sleep/hrv/body_battery/heart_rate/stress，`env_stress` 只读取 activities；`long_term_load` 和 `device_audit` 不支持实时来源。所有实时报告和分析都必须使用显式窗口；本地 `no_data` 后的一次只读联网能力由显式技能调用默认授予，CLI 仍必须传入 `--allow-network` 与 `--allow-health-data`。

本地无数据后按相同窗口读取实时六类指标示例：

```bash
<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days 7 --source local --fallback-live --components sleep,hrv,body_battery,heart_rate,activities,stress --allow-network --allow-health-data --output <HTML_PATH>
```

命令先完成本地验证读取；只有结果状态为 `no_data` 才申请并消费实时能力。组件重复、未知、为空或未显式提供时，在客户端初始化前失败。

请求参数必须在客户端初始化前验证。能力对象仅保存请求的 SHA-256，不保留账户、指标窗口或输出路径明文；健康数据和下载能力在敏感动作前消费一次。

## 限流与失败

- 首次出现 HTTP 429 或 `Too Many Requests` 即停止；摘要组件按顺序读取，避免已有组件触发 429 后再启动后续组件；不得自动退避重试、并发扩散或切换备用接口。
- 认证、连接和 API 异常只输出稳定状态和异常类型，不回显邮箱、令牌路径、服务响应正文或原始异常消息。
- 缺数据应返回 `no_data`、`partial` 或 `no_observation`，不得补零或拿远处样本替代。
- 用户需要判断数据准确性时，应把同一日期的结果与 Garmin Connect 官方界面或合法导出文件核对，并把差异记为未解释。

## 有界 GarminDB 同步

同步是独立写操作。先生成计划：

```bash
<SKILL_PYTHON> scripts/sync_health_data.py sync --start 2026-08-01 --end 2026-08-07 --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json
```

核对后在有效期内执行：

```bash
<SKILL_PYTHON> scripts/sync_health_data.py sync --start 2026-08-01 --end 2026-08-07 --allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <SESSION_SCRATCH>/sync-plan.json
```

GarminDB runner 可使用显式指定的全局 Python 或虚拟环境，不要求独立虚拟目录。计划绑定窗口、配置、同目录令牌、解析后的绝对数据根、`DBs` 目录身份、解释器、相邻 CLI、可选 `pyvenv.cfg`、site-packages 文件树和固定包元数据。执行时配置与令牌只复制到自动删除的临时目录，并把临时配置改写为已绑定的绝对数据根，避免依赖继承的主目录变量。由于 GarminDB 把结束日作为开区间，临时配置把用户结束日加一天，以维持首尾包含的窗口。执行拆为精确窗口下载和 `--latest` 导入分析两个阶段；`--latest` 只用于离线导入本次新增文件，不用于下载。启动前会重新验证计划有效期、配置、令牌、数据根、临时副本和 runner，并用 `python -I -B`、移除 Python/pip/TLS 信任覆盖后的环境、关闭 stdin 的子进程运行。不得从 `PATH` 自动发现 CLI，不得使用备用 API；私有 CA 需要另建显式绑定路径、摘要与用途的受控流程。进程返回成功后还要核对目标数据库指纹和请求窗口覆盖。

SHA-256 只能发现与参考字节不一致，不能证明发布者身份，也不能抵御同一 Windows 用户下可同时修改技能和参考摘要的敌对进程。高对抗要求见 `external_acceptance.md`，必须引入独立账号、代码签名/执行策略或不可变运行环境。

## 真实链路验收

本地单元测试、Mock、dry-run、令牌文件存在或进程返回零均不代表真实链路通过。真实验收所需授权、最小证据和 FHIR 接收端分层门禁见 `external_acceptance.md`。未提供真实会话、精确日期、外部工具/包或接收端材料时，应明确记为 `not_requested` 或 `unavailable`。

## 参考来源

- `garminconnect` 上游仓库与发布说明：https://github.com/cyberjunky/python-garminconnect
- Garmin Connect 官方界面：https://connect.garmin.com
- Garmin Health API：https://developer.garmin.com/gc-developer-program/health-api/
