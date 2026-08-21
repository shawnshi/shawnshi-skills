---
name: personal-health-analysis
description: 以本地优先方式分析 Garmin 睡眠、HRV、心率、压力、身体电量、夜间呼吸率、夜间血氧及数据质量，并生成 Markdown 报告或零外联 HTML 趋势面板。用于“分析睡眠”“查看 HRV/心率/压力”“评估身体状态”“分析个人趋势或睡眠规律”“生成健康报告或趋势图”等请求；显式调用本技能即默认授权读取请求窗口内受支持且与任务有关的健康指标，本地明确无数据时可在另行联网授权后转实时读取，同步和活动轨迹下载仍需单独授权，仅提供非诊断性健康信息。
---

# Garmin 健康数据分析

## 环境与授权

- 显式调用本技能即授权读取本次请求窗口内与分析用途绑定的 Garmin 健康指标；不再逐项询问健康数据授权。未给时间范围时默认最近 7 天，不得为了满足算法样本数自动扩大窗口。面板默认组件仅为 `sleep,hrv,body_battery,heart_rate,stress`；`activities` 与 `training_load_series` 只有任务明确需要时才读取。用户指定更窄指标时继续缩小。账户 Profile/Settings、设备闹钟、原始轨迹和认证材料不属于默认健康指标授权。
- 默认先读取 Garmin 本地数据库；本地分析不要求登录。只有本地结果明确为 `no_data`、用户本次已授权联网、日期窗口与组件清单已绑定、实时预检通过时，才允许转到云端。`partial`、数据库变化、Schema 错误、读取异常或联网授权不完整不得触发回退。
- 技能执行健康读取命令时自动附加 `--allow-health-data`，把上述技能调用授权落实为 CLI 能力；无需再次向用户确认。实时查询、认证、同步或活动文件下载仍须在本次请求中明确允许联网；登录写入令牌需 `--allow-token-write`，GarminDB 写入需 `--allow-sync`，活动原始文件落盘还需 `--allow-download`。这些副作用授权不能由默认健康数据读取授权推导。
- 不在分析任务中自动安装依赖。当前解释器可以是系统 Python、全局 Python 或调用方已管理的环境，不要求技能目录存在 `.venv`。先把 `<SKILL_PYTHON>` 解析为当前选定解释器的 `sys.executable` 绝对路径；同一任务的预检和数据命令必须使用这一个解释器，不得在失败后静默切换。
- 执行数据命令前运行模式预检：本地读取、报告和面板使用 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`；实时读取和认证使用 `--mode live`；解析 FIT/GPX/TCX 使用 `--mode activity`，实时下载并解析时两项都要通过。只有返回 `RUNTIME_READY` 才继续；否则返回 `RUNTIME_DEPENDENCY_UNAVAILABLE` 并停止，不自动安装、不联网补包、不尝试其他解释器。预检只核对当前模式直接依赖，不因解释器中存在无关包而拒绝运行。
- `install.ps1 -Offline -Wheelhouse <DIR>` 和 `install.sh --offline --wheelhouse <DIR>` 仅是用户明确要求时使用的可选隔离部署工具，不是普通运行前提。其锁文件、Wheel 哈希、无覆盖发布和隔离 pip 门禁保持不变；清单哈希只证明与已审核本地字节一致，不等于发布者签名。
- 从请求提取时间范围；未指定时使用默认最近 7 天。自动向本地或实时健康读取命令传入 `--allow-health-data`；用户明确指定指标时缩小范围，不能扩大到活动轨迹、账户资料或请求窗口之外。
- 需要指标解释时按需读取 `references/health_analysis.md`；只有用户授权实时访问时才读取 `references/api.md`，使用扩展指标、时间点查询或活动文件时读取 `references/advanced_tools.md`；准备真实链路或外部 FHIR 验收时读取 `references/external_acceptance.md`。`resources/clinical_guidelines.json` 只是可选方法配置，不是临床事实库；配置未启用、参数越界或来源元数据不可验证时，只做未分类观察。`readiness_index` 因输入血缘重叠而硬停用，即使配置被改为启用也不得生成总分。
- 安全关键入口包括 `scripts/runtime_preflight.py`、`scripts/wheelhouse_integrity.py`、`scripts/garmin_capabilities.py`、`scripts/garmin_auth.py`、`scripts/garmin_sqlite_adapter.py`、`scripts/garmin_intelligence.py`、`scripts/garmin_patterns.py`、`scripts/garmin_chart.py`、`scripts/garmin_data_extended.py`、`scripts/garmin_query.py`、`scripts/garmin_activity_files.py`、`scripts/sync_health_data.py`、`scripts/garmin_fhir_adapter.py` 和 `scripts/fhir_external_acceptance.py`；离线面板模板为 `assets/dashboard_v2.html`，技能发现元数据为 `agents/openai.yaml`。资源清单只说明文件已声明，不能替代授权门禁、内容哈希核验和离线测试。
- `garmin_intelligence.py insight_cn --source <local|live>` 透明路由到 `scripts/garmin_bounded.py`；该路径强制精确窗口、显式来源、live 令牌仅内存加载和 `persisted=false`。其他分析仍由完整非诊断入口处理，不得绕过各自能力门。

## 工作流程

1. 明确问题、时间范围和期望输出：单项指标、日度摘要、描述性模式分析或图表。未指定时间时使用默认最近 7 天；未指定指标时只读取该分析所需的最小组件。样本不足必须回显资格状态，不能把 7 天请求悄悄改成 28 天或更长窗口。
2. 默认使用本地、只读、失败关闭路径。先用同一 `<SKILL_PYTHON>` 运行 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`：
   - 单项或汇总：`<SKILL_PYTHON> scripts/garmin_data.py <sleep|hrv|heart_rate|body_battery|stress|summary> --days <N> --source local --allow-health-data`
   - 同日准备度输入观察或基线变化：`<SKILL_PYTHON> scripts/garmin_intelligence.py <readiness|baseline_change|insight_cn> --days <N> --source local --allow-health-data`。`readiness` 只对齐同日原始/厂商指标并固定返回 `not_scored`，不计算复合分数或行动等级。
   - 描述性个人趋势、睡眠规律与训练负荷滞后资格：`<SKILL_PYTHON> scripts/garmin_intelligence.py patterns --days <N> --source local --allow-health-data`。个人趋势至少需要 21 个历史观测日和最近 7 个完整自然日，最小请求窗口通常为 28 天；窗口更短时仍按原请求运行并返回不满足资格的原因。
   - 趋势面板：`<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days <N> --source local --allow-health-data --output <HTML_PATH>`
   - 已取得联网授权时的本地无数据回退：先让同一解释器通过 `--mode live` 预检，再运行 `<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days <N> --source local --fallback-live --components <COMMA_SEPARATED_COMPONENTS> --allow-network --allow-health-data --output <HTML_PATH>`。面板默认组件使用 `sleep,hrv,body_battery,heart_rate,stress`；用户指定指标时按请求缩小。`activities` 或 `training_load_series` 必须显式写入组件清单。
   - `--days N` 表示截至本地当前日、首尾包含的 N 个自然日；`--period` 只接受正整数天数或 `YTD`，且 `YTD` 包含 1 月 1 日与当前日。非法、零值或负值不得静默改写。报告必须回显实际起止日期、数据日期和每项覆盖率。
