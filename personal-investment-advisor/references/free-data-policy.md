# 个人投资者免费数据政策

## 定位

本技能面向个人投资者，默认只使用无需付费终端、机构订阅或学术授权的公开数据。不得把 Wind、Bloomberg、Refinitiv、FactSet、Compustat、CRSP 或类似专业数据库设为完成任务的默认前提，也不得暗示用户必须购买数据。

用户主动提供且有权使用的付费数据可以作为 `user_authorized` 证据，但不能取代来源、时点、字段含义和哈希核验。

## 免费来源优先级

| 用途 | 首选免费来源 | 使用边界 |
| --- | --- | --- |
| 美股身份、财报及披露时点 | SEC EDGAR `submissions`、`companyfacts`、原始 filing | 使用真实 `filed`/accepted 时间；XBRL 标签须记录并允许发行人差异 |
| A/H 股身份与披露 | 上交所、深交所、港交所、巨潮资讯、发行人官网 | Akshare/Efinance 只作结构化辅助；关键结论回查官方披露 |
| 当前行情与历史价格 | Yahoo Finance/yfinance；A 股可用 Akshare | 属于免费聚合数据；记录获取时间、市场状态、复权方式和缺口 |
| ETF 公司行动与分红 | 发行人、基金官网、交易所；Yahoo 历史作交叉核对 | 未通过 `history_integrity_gate.py` 不生成历史衍生指标 |
| 汇率 | Yahoo Finance 公共 chart 序列 | 必须记录货币对、观测日期、定位、获取时间和内容哈希 |
| 交易成本 | 用户券商公开费率页、公开收费表或用户提供合同 | 缺少点差、冲击或税费时保持未知，不用零值冒充 |
| 指数成分 | 指数公司公开页面、公开调整公告 | 当前成分不能回填为历史成分；公开调整记录不完整时声明幸存者偏差未控制 |

## 数据降级规则

1. **当前快照不等于点时历史**：yfinance/Akshare 当前基本面只能用于当前描述性筛选，不得历史重放。
2. **SEC EDGAR 可解决美股披露时点，不自动解决幸存者偏差**：`companyfacts` 提供 as-reported 事实与 `filed` 日期，但不提供完整历史指数成员及退市总回报。
3. **免费复权序列不是无条件真值**：只有身份、公司行动和序列绑定闭合时，才可声明 `corporate_action_adjusted=true`。
4. **缺少专业字段不阻断无关工作**：无法取得 ADV、市场冲击、卖方一致预期或历史退市回报时，相关结论标为 `not_calculated`、`not_assessed` 或 `experimental_only`；身份核验、财报阅读、持仓集中度、公开情景压力测试等独立部分仍可继续。
5. **不为通过门禁而补造**：免费数据不能证明幸存者偏差控制、公司行动调整或点时可得性时，布尔字段必须如实为 `false`。Alpha 包仍可计算实验指标，但不得推广到 Rank/Yank 或主动候选权重。

## SEC 快照截止与衍生指标口径

- `--as-of YYYY-MM-DD` 保留日级截止，按已获取事实的 `filed <= as_of` 筛选。UTC 当日可用，但只表示获取时已有的数据，不保证当日披露齐全；`cutoff_day_complete=false`，`availability_granularity=filed_date`。
- 带时区 datetime 先换算到 UTC，仅纳入 `filed` 早于截止 UTC 日期的事实。同日披露全部排除，`availability_granularity=filed_date_before_cutoff_day`；不伪造 accepted 时间，也不声称盘中披露完整。未来日期或时刻仍拒绝。
- 原始选中事实保留单位与期间。每项衍生指标独立核验；不闭合时省略该指标，在 `unavailable_derivations` 说明原因，并返回 `insufficient_evidence`。无关且已闭合的衍生指标仍可计算。
- `net_income_to_period_end_equity` 要求净利润与年度期末权益币种相同、期末相同，权益来自年度表单；它不是使用平均权益的标准 ROE。现金流每稀释股要求年度起止日期相同、现金流为货币单位、股数为 `shares`；`derived_units` 标记比率或每股币种。
- 迁移：`parse_as_of` 对纯日期返回 `date`，对带时区输入返回 `datetime`；JSON `as_of` 不再将纯日期伪装成日末时间。新消费者改读 `net_income_to_period_end_equity`，不得把旧 `roe` 直接当作标准 ROE。历史制品不重写；需要新口径时从授权原始事实重新计算。

## Provider 稳定性与迁移（STAGE3A）

