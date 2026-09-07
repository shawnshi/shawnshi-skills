# Garmin 分支执行合同

本页保留执行细节；按 SKILL.md 所选分支读取对应节，不要求无条件读完整页。各节独立编号，按所选任务执行。指标解释继续复用 health_analysis.md，画像复用 health_profile.md，实时访问复用 api.md，扩展工具与研究验收复用 advanced_tools.md、external_acceptance.md。

## 运行前提

- 本目录是唯一健康运行时权威。每次被个人日记或认知复盘调用时，先运行 `<SKILL_PYTHON> scripts/runtime_authority.py --config runtime-authority.json`；仅在返回 `ok=true` 后使用其 `skill_root`、`entrypoints` 与版本。其他发现代理只允许指向同一版本和 SHA-256 的本权威文件，禁止执行代理目录中的脚本。权威、入口哈希或代理绑定漂移时返回 `HEALTH_RUNTIME_AUTHORITY_MISMATCH`，停止健康读取、同步与实时回退。
- 显式调用本技能即授权读取本次请求窗口内与分析用途绑定的 Garmin 健康指标；不再逐项询问健康数据授权。普通趋势面板默认组件仍为 `sleep,hrv,body_battery,heart_rate,stress`；未指定指标的综合健康分析默认使用全面健康画像，并增加体重、非位置化已记录活动摘要、日常活动强度、HRV 厂商基线、睡眠起止/清醒、夜间呼吸/血氧及最新分模态 VO₂max 估计。体重和活动只在请求窗口内做汇总，并各读取截至窗口末端的单条最近记录用于披露新鲜度；不得据此扩展趋势窗口。活动画像不得读取活动 ID、名称、描述、设备序列号、坐标或原始轨迹。面板 `activities` 组件、逐活动明细、原始活动文件与 `training_load_series` 仍只有任务明确需要时才读取。用户指定更窄指标时继续缩小。饮水、账户 Profile/Settings、设备闹钟、原始轨迹和认证材料不属于默认健康指标授权。
- 默认先读取 Garmin 本地数据库；本地分析不要求登录。显式调用本技能同时授权：仅当本地结果明确为 `no_data`、日期窗口与组件清单保持不变且实时预检通过时，对同一窗口和组件执行云端只读回退。`partial`、数据库变化、Schema 错误或其他读取异常不得触发回退。个人日志或认知复盘的 current-date 新鲜度请求直接运行两阶段同步（`sync_health_data.py`），不再启动 Windows 计划任务；授权、身份或覆盖验证失败不得进入该分支。
- 技能执行健康读取命令时自动附加 `--allow-health-data`；进入上述一次性回退时再自动附加 `--allow-network`。两个 CLI 标志仍是本次命令的显式能力门，不得从脚本中移除，也不得跨命令、跨窗口或跨用途复用。默认授权不包含直接跳过本地读取、Garmin 登录或认证状态探测、令牌创建或刷新、数据库同步、活动文件下载及其他持久化；这些操作分别需要本次明确授权，并继续要求 `--allow-token-write`、`--allow-sync` 或 `--allow-download`。
- 不在分析任务中自动安装依赖。当前解释器可以是系统 Python、全局 Python 或调用方已管理的环境，不要求技能目录存在 `.venv`。先把 `<SKILL_PYTHON>` 解析为当前选定解释器的 `sys.executable` 绝对路径；同一任务的预检和数据命令必须使用这一个解释器，不得在失败后静默切换。
- 执行数据命令前运行模式预检：本地读取、报告和面板使用 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`；实时读取和认证使用 `--mode live`；解析 FIT/GPX/TCX 使用 `--mode activity`，实时下载并解析时两项都要通过。只有返回 `RUNTIME_READY` 才继续；否则返回 `RUNTIME_DEPENDENCY_UNAVAILABLE` 并停止，不自动安装、不联网补包、不尝试其他解释器。预检只核对当前模式直接依赖，不因解释器中存在无关包而拒绝运行。
- `install.ps1 -Offline -Wheelhouse <DIR>` 和 `install.sh --offline --wheelhouse <DIR>` 仅是用户明确要求时使用的可选隔离部署工具，不是普通运行前提。其锁文件、Wheel 哈希、无覆盖发布和隔离 pip 门禁保持不变；清单哈希只证明与已审核本地字节一致，不等于发布者签名。
- 需要指标解释时按需读取 `references/health_analysis.md`；生成全面健康画像或多维健康指导时读取 `references/health_profile.md`；只有用户授权实时访问时才读取 `references/api.md`，使用扩展指标、时间点查询或活动文件时读取 `references/advanced_tools.md`；准备真实链路或外部 FHIR 验收时读取 `references/external_acceptance.md`。`resources/clinical_guidelines.json` 只是可选方法配置，不是临床事实库；配置未启用、参数越界或来源元数据不可验证时，只做未分类观察。`readiness_index` 因输入血缘重叠而硬停用，即使配置被改为启用也不得生成总分。
- 安全关键入口包括 `scripts/runtime_preflight.py`、`scripts/wheelhouse_integrity.py`、`scripts/garmin_capabilities.py`、`scripts/garmin_auth.py`、`scripts/garmin_sqlite_adapter.py`、`scripts/garmin_intelligence.py`、`scripts/garmin_health_profile.py`、`scripts/garmin_patterns.py`、`scripts/garmin_chart.py`、`scripts/garmin_data_extended.py`、`scripts/garmin_query.py`、`scripts/garmin_activity_files.py`、`scripts/sync_health_data.py`、`scripts/garmin_fhir_adapter.py` 和 `scripts/fhir_external_acceptance.py`；离线面板模板为 `assets/dashboard_v2.html`，技能发现元数据为 `agents/openai.yaml`。资源清单只说明文件已声明，不能替代授权门禁、内容哈希核验和离线测试。
- `garmin_intelligence.py insight_cn --source <local|live>` 透明路由到 `scripts/garmin_bounded.py`；该路径强制精确窗口、显式来源、live 令牌仅内存加载和 `persisted=false`。其他分析仍由完整非诊断入口处理，不得绕过各自能力门。

## 本地分析

1. 明确问题、时间范围和期望输出：单项指标、日度摘要、描述性模式分析或图表。未指定时间时使用默认最近 14 天（交互层 `N=14`）；本地读取、回退、报告命名和面板等窗口型 CLI 均显式传入同一个 `--days <N>`，不依赖各 CLI 已有默认值，且不修改这些 CLI defaults。用户指定窗口时以该窗口为准；未指定指标时只读取该分析所需的最小组件。样本不足必须回显资格状态，不能把 7 天请求悄悄改成 28 天或更长窗口。

2. 默认使用本地、只读、失败关闭路径。先用同一 `<SKILL_PYTHON>` 运行 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode local`：
   - 单项或汇总：`<SKILL_PYTHON> scripts/garmin_data.py <sleep|hrv|heart_rate|body_battery|stress|summary> --days <N> --source local --allow-health-data`
   - 同日准备度输入观察或基线变化：`<SKILL_PYTHON> scripts/garmin_intelligence.py <readiness|baseline_change|insight_cn> --days <N> --source local --allow-health-data`。`readiness` 只对齐同日原始/厂商指标并固定返回 `not_scored`，不计算复合分数或行动等级。
   - 多维健康画像：`<SKILL_PYTHON> scripts/garmin_health_profile.py --days <N> --source local --timezone <IANA_TIMEZONE> --allow-health-data`。它在精确窗口内联合分析睡眠规律/设备估算连续性、HRV 厂商基线、静息心率、Body Battery 充放电、体重、非位置化已记录活动摘要、最近 7 日强度分钟、夜间呼吸/血氧和分模态 VO₂max 新鲜度，不生成总分。体重与活动各允许读取截至窗口末端的单条最近记录，只用于说明新鲜度和窗口外标志，不纳入窗口趋势。数据库睡眠时间没有偏移时必须显式传入用户提供或运行环境明确的 IANA 时区并披露这一假设；否则省略 `--timezone` 并返回 `timezone_required`。只有用户确认属于 18–64 岁成年人且明确要求 WHO 参考比较时，才附加 `--adult-18-64-guideline`。可选 `--context-file <LOCAL_JSON>` 仅接收本人明确选择的本地情境文件：先过健康权限门，再按同一窗口验证封闭 Schema，任何输入错误在数据库读取前失败关闭；不自动创建文件或保存情境，具体类型、上限和合成示例见 `health_profile.md` 的 P2 节。
   - 描述性个人趋势、睡眠规律与训练负荷滞后资格：`<SKILL_PYTHON> scripts/garmin_intelligence.py patterns --days <N> --source local --allow-health-data`。个人趋势至少需要 21 个历史观测日和最近 7 个完整自然日，最小请求窗口通常为 28 天；窗口更短时仍按原请求运行并返回不满足资格的原因。
   - `--days N` 表示截至本地当前日、首尾包含的 N 个自然日；适配器必须收到同一个 `N`，不得以 `N-1` 再缩短一次窗口。`--period` 只接受正整数天数或 `YTD`，且 `YTD` 包含 1 月 1 日与当前日。非法、零值或负值不得静默改写。报告必须回显实际起止日期、数据日期和每项覆盖率。