3. 在 Windows 控制台乱码时设置 `PYTHONIOENCODING=utf-8`。不要自动安装依赖、登录账户或修改数据库。
4. 检查数据采集时间、缺失率、设备佩戴空档和脚本错误。本地单项、汇总、洞察及面板必须在数据库前后 SHA-256、Schema、WAL/SHM 均未变化的验证读取窗口内完成；结果只披露数据库名和摘要。覆盖状态按实际非空观测区分 `complete`、`partial` 与 `no_data`；只有 `no_data` 可以进入已授权的实时回退，`partial` 继续使用本地数据。SQL、Schema 或读取窗口错误必须以非零退出和机器可读 `read_error` 失败关闭。缺失聚合必须保持 `null`，不得变成生理值 0。
   - HTML 面板只嵌入 `dashboard.v3` 展示契约允许的字段；用户缩小组件范围时，本地提取器不得读取无关健康表，视图构造器还必须再次丢弃未请求字段。不得携带未渲染的健康指标、设备序列号、本地路径、数据库哈希或调试数据。页面保持零外联。
   - 信任栏必须显示请求日期、实际观测日期、有效来源、新鲜度、逐指标覆盖、设备/固件时期证据和完整性状态。日期只有自然日语义时，应明确说明没有可靠时区信息。
   - 静息心率百分比变化只使用 `baseline_change` 的合格结果：至少 21 个成对历史日、日期对齐、方差可分类，且设备、固件、分析算法时期和厂商算法时期均有可比证据。固件一致不能替代厂商算法时期证据；任何门禁未通过都显示“未计算”和原因，不绘制基线参考线。
   - 每个 KPI 绑定自己的最近观测日期和覆盖率，不能让不同日期的指标看起来像同日快照。睡眠阶段缺失保持空值，只有三个阶段都存在时才堆叠；Body Battery 固定使用 0–100 纵轴。
   - `insight_cn` 必须在 `audit_data` 中保留最近一次睡眠的观测日期和总时长，并标明逐组件覆盖；总睡眠已用于计算阶段占比时，不得因展示层漏字段而声称来源没有睡眠时长。来源没有提供睡眠负债时保持 `sleep_debt_h=null`，同时返回 `sleep_debt_status=not_provided_by_source`。
   - 中文可读摘要不得直接显示 Python `None`；没有有效观测时显示“无有效观测”，并保留机器可读字段为 `null`。压力等指标缺失时不得写成 0，也不得把单项缺失扩写成整个 Garmin 读取失败。
   - 压力卡只显示 Garmin 日均压力及同一来源日期的高压、中压、休息原始时长；实验性加权压力不得进入决策面板。睡眠评分热图窗口少于 14 天时显示“窗口不足”，不得写成“无数据”。
   - 描述性模式分析先检查逐指标连续性、同日重复冲突、样本量及设备/固件时期。缺失值、冲突日和不可比时期均失败关闭：不插值、不把空白日当 0，也不输出依赖这些数据的比较值。
   - 夜间呼吸率和夜间血氧只展示设备记录及同一个人的时间趋势，不使用单点阈值判断呼吸疾病或缺氧。血氧数据来自消费级设备时必须明确非诊断用途。
   - Body Battery 与睡眠评分都受睡眠、压力等上游信号影响；Body Battery 还结合 HRV、活动等输入。两项不能当作彼此独立的重复证据，也不得合成为总健康分。
