# 稳定运行、证据复用与自动化分流

## 原生入口优先

先核对 `pia.py --help`、对应子命令与 `yf.py --help`，复用已有入口，不为一次研究另建同功能流水线：

- 日常核验先用 `pia.py daily-run --positions-file <authorized-file> --task-dir <task> --analysis-scope all|held_only --decision-scope <scope> --plan-only`；执行时移除 `--plan-only`。完整清单用 `all`，仅实仓用 `held_only`，不扩大单一证券、文档摘要或假设权重任务。双轨细节见 [daily-sync.md](daily-sync.md)。
- `--dashboard-root` 与 `--risk-bounds-policy` 分别传入已授权数据源，不从持仓目录或环境变量隐式发现。缺少 Dashboard 根时边界阶段未评估；只算实仓等限定任务可显式 `--skip-watchlist`。`readiness` 和 `ledger` 是请求阶段，执行错误参与最终状态；合法“覆盖未证明”与“尚不可执行”不等于程序失败。
- 复用同一任务的来源快照时使用 `--reuse-artifacts`。只有绑定、身份、完整性及时效仍通过才复用，不重写生成时间、不改时钟、不把旧权重标为当前。
- 事件采集使用 `pia.py collect-evidence`；每个 macro/sector/regulatory scope 只声明一次。额外原件独立保留，不重复同scope参数。通道broken与真实空结果分开。
- 研究证据、ETF产品、Thesis、覆盖和准备度使用现有 build、ETF packet、thesis ledger、coverage及readiness入口。先查实际帮助，再选参数；不得自造CLI接口。
- advisory 本地维护按 SKILL.md 的授权边界单独执行。计算命令仍不写回原始输入，修改数据后必须重新绑定相关证据。

## 缓存与并发

`yf.py --daily-sync` 默认使用一个worker，避免多个独立提供方进程同时初始化同一个任务缓存的SQLite数据库。`--cache-dir` 始终指向任务目录；不要借一次运行更改全局缓存。显式2—4 workers仅在实际环境已验证共享缓存安全时使用，不把并发数量直接等同于效率。

串行模式仍须两个不同标的的系统性失败才能认定多标的提供方中断（单标的任务除外）。单标的异常不自动证明所有标的无数据。FX刷新外围只启动一次 `yf.py` 子进程，由提供方拥有传输重试及截止预算；外围 `attempts` 仅接受1，不叠加新的自动重试。不得因换脚本或换目录重置失败预算。

## FX与行情时点

FX刷新优先绑定真实 `info.regularMarketPrice` 与 `info.regularMarketTime`；两字段齐全时检查有限正值并保留实际带时区时间。字段不足才采用日线Close及其观测日期，明确字段来源。未来观测、非有限值、布尔金额、过期值均失败关闭，不拿抓取时间重标观测时间。72小时FX门和15分钟当前报告龄门不放宽。

盘前／盘后行情使用统一 `pia_quote_observation_v1` 价格／时间绑定，详细选择与降级规则见 [daily-sync.md](daily-sync.md#价格与观测时间绑定)。市场状态变化后，先前regularMarketTime可能不再通过相应上限；不能把市场状态改成CLOSED、复制盘前价格到regular字段或伪造时间戳。若报价门拒绝，当前权重与排序保持未知；已验证旧快照可作为具名参考，独立财务研究继续。下一有效观测到来后再运行，不声明未安排的后台任务。

## 自动化边界与停机条件

机器层自动计算事实、绑定、覆盖、时效、Schema和准备度；解释层分开经营变化、历史用户条件、分析师假设及反证。`pass`、结构有效、缺少反证均不能自动升级为投资价值、用户fatal确认或部署批准。

先输出复核优先项，再输出原生状态、解释标签、时点与缺口。失败仅阻断依赖分支；保持原始失败回执，不用“无数据”掩盖环境错误。输入未知、授权未覆盖、来源无法定位、超过重试预算或必要验证失败时停止相应分支。

## 回归与审计

使用模块方式运行测试，例如在 scripts 目录执行 `python -B -m unittest test_p2_refresh_snapshot test_p2_yf_daily_sync test_p2_daily_run_pipeline`，避免旧测试文件中提前出现的 `unittest.main()` 使直接执行漏跑后续测试类。模块发现不等于覆盖率，测试通过也不代替真实服务验证。

优先检验未来/陈旧观测、缓存权限/并发、绑定漂移、提供方故障、部分覆盖、状态严重度和写入保护。不为导入排序等低风险告警全量重排代码。端到端耗时只能由相同负载的实际回执比较；稳定默认值不宣称必然更快。

模型适配维护可参考 [model-behavior-evaluation.md](model-behavior-evaluation.md)。单次无工具探针不代表正常扩展环境或真实投资工作流已验证，不将其设为每次研究的前置门。