3. 在 Windows 控制台乱码时设置 `PYTHONIOENCODING=utf-8`。不要自动安装依赖、登录账户或修改数据库。

4. 将观察值、可能解释和不能判断的事项分开。`baseline_change` 只描述相对个人基线的变化，不对应疾病风险；覆盖不足、日期未对齐、基线少于 21 个同日样本、零方差、`duplicate_conflict`、`cross_epoch`、`manufacturer_algorithm_epoch_unknown`、`analysis_algorithm_epoch_unknown` 或其他 `epoch_unknown` 时不分类。`patterns` 的方向只表示高于、低于、等于或混合于个人历史中位数，不含健康好坏含义。`readiness` 始终不生成复合分数、红黄绿灯或行动等级。任何脚本结果都不得决定训练、补剂、日程或重要决策。

5. 仅在指标多、周期长且任务可独立拆分时使用子代理；传递最小化、去标识的数据。未经用户许可不得把健康数据发送给外部服务。

### 描述性模式分析合同

- `patterns.v1` 始终使用用户请求窗口并先返回资格。个人趋势要求 21 个历史观测日加最近 7 个完整自然日；睡眠规律检查末端 14 日且至少有 7 个有效夜晚，时长与时点资格独立。缺少带 UTC 偏移的起止时间时，时点不能通过来源资格。画像 3 夜统计只标为窗口描述，正式规律性只读取 `qualified_regularity`，不能用旧描述字段的 `eligible` 代替。时期门阻断时仍披露 `duration_observed_nights`、`timing_observed_nights` 的实际来源有效日数。
- `patterns` 当前只支持本地只读来源；`--source live` 必须在建立客户端前返回 `LIVE_ANALYSIS_NOT_SUPPORTED`，不能把面板实时读取能力外推为模式分析实时能力。
- 训练负荷目前是 `event_stream`，空白日不等于零。只有上游证明 `explicit_daily_zero` 且形成至少 28 个精确 `t→t+1` 配对时，才计算 Spearman 秩相关；相关不表示因果。
- 缺失、同日冲突、`cross_epoch` 或 `epoch_unknown` 均失败关闭。同日冲突门禁同时适用于个人趋势、睡眠时长/时点规律和训练负荷滞后分析。面板只保留渲染所需的聚合结果，不写入睡眠原始起止时间或关联配对日期。
- 运行模式分析或解释资格状态前读取 `references/health_analysis.md` 的“数据资格与连续性”“`patterns.v1` 描述性方法”和“当前来源的 P2 边界”；其中列出 `historical_baseline_insufficient`、`recent_window_incomplete`、`partial_available`、`load_coverage_unknown` 与 `not_requested` 等状态的精确定义。

