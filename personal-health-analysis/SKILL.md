---
name: personal-health-analysis
description: 以本地优先、失败关闭方式分析用户授权的 Garmin 睡眠、HRV、心率、压力、身体电量及数据质量，并生成 Markdown 报告或零外联 HTML 趋势面板。用于“分析睡眠”“查看 HRV/心率/压力”“评估身体状态”“生成健康报告或趋势图”等请求；实时访问、同步和活动文件下载必须取得本次明确授权，仅提供非诊断性健康信息。
---

# Garmin 健康数据分析

## 环境与授权

- 默认只读取 Garmin 本地数据库；本地分析不要求登录，也不得因本地失败而回退到云端。
- 实时查询、认证、同步或活动文件下载需要可用账户授权，并须在本次请求中明确允许联网。读取健康数据还要单独允许 `--allow-health-data` 并给出精确指标与日期窗口；登录写入令牌需 `--allow-token-write`；活动原始文件落盘还需 `--allow-download`。这些授权不能互相替代。
- 不在分析任务中自动安装依赖。只有用户明确要求安装时才运行 `install.ps1 -Offline -Wheelhouse <DIR>` 或 `install.sh --offline --wheelhouse <DIR>`；一步式在线安装已禁用。两者先在目标同级暂存目录构建隔离 `.venv`，校验成功后才发布，目标路径必须尚不存在。安装必须使用传递依赖已固定的 `requirements.lock.txt`，在创建环境前及安装后校验 `wheelhouse-manifest.json` 的平台、Python、锁文件及全部纯 Wheel SHA-256，并让 pip 使用隔离模式、逐发行包哈希、`--require-hashes --only-binary=:all: --no-index --disable-pip-version-check`；安装集合只能包含锁定包及 venv 自带的 pip/setuptools。不得接受 sdist、空缓存或复用旧环境。清单哈希证明与已审核本地字节一致，不等于发布者签名。
- 后续命令中的 `<SKILL_PYTHON>` 必须解析为该隔离环境的解释器：Windows 为 `<SKILL_ROOT>/.venv/Scripts/python.exe`，POSIX 为 `<SKILL_ROOT>/.venv/bin/python`。不得用未核验的全局 `python` 替代。
- 先确认用户允许读取相关健康数据和时间范围。不要扩大到未请求的指标、活动轨迹或历史周期。
- 需要指标解释时按需读取 `references/health_analysis.md`；只有用户授权实时访问时才读取 `references/api.md`，使用扩展指标、时间点查询或活动文件时读取 `references/advanced_tools.md`；准备真实链路或外部 FHIR 验收时读取 `references/external_acceptance.md`。`resources/clinical_guidelines.json` 只是可选方法配置，不是临床事实库；配置未启用、参数越界或来源元数据不可验证时，只做未分类观察。
- 安全关键入口包括 `scripts/wheelhouse_integrity.py`、`scripts/garmin_capabilities.py`、`scripts/garmin_auth.py`、`scripts/garmin_sqlite_adapter.py`、`scripts/garmin_data_extended.py`、`scripts/garmin_query.py`、`scripts/garmin_activity_files.py`、`scripts/sync_health_data.py`、`scripts/garmin_fhir_adapter.py` 和 `scripts/fhir_external_acceptance.py`；离线面板模板为 `assets/dashboard_v2.html`，技能发现元数据为 `agents/openai.yaml`。资源清单只说明文件已声明，不能替代授权门禁、内容哈希核验和离线测试。

## 工作流程

1. 明确问题、时间范围和期望输出：单项指标、日度摘要、趋势分析或图表。
2. 默认使用本地、只读、失败关闭路径：
   - 单项或汇总：`<SKILL_PYTHON> scripts/garmin_data.py <sleep|hrv|heart_rate|body_battery|stress|summary> --days <N> --source local`
   - 描述性准备度或基线变化：`<SKILL_PYTHON> scripts/garmin_intelligence.py <readiness|baseline_change|insight_cn> --days <N> --source local`
   - 趋势面板：`<SKILL_PYTHON> scripts/garmin_chart.py dashboard --days <N> --source local --output <HTML_PATH>`
   - `--days N` 表示截至本地当前日、首尾包含的 N 个自然日；`--period` 只接受正整数天数或 `YTD`，且 `YTD` 包含 1 月 1 日与当前日。非法、零值或负值不得静默改写。报告必须回显实际起止日期、数据日期和每项覆盖率。
