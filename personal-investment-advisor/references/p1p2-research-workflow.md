# 显式 P1/P2 研究接线

这是离线研究诊断，不是新的研究框架、策略或交易入口。`complete` 仅指所选组件的结构、数学或描述性比较完成；不表示发布者认证、语义审查、预测有效、Alpha 合格、正式校准或交易就绪。原 P0 已确认条件、局部命中、仓位超限及 Alpha 门保持原路径。

## 原生接口

- `python -B scripts/pia.py edgar-fundamentals MSFT --as-of <日期> --decision-scope research_only --artifact-dir <已授权任务证据根>`：只有另行授权公开抓取时运行；沿用原 SEC 客户端和身份配置，不输出请求头。新增参数是可选的，不改变旧无落盘接口。
- `pia.py fact-prepare --input-file <native fact_prepare_input> --evidence-root <capture evidence_root> --task-dir <任务目录>`：已有捕获字节生成来源绑定数值投影，不下载。
- `pia.py fundamental-diagnostic --input-file <显式输入> --evidence-root <证据根>`：原 brief/math/valuation 门及显式情景/机会成本。`research_lane=fundamental|quantitative` 必填；量化仍转原 Alpha 门，基本面 complete 不充当 Alpha 证据。
- `pia.py expectation-feedback --input-file <显式输入> --evidence-root <证据根>`：原始预期文件 hash/pointer 与 F 实际投影比较；时间、hash、mtime 或调用方 boolean 不是前瞻性信任。仅描述性历史比较，不追加真实 journal，不进入正式收益/校准。
- `pia.py research-workflow --input-file <编排清单> --evidence-root <证据根> --task-dir <新任务目录>`：只连接上述公开 API 和原风险 compute/builders。三个路径均显式；不扫描私域、不自动 fetch。`research-prepare` 的旧四必需参数及事件候选语义不变。

## 编排清单与路径

最薄清单：

```json
{"native_report":"capture-report.json","fundamental_input":"declared-research.json","feedback_input":"declared-feedback.json"}
```

所有清单中的文件引用为**相对显式 evidence_root 的 POSIX 路径**，禁止越界、符号链接/junction。`native_report` 可以是 SEC 原输出或 pia `result` 信封。其 capture evidence_root 必须等于调用方证据根，程序不会猜根。也可直接给 `fact_input`；不要同时提供两者表达冲突选择。`fundamental_input`、`feedback_input` 可独立省略；至少一个分支。预期文件保留原始 `prior_ref`（含 hash/pointer）；省略 `actual_refs` 时程序按 symbol/metric/unit/period/scope 精确选择刚生成的 F 事实，不做别名、财政年度转换或字段造义。M 来源项由程序从 F 自动补齐，不要求用户手写事实 JSON。

为让 J 原始引用与新投影共用同一显式信任根，workflow 的 task_dir 必须位于 evidence_root 内（可相同）；已有 `out/`、`inputs/`、`fact_prepare/` 任一目录则拒绝重跑覆盖。输入不可位于这些输出子树。只新建本任务的投影、输入副本和 out；不修改原捕获、预期、策略、持仓或 journal。失败后选择新的显式任务目录，不以 force 重放。

F 的数值一致性需要原始捕获与映射文件；投影自身不是一手发布原件。PDF 仅 page/span/hash 绑定的未核验候选，不能自动进入数值事实。未知语义与规则不得由程序猜测。

## 可选风险接线

清单 `risk` 接收：`weights_file`、`positions_file`、`confirmed_policy`（根内相对文件），`histories` 和 `fx_histories`（symbol/pair → `{file,source,source_locator,currency}`），以及显式 `base_currency,window_start,window_end,as_of`（带时区）、`annualization_factor=252,annualization_basis`。252 是已有风险方法固定约定，调用方仍须明示交易日年化依据；不是用户权重策略，也不支持在编排层静默改算法。只截取所给窗口，源/hash/币种与实际共同窗口写入回执。

`requests` 为 `diagnostic`、`inverse_vol`、`scenario` 的非空列表；省略时只诊断。部分历史仍保留原 compute 的部分覆盖及未测量声明，不变成全组合风险贡献、风险平价或零风险。生成波动观察使用原 compute 输出与来源元数据，再调用原 inverse-vol builder，不另造数学公式。

正式 builders 另需明确 `bucket_policy` 的 core、satellite、denominator、core_fraction、satellite_fraction、tolerance_fraction 及 positions/policy。缺份额不再回退 80/20，显式 0 不被 `or` 换掉；下游 schema 仍按原规则验证。不得推定现金排除或分母。

情景继续使用原 build_scenario 支持的两情景、CNY/USD 映射与零交易换手合同，须给出两个 `scenario_names`、`main_local_total_returns`、`sensitivity_overrides`、`horizon`、`risk_thresholds`、`no_transactions_no_new_capital=true`，外币必须有原映射支持的明确 FX 冲击。旧 scenario builder 的零份额/零容差 fallback 不在本轮授权修改内：workflow 对该输入报告语义缺口，不悄悄替换。horizon/threshold 是显式声明，仅保留在接线回执，不伪称 builder 已执行阈值批准或期限数学。新含义/未支持币种单列待核验；不得编造成本、概率或折现。情景缺口不阻断可独立的风险诊断/逆波动结果。

## 输出及缺口

`out/research_workflow.json` 保留各组件真实 status、局部结果、源/语义/时间限制及 `gaps`：

- `program_fetchable`：输入/来源资料缺口，不默认要求用户创造 JSON；只能在另有授权的抓取步骤补取。
- `semantic_review_needed`：别名、PDF、模型/输入含义或方法支持边界。
- `rule_confirmation_needed`：窗口/分桶/份额/分母/期限/情景/阈值等未确认规则。
- `provider/error`：物理文件/提供方/依赖故障；保留原类型/状态，不改成 no_data。

`pia.py report --run-dir <任务目录> --out <任务内report.md>` 展示全部独立分支、来源与限制；`readiness` 明确不将研究 complete 升级为交易 ready；`review-pack` 加入真实研究摘要与原始工作流 hash，但不会放宽泳道原来的必需输入或声称已经独立复核。正式校准、订单、真实数据写回均不在本流程内。

验证仅用合成输入；新增测试覆盖 native facade→F→M/J→报告、原 risk/builders、集中缺口、provider 错误保留及越界/覆盖拒绝。离线测试的 socket/sitecustomize guard 不是 OS 防火墙；不据此声称物理隔离。