## 数据质量

1. 检查数据采集时间、缺失率、设备佩戴空档和脚本错误。本地单项、汇总、洞察及面板必须在数据库前后 SHA-256、Schema、WAL/SHM 均未变化的验证读取窗口内完成；结果只披露数据库名和摘要。全库 SHA-256 的读取成本随数据库及 WAL/SHM 大小增长，并非只随请求天数增长；在测量前不得以缩短窗口、缓存或抽样替代完整性门，也不得弱化前后全量哈希校验。覆盖状态按实际非空观测区分 `complete`、`partial` 与 `no_data`；只有 `no_data` 可以进入已授权的实时回退，`partial` 继续使用本地数据。SQL、Schema 或读取窗口错误必须以非零退出和机器可读 `read_error` 失败关闭。缺失聚合必须保持 `null`，不得变成生理值 0。
   - HTML 面板只嵌入 `dashboard.v3` 展示契约允许的字段；用户缩小组件范围时，本地提取器不得读取无关健康表，视图构造器还必须再次丢弃未请求字段。不得携带未渲染的健康指标、设备序列号、本地路径、数据库哈希或调试数据。页面保持零外联。
   - 信任栏必须显示请求日期、实际观测日期、有效来源、新鲜度、逐指标覆盖、设备/固件时期证据和完整性状态。设备数明确标为库存记录，不代表窗口内使用了多台设备。内部 `observation_attributions` 只消费受信来源显式提供的组件/日期/设备/固件归属，不新增 CLI 或数据库读取字段；缺组件、缺日期、未知标识/版本或归属冲突不能证明可比，分别披露 `device_attribution_unknown` 或 `device_attribution_conflict`。历史库存不转换为归属；确有归属的跨设备/固件仍返回 `cross_epoch`。厂商与分析算法时期门独立保留。归属明细和原始设备标识不得进入面板；日期只有自然日语义时，应明确说明没有可靠时区信息。
   - 静息心率百分比变化只使用 `baseline_change` 的合格结果：至少 21 个成对历史日、日期对齐、方差可分类，且设备、固件、分析算法时期和厂商算法时期均有可比证据。固件一致不能替代厂商算法时期证据；任何门禁未通过都显示“未计算”和原因，不绘制基线参考线。
   - 每个 KPI 绑定自己的最近观测日期和覆盖率，不能让不同日期的指标看起来像同日快照。睡眠阶段缺失保持空值，只有三个阶段都存在时才堆叠；Body Battery 固定使用 0–100 纵轴。睡眠、静息心率、步数、夜间呼吸率、HRV、Body Battery、Garmin 日均压力和夜间 Pulse Ox 的请求末日缺失时，仍须保留并绘制此前有效观测，并在对应图表内标注“`<末日日期> 暂无来源观测`”，说明若为当天，记录可能尚未完整，不代表同步失败；不得把末日缺失扩写为整个窗口无数据。
   - `insight_cn` 必须在 `audit_data` 中保留最近一次睡眠的观测日期和总时长，并标明逐组件覆盖；总睡眠已用于计算阶段占比时，不得因展示层漏字段而声称来源没有睡眠时长。来源没有提供睡眠负债时保持 `sleep_debt_h=null`，同时返回 `sleep_debt_status=not_provided_by_source`。
   - 中文可读摘要不得直接显示 Python `None`；没有有效观测时显示“无有效观测”，并保留机器可读字段为 `null`。压力等指标缺失时不得写成 0，也不得把单项缺失扩写成整个 Garmin 读取失败。
   - 压力卡只显示 Garmin 日均压力及同一来源日期的高压、中压、休息原始时长；实验性加权压力不得进入决策面板。睡眠评分热图窗口少于 14 天时显示“窗口不足”，不得写成“无数据”。
   - 描述性模式分析先检查逐指标连续性、同日重复冲突、样本量及设备/固件时期。缺失值、冲突日和不可比时期均失败关闭：不插值、不把空白日当 0，也不输出依赖这些数据的比较值。
   - 夜间呼吸率和夜间血氧只展示设备记录及同一个人的时间趋势，不使用单点阈值判断呼吸疾病或缺氧。血氧数据来自消费级设备时必须明确非诊断用途。
   - Body Battery 与睡眠评分都受睡眠、压力等上游信号影响；Body Battery 还结合 HRV、活动等输入。两项不能当作彼此独立的重复证据，也不得合成为总健康分。
   - 全面画像优先展示睡眠规律、HRV 厂商基线、Body Battery 动态、体重、非位置化已记录活动、日常活动分布、夜间生理和 VO₂max 新鲜度八个互补视角。体重窗口趋势至少需要 3 次测量且跨越 14 天；否则只报告观测和新鲜度，不计算变化速度。已记录活动是事件流，空白日不等于零活动；活动摘要不得读取位置、活动标识、名称或描述。睡眠连续性固定命名为 `device_estimated_sleep_continuity`，不是临床睡眠效率；步数不使用通用“1 万步”阈值；强度分钟默认只比较用户自己的 Garmin 目标；VO₂max 不跨跑步与骑行模态比较。