- `provider_runtime.py` 是 Akshare/Efinance、`yf.py` 与 `quality_screener.py` 的单一进程与重试所有者。每次补充指标调用默认 8 秒；历史、报价元数据、新闻、搜索或财报调用默认 30 秒。沿用原补充接口的 8 秒及搜索接口的 10 秒 × 3 次量级，不代表服务 SLA。Python 调用可传入 `timeout_seconds`；Fetcher 支持 `supplement_seconds` 与 `operation_seconds`。不改第三方内部重试设置。
- 截止时间使用单调时钟，包含进程启动、导入、调用、子进程序列化和退避；Akshare 的请求间隔等待也扣除预算。超时终止自有进程，`terminate/join` 和必要的 `kill/join` 各最多等待 1 秒。正常操作的壁钟验收为预算加这 2 秒及操作系统调度、临时存储与反序列化开销；不能保证内核故障、进程创建或文件系统卡死时的硬实时上限。清理失败单列错误，不能返回无数据。
- 每个操作最多启动 3 次自有进程，永久、权限、参数和编程错误不重试；仅已识别的连接、超时、限流或可重试 HTTP 状态重试，退避为 1.5 秒、2.25 秒且不得越过剩余预算。`attempts` 统计进程尝试，启动失败可能尚未调用提供方；`attempt_scope` 明示第三方内部 HTTP 调用次数未知。禁止在自有子进程中再调用该运行时。
- 独立操作预算相加，不把每标的或整个 CLI 宣称为 30 秒：完整 Yahoo 研究可包含解析、历史、元数据和新闻；A 股增强包含报价与可选筹码两个操作。Daily Sync 每标的只有一个元数据操作，默认 2 个协调线程、最多 4 个，每个线程只等待可终止子进程，不用线程超时冒充取消。输出按首次输入顺序去重排列，已有熔断与元数据复用规则保留。
- `auto` 历史仅在真实空表时尝试 Yahoo，并共享历史操作的剩余时间与总计 3 次尝试；Akshare 硬失败不再被 Yahoo 成功掩盖。瞬态重试后才返回空表时，也扣除已经消耗的全部尝试；预算耗尽仅跳过备用来源并保留真实 `no_data`，不伪造超时异常。`yf.py` 请求的历史为空时返回 `insufficient_data` 和非零退出码，不当作完成或操作异常。解析中的硬失败不再静默转成“找不到证券”。
- 迁移：`_run_isolated_provider` 原来把启动失败、EOF、超时、提供方异常和非表格返回都折叠为空表；现在返回 `ok/no_data/error/timeout` outcome。`require_data` 仅对真实数据或真实空结果返回值，对操作失败抛出带 outcome 的 `ProviderError`。异常保留原生类别、模块、错误码及脱敏后的错误文本和 traceback 帧，不返回原始提供方 stdout/stderr。`quality_screener.fetch_yf_data` 仅返回 `(income, cashflow, balance)`，删除唯一消费者原本丢弃的 live Ticker 项；财报空表是证据不足，不再重试或伪装成提供方异常。
- A 股增强的必需指标是 `volume_ratio`、`turnover_rate`，未跳过筹码时另需 `profit_ratio`、`avg_cost`、`concentration`。振幅、市值、筹码区间、板块字段为可选，缺失仍列出。`evidence_status` 单独描述必需字段覆盖；`provider_outcomes` 保留每个请求的操作状态。任一已请求提供方硬失败时，`enhancement_status=error`、独立 CLI `status=data_error` 且退出 2；另一来源的有效部分保留，不能将失败升级为 `complete`。`yf.py` 同步错误到 `errors` 与非零退出码。
- 诊断文本与 `provider_code` 共用脱敏器：仅扫描前 4096 个字符，输出最多 500 个字符；识别 Authorization、token、password、secret、api_key（含 api-key、apikey）赋值及带引号的键。遇到敏感键后保守删除整个剩余文本，不依赖值的空格、换行、引号或转义边界，因此后续非敏感上下文也可能被省略。无法转换的异常不回退到 `repr`，非标量诊断值直接省略。保留异常类别、模块、errno 和无局部变量的 traceback 文件名、行号、函数名；HTTP 状态依次取 `response.status_code`、`status_code`、`status` 中首个有效的 100–599 整数或三位数字字符串，分类与输出共用该结果。这不是任意秘密检测器，不保证识别无标签凭证、编码后的键或未列出的敏感键。
- IPC 是父进程新建私有外部临时目录中的一次性传输，不是授权归档或缓存。为保留 DataFrame 类型、索引和 attrs，仅读取已退出自有子进程写入的固定结果文件；不接受外部路径或字节，不跟随符号链接或 Windows reparse point。子进程写入和父进程读取均限制为 32 MiB，截断、畸形、超限或磁盘错误均为操作错误；成功、失败、超时均清理临时目录。pickle 只适用于该受信本地进程边界，不是处理用户上传文件的接口。它不隔离同账户恶意代码，也不保证提供方内部再次创建的后代进程可被清理；当前适配器不创建后代。
- 未联网验证第三方服务可用性。第三方库若内部吞掉传输异常后自行返回空表，该内部真实性缺口无法由外层空表推断修复；历史调用使用已安装 yfinance 支持的 `raise_errors=True`。不据此声称控制了第三方内部请求次数、内存或所有失败语义。`research_only`、无交易指令和逐项持久化授权均不改变。

## 免费模式可完成的任务

- 当前行情、证券身份、财报与原始披露研究；
- SEC EDGAR 点时年度财务快照与透明的历史实验；
- 当前持仓权重、集中度、汇率换算和显式情景压力测试；
- 使用免费总回报历史的波动率、相关性和 PSD 协方差诊断；
- 不依赖 Alpha 的 `experimental_weight` 分配实验。

严格 Alpha 推广仍要求完整点时证据、公司行动调整和幸存者偏差控制。免费来源无法闭合时，输出实验结果和缺口，不推荐付费数据作为默认下一步。