3. 在 Windows 控制台乱码时设置 `PYTHONIOENCODING=utf-8`。不要自动安装依赖、登录账户或修改数据库。
4. 检查数据采集时间、缺失率、设备佩戴空档和脚本错误。本地单项、汇总、洞察及面板必须在数据库前后 SHA-256、Schema、WAL/SHM 均未变化的验证读取窗口内完成；结果只披露数据库名和摘要。覆盖状态按实际非空观测区分 `complete`、`partial` 与 `no_data`；SQL、Schema 或读取窗口错误必须以非零退出和机器可读 `read_error` 失败关闭。缺失聚合必须保持 `null`，不得变成生理值 0。
5. 仅在用户本次明确授权时使用实时路径：必须同时传入 `--source live --allow-network --allow-health-data`，并显式给出 `--days` 或 `--start/--end`。实时 `summary` 与面板固定读取 sleep、hrv、body_battery、heart_rate、activities、stress、training_load_series 七项；不读取 Profile、体成分、补水、Fitness Age 或设备闹钟。实时洞察按分析用途进一步缩小组件；`long_term_load` 和 `device_audit` 没有可满足契约的实时来源，必须在客户端初始化前返回 `LIVE_ANALYSIS_NOT_SUPPORTED`。点时查询还必须显式给出日期、IANA 时区和最大容差。能力对象绑定绝对起止日期与组件清单，健康数据与下载能力仅能消费一次；不得直接调用 `get_client()` 绕过 CLI 门禁。
6. 只有用户明确要求同步后，才执行两阶段同步：先运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --dry-run --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-output <SESSION_SCRATCH>/sync-plan.json` 生成短期计划；核对范围和绑定摘要后，再在计划有效期内运行 `<SKILL_PYTHON> scripts/sync_health_data.py sync --start <YYYY-MM-DD> --end <YYYY-MM-DD> --allow-network --allow-sync --config-dir <TRUSTED_CONFIG_DIR> --garmindb-python <TRUSTED_GARMINDB_PYTHON> --plan-file <SESSION_SCRATCH>/sync-plan.json`。启动前要重新核对计划有效期、配置、临时配置和 runner，子进程以 `python -I -B`、清理环境和关闭 stdin 运行；联网与同步能力绑定精确日期窗口并在启动前各消费一次。计划绑定配置摘要、解释器与 CLI 身份、`pyvenv.cfg`、完整 site-packages 文件树及固定包元数据。不得从全局 `PATH` 寻找 CLI 或切换备用 API。文件哈希不是签名，也不能抵御同一 Windows 用户下可同时改写技能、计划和 runner 的敌对进程；这类要求必须使用独立服务账号、代码签名/WDAC/AppLocker 或不可变镜像作为外部信任根。默认安装不包含 GarminDB。
7. 将观察值、可能解释和不能判断的事项分开。`baseline_change` 只描述相对个人基线的变化，不对应疾病风险；覆盖不足、日期未对齐、基线少于 21 个同日样本、零方差或跨已知设备/固件/分析算法时期时不分类。`readiness` 在没有启用且可追踪的配置时不生成分数。任何脚本结果都不得决定训练、补剂、日程或重要决策。
8. 仅在指标多、周期长且任务可独立拆分时使用子代理；传递最小化、去标识的数据。未经用户许可不得把健康数据发送给外部服务。
9. 用户要求生成持久化报告或面板时，先运行 `<SKILL_PYTHON> scripts/report_output.py --days <N>`，取得同一批次的 `markdown` 和 `html` 绝对路径。
10. 将最终 Markdown 正文写入返回的 `markdown` 路径；生成面板时把返回的 `html` 路径传给 `garmin_chart.py --output <HTML_PATH>`。默认拒绝覆盖现有文件；只有用户明确要求替换时才使用对应覆盖参数。

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
- 可能解释与证据限制
- 可选的一般性恢复或训练考虑事项，由用户结合主观感受和专业意见决定
- 需要升级处理的风险
- 持久化任务的 Markdown 与 HTML 绝对路径

FHIR 仅提供离线 `FHIR_EXPORT_RESEARCH_ONLY` 包装：输入必须是用户显式指定的本地 JSON，输出必须显式确认 `--acknowledge-research-only`。只支持 HRV 毫秒、静息心率和睡眠时长三个文本编码指标；Provenance 同时区分调用方声明的上游来源摘要和适配器实算的输入 JSON 摘要，可选设备标识只能传 64 位小写十六进制摘要。不使用 LOINC，不生成解释或参考区间，不访问 Garmin 或 FHIR 服务器，也不宣称临床互操作。状态和导出回执必须把 R4 结构、Profile/IG、术语、接收端四道外部门禁标为 `not_performed`。收到外部验证材料后可用 `scripts/fhir_external_acceptance.py` 盘点 Bundle、工具和包摘要及每道门禁；它不运行外部工具、不验证签名，只能检查调用方材料内部一致性。调用方声明的 `passed` 必须降为 `indeterminate`，回执固定保持 `ok=false`、`external_acceptance_established=false` 与 `clinical_interoperability=false`。具体输入与命令读取 `references/advanced_tools.md` 和 `references/external_acceptance.md`。

避免伪精确评分。比较个人基线时说明基线窗口和算法；没有足够历史数据时，不给出趋势结论。不得推荐药物、补剂或剂量，不得要求强制训练、停止训练、取消会议、修改闹钟或禁止决策。

## 医疗安全边界

- 不诊断、不开药、不调整处方，也不把穿戴设备数据称为临床级证据。
- 不根据消费级设备分数推断感染、炎症、免疫状态、认知能力或职业表现；评分与分区只能作为明确标注方法和来源的实验性描述。
- 出现胸痛、严重呼吸困难、晕厥、疑似中风、持续极端心率或用户描述的其他急症信号时，停止常规分析并建议立即联系当地急救服务。
- 对持续异常、明显症状或影响生活的变化，建议咨询合格医疗人员，并携带原始数据。
- 不自动保存、同步或注册健康洞察。长期存储或共享必须说明数据、目的和目标位置，并取得明确授权。