## 离线可视化与报告

- 原生面板在信任栏后展示重点问题、覆盖缺口和最多两项可选行动，再保留原有 KPI 与曲线。P3 薄切片复用 P1 纯函数，仅映射已请求的睡眠时长、HRV、静息心率及已有正式睡眠资格；不调用全面画像读取器，不补充厂商区间、时点连续性、活动或体重。未支持的问题不展示，描述可用不等于恢复比较合格。
- 面板可选 `--context-file <LOCAL_JSON>` 复用画像 P2 的封闭 Schema、文件上限和本地路径验证；所有权限门之后、数据库/云读取之前验证同一窗口。没有请求 `sleep` 时返回 `context_not_requested`，不读情境文件或扩大组件。省略参数不新增数据读取。HTML 只保留本人记录/完成计数、字段覆盖与同日设备时长聚合；不保留原始记录、钟点、路径或阶段明细，也不评估疗效。原始 P2 阶段复盘仍仅在画像中可用。

- 趋势面板：`<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days <N> --source local --allow-health-data --output <HTML_PATH>`。最终 HTML 必须是该命令的直接输出，不得再由通用看板、网页或图表渲染器覆盖、包装或重写。
- 显式调用本技能后的本地无数据回退：仅当本地结果为 `no_data`，先让同一解释器通过 `--mode live` 预检，再消耗本次默认授权，运行 `<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days <N> --source local --fallback-live --components <COMMA_SEPARATED_COMPONENTS> --allow-network --allow-health-data --output <HTML_PATH>`。面板默认组件使用 `sleep,hrv,body_battery,heart_rate,stress`；用户指定指标时按请求缩小。`activities` 或 `training_load_series` 必须由用户明确请求后写入组件清单。

