# Garmin 扩展工具与授权边界

只在用户请求扩展指标、时间点查询或活动文件时读取本资料。显式调用本技能即授权读取请求窗口内全部受支持健康指标，技能自动附加 `--allow-health-data`；所有实时路径仍访问非官方 Garmin Connect 接口，必须取得本次联网授权。本地只有 `no_data` 可按技能契约转实时，其他失败不得回退。

下列 `<SKILL_PYTHON>` 是本次选定解释器的 `sys.executable` 绝对路径，不要求位于虚拟目录。预检和后续命令必须使用同一解释器：普通本地分析先运行 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`；实时路径先运行 `--mode live`；活动文件解析先运行 `--mode activity`。预检失败时返回 `RUNTIME_DEPENDENCY_UNAVAILABLE`，不得自动安装或切换解释器。

同步还属于独立写操作：必须先用 `sync_health_data.py sync --start <START> --end <END> --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json` 生成短期计划，再以相同日期窗口、`--allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <PLAN>` 执行。显式 runner 可为全局 Python 或虚拟环境，不要求独立虚拟目录。计划缺失、过期、被修改，或窗口、配置、同目录令牌、解析后的绝对数据根、`DBs` 目录身份、解释器、相邻 CLI、环境文件树和固定包版本任一不一致时停止；配置与令牌只复制到自动删除的临时目录，临时配置必须指向已绑定的绝对数据根，并把结束日加一天以适配 GarminDB 的开区间。运行分为精确窗口下载和仅处理新增文件的 `--latest` 导入分析两个阶段；禁止给下载阶段添加 `--latest`。启动前再次复核计划与临时副本，并以 `python -I -B`、清理环境和关闭 stdin 运行。不得从全局 `PATH` 自动发现同步 CLI。进程成功后必须核对目标数据库指纹和请求窗口覆盖。文件树证据不是签名，也不能抵御同一用户下的敌对进程；高对抗运行需要 `external_acceptance.md` 所列外部信任根。

## 1. 扩展实时指标

先用 `--dry-run` 核对参数，再显式联网：

```bash
<SKILL_PYTHON> scripts/garmin_data_extended.py training_readiness --date 2026-08-08 --allow-network --allow-health-data
<SKILL_PYTHON> scripts/garmin_data_extended.py spo2 --date 2026-08-08 --allow-network --allow-health-data
<SKILL_PYTHON> scripts/garmin_data_extended.py respiration --date 2026-08-08 --allow-network --allow-health-data
```

这些字段是消费级设备值或厂商派生值，不用于诊断或训练资格判断。

## 2. 时间点查询

时间点查询是实时路径，必须显式提供日期、IANA 时区和 0–3600 秒最大允许偏差；没有默认容差。夏令时下不存在或有歧义的本地时刻必须失败。没有足够接近的观测时返回 `no_observation`，不得用远处样本代替。

```bash
<SKILL_PYTHON> scripts/garmin_query.py heart_rate "15:00" --date 2026-08-08 --timezone Asia/Shanghai --max-tolerance-seconds 300 --allow-network --allow-health-data
<SKILL_PYTHON> scripts/garmin_query.py stress "15:00" --date 2026-08-08 --timezone Asia/Shanghai --max-tolerance-seconds 300 --allow-network --allow-health-data
```

输出必须同时展示 `requested_at`、`observed_at`、`delta_seconds` 和时区。

## 3. 活动文件

- 默认多维健康画像会从本地 `garmin_activities.db` 读取不含位置、活动 ID、名称或描述的会话汇总字段；这不等于授权读取逐活动明细或原始活动文件。精确字段、稀疏事件流语义和解释边界见 `references/health_profile.md`。
- 下载 FIT、GPX 或 TCX 会访问 Garmin，并可能包含精确位置、时间和活动轨迹；默认健康数据读取授权不包含原始轨迹，仍必须分别取得联网和原始文件下载授权，并自动附加健康数据 CLI 标志。
- 下载时必须显式指定会话隔离输出目录，不得使用报告目录。
- 已存在的本地文件可离线解析、查询或汇总，不需要联网授权。
- 下载只要求实时模式通过；解析 FIT、GPX 或 TCX 前还要通过活动模式。下载后立即解析时两项都要通过。

```bash
<SKILL_PYTHON> scripts/garmin_activity_files.py download --activity-id 12345678 --format fit --output-dir <SESSION_SCRATCH> --allow-network --allow-health-data --allow-download
<SKILL_PYTHON> scripts/garmin_activity_files.py parse --file <SESSION_SCRATCH>/activity.fit
<SKILL_PYTHON> scripts/garmin_activity_files.py query --file <SESSION_SCRATCH>/activity.fit --distance 5000
<SKILL_PYTHON> scripts/garmin_activity_files.py analyze --file <SESSION_SCRATCH>/activity.fit
```

未经用户许可，不持久保存、外发或交给子代理处理轨迹坐标。

## 4. 报告与面板

```bash
<SKILL_PYTHON> scripts/report_output.py --days 7
<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days 7 --source local --allow-health-data --output <HTML_PATH>
<SKILL_PYTHON> scripts/garmin_health_profile.py --days 7 --source local --timezone Asia/Shanghai --allow-health-data
```

面板固定零外联并设置禁止网络的 CSP。报告和面板默认拒绝覆盖；需要替换时必须得到用户明确要求，再使用 `--allow-overwrite` 或 `--overwrite`。

多维画像的 IANA 时区必须来自用户或明确的运行环境并在结果中披露；不得根据睡眠日期反推时区。只有用户确认属于 18–64 岁成年人且要求公共卫生参考比较时，才附加 `--adult-18-64-guideline`。完整指标与解释边界见 `references/health_profile.md`。

## 5. 研究用途 FHIR R4 包装

`garmin_fhir_adapter.py` 只把显式本地 JSON 包装为 FHIR R4 `collection` Bundle。它不读取 Garmin、不联网、不上传服务器，也不使用 LOINC。当前只接受 `hrv_ms`、`resting_heart_rate_bpm` 和 `sleep_duration_seconds`；输入中的 `source_sha256` 是调用方声明的上游来源摘要，适配器会另行计算并写入本次输入 JSON 的真实 SHA-256。可选 `device_serial_hash` 必须是 64 位小写十六进制摘要，不能传入原始设备序列号。Bundle 带 Provenance，输出不含临床解释或参考区间。

```bash
<SKILL_PYTHON> scripts/garmin_fhir_adapter.py status
<SKILL_PYTHON> scripts/garmin_fhir_adapter.py export --input <LOCAL_JSON> --output <FHIR_JSON> --acknowledge-research-only
```

默认拒绝覆盖。该输出只适合个人数据可携带或研究准备，不代表任何临床实施指南、机构 Profile、术语等价性或接收系统兼容性。

`status` 与导出回执中的 R4 结构、Profile/IG、术语、接收端四道外部门禁默认均为 `not_performed`。外部 Schema/Validator、Profile/IG、术语或接收端材料不能由本地包装成功推断。用户提供哈希绑定的验证材料后，可离线复核：

```bash
<SKILL_PYTHON> scripts/fhir_external_acceptance.py --bundle <FHIR_JSON> --evidence <EVIDENCE_JSON> --output <ACCEPTANCE_JSON>
```

该复核不会运行验证器、联网、验证独立签名或发送 Bundle，只盘点“调用方材料与调用方摘要是否一致”。调用方声明的 `passed` 一律降为 `indeterminate`；回执固定保留 `ok=false`、`external_acceptance_established=false` 和 `clinical_interoperability=false`。材料格式和接收端限制见 `references/external_acceptance.md`。