5. 仅在用户本次明确允许联网且 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode live` 返回 `RUNTIME_READY` 时使用实时路径：传入 `--allow-network`，并依据默认健康读取授权自动附加 `--allow-health-data`；日期使用请求窗口，未指定时为最近 7 天。直接实时读取使用 `--source live`；自动回退使用本地 `--source local --fallback-live`，并用 `--components` 绑定默认五个面板组件或用户指定的更窄子集。实时面板只能读取已绑定组件；不读取 Profile、体成分、补水、Fitness Age 或设备闹钟。实时洞察按分析用途进一步缩小组件；不具备当前实时实现的分析必须在客户端初始化前返回 `LIVE_ANALYSIS_NOT_SUPPORTED`。点时查询还必须显式给出日期、IANA 时区和最大容差。能力对象绑定绝对起止日期与组件清单，健康数据与下载能力仅能消费一次；不得直接调用 `get_client()` 绕过 CLI 门禁。
6. 只有用户明确要求同步后，才执行两阶段同步：先运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json` 生成短期计划；核对范围和绑定摘要后，再在计划有效期内运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <SESSION_SCRATCH>/sync-plan.json`。GarminDB runner 可使用显式指定的全局 Python 或虚拟环境，不要求独立虚拟目录；必须在解释器相邻安装中定位 CLI，并核对固定版本 `garmindb==3.8.0` 与 `garminconnect==0.3.9`。计划同时绑定配置、同目录令牌、解析后的绝对数据根及 `DBs` 目录身份；执行时只把配置与令牌复制到自动删除的临时目录，并把临时配置改写为已绑定的绝对数据根。GarminDB 的结束日为开区间，因此临时配置把用户结束日加一天，只用于保持用户窗口首尾包含；运行分成“精确窗口下载”和“仅导入本次新增文件并分析”两个子阶段，禁止全历史重复导入。启动前要重新核对计划有效期、配置、令牌、数据根、临时副本和 runner，子进程以 `python -I -B`、清理环境和关闭 stdin 运行；联网与同步能力绑定精确日期窗口并在启动前各消费一次。计划还绑定解释器与 CLI 身份、可选 `pyvenv.cfg`、完整 site-packages 文件树及固定包元数据。不得从全局 `PATH` 寻找 CLI 或切换备用 API。文件哈希不是签名，也不能抵御同一 Windows 用户下可同时改写技能、计划和 runner 的敌对进程；这类要求必须使用独立服务账号、代码签名/WDAC/AppLocker 或不可变镜像作为外部信任根。同步返回成功后必须用目标数据库指纹和请求窗口的本地覆盖复核，不能只看退出码。默认安装不包含 GarminDB。
7. 将观察值、可能解释和不能判断的事项分开。`baseline_change` 只描述相对个人基线的变化，不对应疾病风险；覆盖不足、日期未对齐、基线少于 21 个同日样本、零方差、`duplicate_conflict`、`cross_epoch`、`manufacturer_algorithm_epoch_unknown`、`analysis_algorithm_epoch_unknown` 或其他 `epoch_unknown` 时不分类。`patterns` 的方向只表示高于、低于、等于或混合于个人历史中位数，不含健康好坏含义。`readiness` 始终不生成复合分数、红黄绿灯或行动等级。任何脚本结果都不得决定训练、补剂、日程或重要决策。
8. 仅在指标多、周期长且任务可独立拆分时使用子代理；传递最小化、去标识的数据。未经用户许可不得把健康数据发送给外部服务。
9. 用户要求生成持久化报告或面板时，先运行 `<SKILL_PYTHON> scripts/report_output.py --days <N>`，取得同一批次的 `markdown` 和 `html` 绝对路径。
10. 将最终 Markdown 正文写入返回的 `markdown` 路径；生成面板时把返回的 `html` 路径传给 `garmin_chart.py --output <HTML_PATH>`。默认拒绝覆盖现有文件；只有用户明确要求替换时才使用对应覆盖参数。

## 描述性模式分析合同

- `patterns.v1` 始终使用用户请求窗口并先返回资格。个人趋势要求 21 个历史观测日加最近 7 个完整自然日；睡眠规律检查末端 14 日且至少有 7 个有效夜晚，时长与时点资格独立。缺少带 UTC 偏移的起止时间时，时点保持 `source_not_supported`。
- `patterns` 当前只支持本地只读来源；`--source live` 必须在建立客户端前返回 `LIVE_ANALYSIS_NOT_SUPPORTED`，不能把面板实时读取能力外推为模式分析实时能力。
- 训练负荷目前是 `event_stream`，空白日不等于零。只有上游证明 `explicit_daily_zero` 且形成至少 28 个精确 `t→t+1` 配对时，才计算 Spearman 秩相关；相关不表示因果。
- 缺失、同日冲突、`cross_epoch` 或 `epoch_unknown` 均失败关闭。同日冲突门禁同时适用于个人趋势、睡眠时长/时点规律和训练负荷滞后分析。面板只保留渲染所需的聚合结果，不写入睡眠原始起止时间或关联配对日期。
- 运行模式分析或解释资格状态前读取 `references/health_analysis.md` 的“数据资格与连续性”“`patterns.v1` 描述性方法”和“当前来源的 P2 边界”；其中列出 `historical_baseline_insufficient`、`recent_window_incomplete`、`partial_available`、`load_coverage_unknown` 与 `not_requested` 等状态的精确定义。

## 报告归档契约

- Garmin 分析产出的 `.md` 和 `.html` 默认保存在当前工作区的 `output/personal-health-analysis`。
- `GARMIN_REPORT_DIR` 可覆盖默认目录；`GARMIN_OUTPUT_DIR` 仅作为旧版兼容项。用户显式指定的输出路径优先。
- 同一次分析的 Markdown 和 HTML 必须共享文件名主干，例如 `health_analysis_7days_20260727_093045.md` 与 `.html`。
- 临时 JSON、数据库副本、FIT/GPX 活动文件、认证令牌和调试日志不得写入报告归档目录；中间文件放入当前会话的 `scratch`。
- 普通问答或单项指标查询不自动落盘。用户提出“生成报告、面板、大屏”即授权保存该次请求的 MD/HTML，不扩大为数据同步、外部分享或长期洞察注册。
- `GARMIN_STATE_DIR` 不构成保存授权。只有用户要求保存最小状态记录时才向 `garmin_intelligence.py` 传入显式 `--state-output <FILE>`。

## 输出

- 数据范围、来源和新鲜度
- 关键指标及变化
- 每项深入分析的资格状态、实际样本数、所需样本数与失败关闭原因
- 可能解释与证据限制
- 可供用户核验的情境因素、未知项和后续观察问题，不输出训练或日程指令
- 需要升级处理的风险
- 持久化任务的 Markdown 与 HTML 绝对路径

FHIR 仅提供离线 `FHIR_EXPORT_RESEARCH_ONLY` 包装：输入必须是用户显式指定的本地 JSON，输出必须显式确认 `--acknowledge-research-only`。只支持 HRV 毫秒、静息心率和睡眠时长三个文本编码指标；Provenance 同时区分调用方声明的上游来源摘要和适配器实算的输入 JSON 摘要，可选设备标识只能传 64 位小写十六进制摘要。不使用 LOINC，不生成解释或参考区间，不访问 Garmin 或 FHIR 服务器，也不宣称临床互操作。状态和导出回执必须把 R4 结构、Profile/IG、术语、接收端四道外部门禁标为 `not_performed`。收到外部验证材料后可用 `scripts/fhir_external_acceptance.py` 盘点 Bundle、工具和包摘要及每道门禁；它不运行外部工具、不验证签名，只能检查调用方材料内部一致性。调用方声明的 `passed` 必须降为 `indeterminate`，回执固定保持 `ok=false`、`external_acceptance_established=false` 与 `clinical_interoperability=false`。具体输入与命令读取 `references/advanced_tools.md` 和 `references/external_acceptance.md`。

避免伪精确评分。比较个人基线时说明基线窗口和算法；没有足够历史数据时，不给出趋势结论。不得推荐药物、补剂或剂量，不得要求强制训练、停止训练、取消会议、修改闹钟或禁止决策。

## 医疗安全边界

- 不诊断、不开药、不调整处方，也不把穿戴设备数据称为临床级证据。
- 不根据消费级设备分数推断感染、炎症、免疫状态、认知能力或职业表现；只可按来源描述厂商已有分数，不自行合成准备度总分或行动分区。
- 出现胸痛、严重呼吸困难、晕厥、疑似中风、持续极端心率或用户描述的其他急症信号时，停止常规分析并建议立即联系当地急救服务。
- 对持续异常、明显症状或影响生活的变化，建议咨询合格医疗人员，并携带原始数据。
- 不自动保存、同步或注册健康洞察。长期存储或共享必须说明数据、目的和目标位置，并取得明确授权。