1. 用户要求生成持久化报告或面板时，先运行 `<SKILL_PYTHON> scripts/report_output.py --days <N>`，取得同一批次的 `markdown` 和 `html` 绝对路径。

2. 将最终 Markdown 正文写入返回的 `markdown` 路径；正文必须包含明确的“整体评价”和“后续建议”两节。整体评价先交代覆盖率、新鲜度和分析资格，再概括可观察的个人趋势；后续建议至少区分数据同步/佩戴核实、生活情境记录和必要时的医疗升级，不给出药物、补剂、训练或日程指令。生成面板时把返回的 `html` 路径传给 `garmin_chart.py --output <HTML_PATH>`，并保留该脚本生成的原生页面。默认拒绝覆盖现有文件；只有用户明确要求替换时才使用对应覆盖参数。

### 报告归档契约

- Garmin 分析产出的 `.md` 和 `.html` 默认保存在 `C:\Users\shich\MEMORY\raw\garmin`。
- `GARMIN_REPORT_DIR` 可覆盖默认目录；`GARMIN_OUTPUT_DIR` 仅作为旧版兼容项。用户显式指定的输出路径优先。
- 同一次分析的 Markdown 和 HTML 必须共享文件名主干，例如 `health_analysis_7days_20260727_093045.md` 与 `.html`。
- 临时 JSON、数据库副本、FIT/GPX 活动文件、认证令牌和调试日志不得写入报告归档目录；中间文件放入当前会话的 `scratch`。
- 普通问答或单项指标查询不自动落盘。用户提出“生成报告、面板、大屏”即授权保存该次请求的 MD/HTML，不扩大为数据同步、外部分享或长期洞察注册。
- `GARMIN_STATE_DIR` 不构成保存授权。只有用户要求保存最小状态记录时才向 `garmin_intelligence.py` 传入显式 `--state-output <FILE>`。
- 已明确启用的自动同步任务可更新其单一脱敏运行状态文件；该例外不授权保存分析正文、原始健康数值、凭据或第二份状态副本。

### 输出

