# 同步执行合同

## 导航

- [授权与只读请求](#授权与只读请求)
- [日期范围与执行计划](#日期范围与执行计划)
- [时间预算与兼容性](#时间预算与兼容性)

## 授权与只读请求

源码固定哈希门禁已移除。旧 `--authority-config` 参数仅为兼容旧调用而接受，不读取该配置，也不报告哈希通过。`freshness_task_gate.py` 检查已有计划任务时，仍须由调用方提供已批准的 `--expected-arguments-sha256`；没有该指纹则停止，不从实际任务反向信任自身参数。其来源是用户授权注册时 `install_auto_sync_task.ps1` 返回的 `arguments_sha256` 回执字段；调用方保留该批准时点的值，不能以重新查询未经核验的现有任务来补齐。直接同步仍核对 canonical runner 路径、显式能力、日期、单例锁、预检、短期计划、数据库变化与末端覆盖。本次移除不注册、更新或启动任何现有计划任务。

- 用户明确要求启用 Garmin 自动同步时，该请求授权注册或更新一个当前用户、最低权限的计划任务。用户明确启用后，已注册的计划任务会按日自动同步到绑定的 GarminDB 本地数据库，并自动更新单一脱敏运行状态文件；该持续授权仅来自这次明确启用请求。任务动作仍必须显式携带 `--allow-network`、`--allow-sync` 与 `--allow-health-data`，不得把授权扩展到登录、令牌写入、活动轨迹下载、账户设置、代理、证书或其他存储。如果用户要求仅诊断、预览、不保存、试运行、不同步、禁用或移除自动同步，则保持只读，不注册或运行任务，也不写入数据库或状态文件。
- 日期窗口同步只支持监测、睡眠、静息心率、HRV 和体重。上游活动按最近 N 个而非日期选取，不能兑现精确日期范围；`--allow-download` 因此返回 `activity_date_window_unsupported`，预览与直接 API 调用也在读配置、定位令牌或联网前拒绝。计划只接受 `network,sync` 两个门，含旧活动门的计划必须重新生成。需要活动文件时，沿 `advanced_tools.md` 中独立的活动 ID 下载合同另行取得授权，不能把日期同步授权扩大为不限日期的活动下载。

## 日期范围与执行计划

1. 只有用户明确要求同步后，才执行两阶段同步：先运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json` 生成短期计划；核对范围和绑定摘要后，再在计划有效期内运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <SESSION_SCRATCH>/sync-plan.json`。GarminDB runner 可使用显式指定的全局 Python 或虚拟环境，不要求独立虚拟目录；必须在解释器相邻安装中定位 CLI，并核对固定版本 `garmindb==3.9.0` 与 `garminconnect==0.3.17`。计划同时绑定配置、同目录令牌、解析后的绝对数据根及 `DBs` 目录身份；执行时只把配置与令牌复制到自动删除的临时目录，并把临时配置改写为已绑定的绝对数据根。GarminDB 的配置结束日为开区间，临时配置把用户结束日加一天；3.9.0 CLI 还会用不含当天的天数截断，因此 `sync_health_data.py` 内置有界子进程适配，仅对固定 AST 摘要匹配的 `__get_date_and_days` 非 latest 分支修正当天计数，并核对返回范围与请求完全一致。日期不得在未来，不改变系统时钟或上游安装。v4 短期计划包含适配器所属源文件身份/哈希绑定，旧计划必须重新生成；子进程在执行任何上游代码前核对 CLI 原始字节哈希、方法形状、临时配置摘要、精确窗口与过期时间，失败即停止；运行分成 `download`（精确窗口下载）和 `import`（仅导入本次新增文件）两个子阶段，禁止全历史重复导入。日常补同步不携带 `--analyze`：GarminDB 的 `Analyze.summary()` 会遍历所有存储年份，不受本次窗口限制，不能混入限时补数。回执明确标记 `summary_analysis=not_requested`；既有派生汇总不会被重新计算，不承诺其已更新。需要全历史汇总时另开受控、分批的显式任务，不能直接绕过 canonical 能力与生命周期门。启动前要重新核对计划有效期、配置、令牌、数据根、临时副本和 runner，子进程以 `python -I -B`、清理环境和关闭 stdin 运行；联网与同步能力绑定精确日期窗口并在启动前各消费一次。计划还绑定解释器与 CLI 身份、可选 `pyvenv.cfg`、完整 site-packages 文件树及固定包元数据。不得从全局 `PATH` 寻找 CLI 或切换备用 API。文件哈希不是签名，也不能抵御同一 Windows 用户下可同时改写技能、计划和 runner 的敌对进程；这类要求必须使用独立服务账号、代码签名/WDAC/AppLocker 或不可变镜像作为外部信任根。同步返回成功后必须用目标数据库指纹和请求窗口的本地覆盖复核，不能只看退出码。默认安装不包含 GarminDB。

   - 用户明确要求启用自动同步时，使用 `scripts/install_auto_sync_task.ps1` 注册当前用户计划任务。默认每日 06:30 同步最近 7 个自然日，`StartWhenAvailable=true`、`MultipleInstances=IgnoreNew`、`RunLevel=Limited`、`LogonType=Interactive`；不保存账户密码，也不唤醒设备。调度动作必须指向本目录的 `scripts/garmin_auto_sync.py` 并保留显式能力标志，每次重新生成 900 秒短期计划。运行器总预算必须短于任务的物理执行上限，并在获得单例锁后、每个阶段开始前、成功或失败时原子更新脱敏状态；外部终止后遗留的 `running` 状态必须被下一次读取识别为 `interrupted_or_terminated`，不得误报成功。失败不在同一次运行中重试，等待下一日调度或由获授权的新鲜度门启动一次。日记和复盘需要新鲜度同步时，直接运行两阶段同步：先 `sync_health_data.py sync --dry-run` 生成短期计划，再 `sync_health_data.py sync --allow-network --allow-sync` 执行，沿用 7 个自然日窗口并验证终态起止日期、数据库变化和五组件末端覆盖。不经计划任务触发；授权、身份或覆盖验证失败均失败关闭。
   - 自动同步状态只允许保存运行 ID、请求窗口、当前阶段、逐组件观测数量和最近观测日期、数据库指纹变化布尔值、错误类型及完成时间；不得保存健康数值、令牌、配置内容、本地路径或子进程原始错误正文。只有能力、解释器预检和同步计划验证通过、数据库指纹发生变化、五个必需组件的最近观测日期均到达请求末日、且同步后本地重读通过，才允许 `status=success`。注册后检查任务动作、最低权限、下次运行时间和状态文件，并手动启动一次任务完成跨表面验证。


## 时间预算与兼容性

- `sync_health_data.py --timeout-seconds` 表示整次调用预算，默认且最多 180 秒；超过上限的旧参数也会被收敛到 180 秒。所有下载、导入阶段共享单调时钟截止时间，各子进程只使用剩余预算；核验前后再次检查，超时不得返回成功。超时可能已经完成部分下载或导入，不能声称已回滚；先只读核对数据库指纹与窗口覆盖，再按新的有效计划恢复。
- 自动同步包装器也将总预算上限设为 180 秒，并为子进程退出留出时间。新的计划任务模板将 Windows ExecutionTimeLimit 设为 3 分钟；磁盘模板修改不会更新已注册任务，本次维护不得擅自重新注册任务。
- 同步调用应配合运行时可用的 180 秒整命令超时。脚本对子进程实施剩余预算，并检查同步核验耗时，但进程内文件哈希和数据库核验不是可抢占硬截止；没有宿主监督时，不声称全部清理与核验必定在 180 秒内结束。必要宿主超时能力缺失时停止实际写入。
- 默认安装不包含 GarminDB。现有 `garmindb==3.9.0` / `garminconnect==0.3.17` 组合存在上游依赖声明冲突，不能只因版本门通过就报告兼容；处理边界见 [运行时兼容性](runtime_compatibility.md)。本次不安装、降级或修改 runner 环境。