- 数据范围、来源和新鲜度
- 关键指标及变化
- 每项深入分析的资格状态、实际样本数、所需样本数与失败关闭原因
- 多维画像中逐模块的指标血缘、设备算法依赖、最新观测日期与窗口末端缺失；体重和活动还要披露窗口内样本、最近记录新鲜度及是否落在请求窗口外
- 画像新增 `problem_insights.v1` 问题导向观察：只使用已有内存摘要，分别回答睡眠机会/连续性、恢复比较资格、活动记录/设备目标；保留证据指针、日期/覆盖、未验证解释和缺失证据，全局最多两项去重可选行动且覆盖核验优先。具体字段及“不把描述可用当成比较合格”的规则见 `health_profile.md`。可选 P2 `user_context_review` 只聚合本人主动提供的 `--context-file`，提供单一观察行动计数、显式阶段日期及字段覆盖；缺失保留未知，阶段并列不是疗效或因果结论，不解锁时期/趋势门。不新增数据库查询、自动保存、长期记录或图表布局。
- 可能解释与证据限制
- 整体评价：先说明覆盖、新鲜度与分析资格，再总结有证据支持的个人趋势
- 后续建议：列出数据同步/佩戴核实、生活情境记录和必要时的医疗升级，不输出训练或日程指令
- 需要升级处理的风险
- 持久化任务的 Markdown 与 HTML 绝对路径

## 受限实时回退

1. 显式调用本技能默认授权一次“本地 `no_data` 后、同窗口、同组件”的实时只读回退；不得因该授权跳过本地路径。回退前必须让同一 `<SKILL_PYTHON>` 通过 `scripts/runtime_preflight.py --mode live`，命令同时传入 `--allow-network` 与 `--allow-health-data`。日期沿用请求窗口，未指定时为最近 14 天（与本地读取同一个 `N=14`）；自动回退使用 `--source local --fallback-live` 并以 `--components` 绑定默认五个面板组件或用户指定的更窄子集。用户明确要求直接实时来源时可使用 `--source live`，仍须绑定精确窗口和最小组件。实时面板不读取 Profile、体成分、补水、Fitness Age 或设备闹钟；实时洞察按用途继续缩小组件。不具备当前实时实现的分析必须在客户端初始化前返回 `LIVE_ANALYSIS_NOT_SUPPORTED`。点时查询还必须显式给出日期、IANA 时区和最大容差。能力对象只能消费一次；不得直接调用 `get_client()` 绕过 CLI 门禁。

## 显式同步管理

- 用户明确要求启用 Garmin 自动同步时，该请求授权注册或更新一个当前用户、最低权限的计划任务。用户明确启用后，已注册的计划任务会按日自动同步到绑定的 GarminDB 本地数据库，并自动更新单一脱敏运行状态文件；该持续授权仅来自这次明确启用请求。任务动作仍必须显式携带 `--allow-network`、`--allow-sync` 与 `--allow-health-data`，不得把授权扩展到登录、令牌写入、活动轨迹下载、账户设置、代理、证书或其他存储。如果用户要求仅诊断、预览、不保存、试运行、不同步、禁用或移除自动同步，则保持只读，不注册或运行任务，也不写入数据库或状态文件。

1. 只有用户明确要求同步后，才执行两阶段同步：先运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json` 生成短期计划；核对范围和绑定摘要后，再在计划有效期内运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <SESSION_SCRATCH>/sync-plan.json`。GarminDB runner 可使用显式指定的全局 Python 或虚拟环境，不要求独立虚拟目录；必须在解释器相邻安装中定位 CLI，并核对固定版本 `garmindb==3.8.0` 与 `garminconnect==0.3.9`。计划同时绑定配置、同目录令牌、解析后的绝对数据根及 `DBs` 目录身份；执行时只把配置与令牌复制到自动删除的临时目录，并把临时配置改写为已绑定的绝对数据根。GarminDB 的配置结束日为开区间，临时配置把用户结束日加一天；3.8.0 CLI 还会用不含当天的天数截断，因此 `sync_health_data.py` 内置有界子进程适配，仅对固定 AST 摘要匹配的 `__get_date_and_days` 非 latest 分支修正当天计数，并核对返回范围与请求完全一致。日期不得在未来，不改变系统时钟或上游安装。v3 短期计划新增适配器所属源文件身份/哈希绑定，旧计划必须重新生成；子进程在执行任何上游代码前核对 CLI 原始字节哈希、方法形状、临时配置摘要、精确窗口与过期时间，失败即停止；运行分成“精确窗口下载”和“仅导入本次新增文件并分析”两个子阶段，禁止全历史重复导入。启动前要重新核对计划有效期、配置、令牌、数据根、临时副本和 runner，子进程以 `python -I -B`、清理环境和关闭 stdin 运行；联网与同步能力绑定精确日期窗口并在启动前各消费一次。计划还绑定解释器与 CLI 身份、可选 `pyvenv.cfg`、完整 site-packages 文件树及固定包元数据。不得从全局 `PATH` 寻找 CLI 或切换备用 API。文件哈希不是签名，也不能抵御同一 Windows 用户下可同时改写技能、计划和 runner 的敌对进程；这类要求必须使用独立服务账号、代码签名/WDAC/AppLocker 或不可变镜像作为外部信任根。同步返回成功后必须用目标数据库指纹和请求窗口的本地覆盖复核，不能只看退出码。默认安装不包含 GarminDB。
   - 用户明确要求启用自动同步时，使用 `scripts/install_auto_sync_task.ps1` 注册当前用户计划任务。默认每日 06:30 同步最近 7 个自然日，`StartWhenAvailable=true`、`MultipleInstances=IgnoreNew`、`RunLevel=Limited`、`LogonType=Interactive`；不保存账户密码，也不唤醒设备。调度动作必须绑定本目录的 `runtime-authority.json` 与 `scripts/garmin_auto_sync.py`，每次重新生成 900 秒短期计划。运行器总预算必须短于任务的物理执行上限，并在获得单例锁后、每个阶段开始前、成功或失败时原子更新脱敏状态；外部终止后遗留的 `running` 状态必须被下一次读取识别为 `interrupted_or_terminated`，不得误报成功。失败不在同一次运行中重试，等待下一日调度或由获授权的新鲜度门启动一次。日记和复盘需要新鲜度同步时，直接运行两阶段同步：先 `sync_health_data.py sync --dry-run` 生成短期计划，再 `sync_health_data.py sync --allow-network --allow-sync` 执行，沿用 7 个自然日窗口并验证终态起止日期、数据库变化和五组件末端覆盖。不经计划任务触发；授权、身份或覆盖验证失败均失败关闭。
   - 自动同步状态只允许保存运行 ID、请求窗口、当前阶段、逐组件观测数量和最近观测日期、运行时绑定哈希、数据库指纹变化布尔值、错误类型及完成时间；不得保存健康数值、令牌、配置内容、本地路径或子进程原始错误正文。只有权威绑定通过、数据库指纹发生变化、五个必需组件的最近观测日期均到达请求末日、且同步后本地重读通过，才允许 `status=success`。注册后检查任务动作、最低权限、下次运行时间和状态文件，并手动启动一次任务完成跨表面验证。

## 研究输出

FHIR 仅提供离线 `FHIR_EXPORT_RESEARCH_ONLY` 包装：输入必须是用户显式指定的本地 JSON，输出必须显式确认 `--acknowledge-research-only`。只支持 HRV 毫秒、静息心率和睡眠时长三个文本编码指标；Provenance 同时区分调用方声明的上游来源摘要和适配器实算的输入 JSON 摘要，可选设备标识只能传 64 位小写十六进制摘要。不使用 LOINC，不生成解释或参考区间，不访问 Garmin 或 FHIR 服务器，也不宣称临床互操作。状态和导出回执必须把 R4 结构、Profile/IG、术语、接收端四道外部门禁标为 `not_performed`。收到外部验证材料后可用 `scripts/fhir_external_acceptance.py` 盘点 Bundle、工具和包摘要及每道门禁；它不运行外部工具、不验证签名，只能检查调用方材料内部一致性。调用方声明的 `passed` 必须降为 `indeterminate`，回执固定保持 `ok=false`、`external_acceptance_established=false` 与 `clinical_interoperability=false`。具体输入与命令读取 `references/advanced_tools.md` 和 `references/external_acceptance.md`。
