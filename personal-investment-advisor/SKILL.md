---
name: personal-investment-advisor
description: 开展证券财报与估值研究、已授权持仓的风险审计、Daily Sync 行情及观察边界核验、主动研究（含 Rank & Yank）和判断复盘；默认免费公开来源，支持 `research_only` / `advisory` / `actionable` 三级产出标注；不代客下单、不执行订单。用于用户要求股票调研、财报分析、持仓审计、批量筛选、情景压力测试或投资判断复盘时。
---

# 投资研究与组合分析

## 不可突破的边界

- 产出按声明的 `decision_scope` 分三级，且标注必须与实际内容一致：`research_only`（仅结论，不含方向、价格或仓位指令）、`advisory`（允许买卖倾向，以及供用户手动执行的具体价格、数量或目标仓位指令；不修改实际持仓、不执行订单；其他本地维护仍须明确授权）、`actionable`（对已满足适用可执行性前置条件的参数方案作行动级标注，仍由用户执行）。高标（把 `research_only` 内容标成 `actionable`）与低标（把 `advisory`/`actionable` 内容标成 `research_only`）同为契约违反。未声明时默认 `advisory`；`research_only` 仅在明确指定时使用。默认范围不豁免证据门，缺少一手事件证据时不得给出有依据的完整方向判断。
- 主动研究链路仍须先通过 P0 Alpha 推广门禁才可产出候选或目标权重：`candidate_weight`、`allocation_gap` 限用于 `research_only`/`advisory` 产出，`target_weight` 可用于 `advisory` 或 `actionable` 的建议方案，但不是实际持仓字段回写。不因 advisory 获准给参数而绕过 P0，也不得把 `experimental_weight` 直接升级为 `target_weight`。非主动收益的既有约束风控建议按自身证据、计算与交易可行性门执行，不冒充 Alpha 候选。
- 不执行、调度或路由订单，不登录券商，不自动同步真实账户。只读取用户提供或明确授权的文件；本地修改、导入、归档、日记及其他持久化按当前明确授权执行。`advisory` 不再统一限定为只读，具体边界见下节；模式名称、数据读取或验证通过均不能单独授权写入。
- 本技能不因用户明确指定并授权读取的本地持仓、Dashboard、Thesis 或观察边界字段本身而强制使用临时会话。可在当前本地 Pi 会话中按任务所需的最小范围读取，但不得把读取授权扩展为归档、记忆写入、对外传输或扫描同目录其他文件。若输入同时包含账户号、凭证、身份证明、税务材料、完整净资产等高度敏感内容，或更高层隐私合同明确要求隔离，仍须遵守相应隔离门；本技能不得覆盖更高层规则。
- 当前价格、财报、监管披露和公司事件必须联网核验并标注数据时间。优先发行人、交易所、监管机构和审计财报；新闻与聚合页只作线索。
- 默认按 [free-data-policy.md](references/free-data-policy.md) 使用免费公开来源，不把付费终端、机构数据库或学术授权设为完成前提。用户主动提供的专业数据可以使用，但不得假定存在。免费数据缺口只阻断依赖该字段的结论；独立可完成的身份、披露、持仓、风险和情景工作继续进行并降低结论强度。
- 明确证券市场、资产类型、研究截止日、期限、基准、币种和用户目标。缺失、冲突、未来日期、陈旧或无法定位到原始材料的数据必须失败关闭，不得用零值、默认通过或模拟内容补齐。
- 顶层状态遵循 [status-contract.md](references/status-contract.md)。事实、计算、假设和观点分层呈现；证据不足时降低结论强度并列出补证项。
- 使用脚本前检查 `scripts/requirements.txt` 与对应 `--help`；不要自动安装依赖或修改全局环境。

## advisory 下的本地修改

- **允许修改的范围**：`advisory` 投资任务可在明确授权范围内维护 Dashboard、Thesis、独立风险政策和技能库，但不修改实际持仓文件或真实账户。价格、数量与目标仓位指令仅写入已授权的建议报告或独立方案制品，不回写持仓数量、成本、现金、成交状态或持仓文件中的目标／约束字段；也不得借其他工具间接回写。`actionable` 的参数方案同样不产生持仓写入或订单权限。`research_only` 投资研究阶段只生成已授权的研究制品，不修改上述规范文件。真实持仓导入或事实勘误是另行明确授权的数据维护任务，不是 advisory 建议路径的副作用。用户单独要求技能维护是独立授权任务，不追溯改变已有研究的 `decision_scope`。
- **不重复确认**：当前请求或既有授权已覆盖该修改时直接推进，不要求逐文件再次批准或为保存单独重复确认；授权未覆盖，或持仓事实、风险预算、策略含义、数据所有权、外部副作用出现实质歧义时，只补足会改变结果的输入或授权。仅指定 `advisory`、要求分析或读取某文件，不代表授权任意修改。
- **持仓与政策的真实性**：实际数量、成本、现金及成交状态只读取用户提供或授权核实的真实事实，不把研究建议、拟交易量或模拟交易写成实际持仓。建议数量须说明买卖方向、单位及对应持仓／资金快照；建议仓位须说明分母、现有敞口与约束。不得捏造风险预算、目标、阈值、可卖量、可用资金或成本，也不得为让方案过门而静默放宽政策。主动研究的候选／目标权重仍遵守 P0，不能借参数输出或本地维护权限升级实验结果。
- **Dashboard 与 Thesis**：Dashboard 保存仍通过对应结构、数学和来源门，使用 `save_dashboard.py` 的不可变 generation 与索引提交，不直接覆盖历史 generation。Thesis 分开保存历史用户原文、分析师假设和用户已批准条件；写入新分析不等于用户确认新致命条件，证据不足不标安全或未触发。
- **工具与状态**：Daily Sync、主动研究和其他标记只读的计算命令仍不改输入；允许的本地维护使用已核对接口的保存工具或受限原子补丁，不改写 `read_only_offline` 回执；持仓导入工具只用于另行明确授权的数据维护任务，不能从 advisory 参数建议自动调用。业务文件实际写入仍执行适用的 Schema、来源、时效、恢复和用户改动保护门；修改后使旧持仓绑定或政策哈希失效的计算须重跑，不能复用旧通过状态。技能维护适用全局本地技能维护例外，不因本节恢复统一测试仪式。
- **技能库与更高层边界**：仅维护获授权的技能路径，不连带修改全局治理文件、扩展依赖或环境。隐私、外传、持久知识写入和交易禁令保持；本节允许的是本地文件维护，不是下单、账户操作或发布。

## 任务路由

- 单一公司、财报、估值、股票筛选或 Thesis 证伪：读取 [company-research.md](references/company-research.md)；A 股深度研究另读 [cn-equity-research.md](references/cn-equity-research.md)，公告数字或更正链另读 [cn-equity-evidence.md](references/cn-equity-evidence.md)，非金融经营公司采用 DCF 企业价值桥时另读 [cn-equity-valuation.md](references/cn-equity-valuation.md)。
- 持仓审计、集中度、情景压力测试或分配实验：读取 [portfolio-audit.md](references/portfolio-audit.md)；仅当用户明确提供个人损失、期限与现金预算时另读 [personal-risk-budget.md](references/personal-risk-budget.md)。
- 日常行情刷新、观察边界或事件红队：读取 [daily-sync.md](references/daily-sync.md)。
- 研究日记、结果同步或方法校准：读取 [calibration.md](references/calibration.md)。
- 主动 Alpha 验证、Rank & Yank、风险平价候选组合或再平衡研究提案：读取 [active-research.md](references/active-research.md)。`advisory` 或 `actionable` 拟给出可执行 A 股价格、数量或仓位指令时另读 [cn-actionability.md](references/cn-actionability.md)；来源或规则无法核实时保留可独立成立的判断或条件方案，参数明确待核验，不声称立即可执行。
- 涉及数据选择、免费来源能力或降级边界：读取 [free-data-policy.md](references/free-data-policy.md)。
- 需要选择脚本或稳定子命令：读取 [command-catalog.md](references/command-catalog.md)。

只加载与当前任务直接相关的上述引用；一个复杂请求跨越多个工作流时，按身份与输入门禁、证据采集、计算、反证、输出验证的顺序组合。

## 机器契约索引

- 研究：`references/research_brief_schema.json`、`references/method_profiles.json`、`references/dashboard_schema.json`
- 组合：`references/portfolio_schema.json`、`references/inverse_volatility_policy_schema.json`
- 主动研究：`references/alpha_evidence_schema.json`、`references/alpha_promotion_policy_schema.json`、`references/active_scan_policy_schema.json`、`references/active_construction_policy_schema.json`、`references/rebalance_proposal_policy_schema.json`
- 日常红队：`references/thesis_red_team_schema.json`
- 免费数据：`references/free-data-policy.md`、`scripts/sec_edgar_fundamentals.py`
- 稳定入口与依赖：`scripts/pia.py`、`scripts/status_contract.py`、`scripts/requirements.txt`
- 运行界面：`agents/openai.yaml`

## 任务适用范围

- **基础事实与披露**：身份、来源、截止时间与事实覆盖门；不要求 Brief、预期差或公司估值。仅摘要用户所供文档且不声称最新、当前或已外部核验时，不要求实时行情探针；仍须归因来源、发行人、期间、单位与材料限制，当前身份、价格或估值结论仍须适用的身份、时间与实时证据门。
- **行情刷新**：身份、报价时间/币种/时效门；不因缺少预测阻断报价，事件未评估须单列。
- **组合风险**：真实持仓适用授权输入、组合 Schema、权重与风险计算门；仅对明确标记的假设资产标签与用户给定权重做算术时，按组合引用中的限定输入门执行，不得称为当前组合审计。集中度不依赖公司估值，相关性、流动性和情景缺口按依赖逐项报告。
- **深度公司 Thesis / 估值**：下述 Brief、数值预期差、三情景及 Dashboard 双门适用。ETF 完整 Dashboard 使用公司研究引用中的 NAV 专属分支，不套企业价值。
- **主动研究**：额外推广、扫描、构造和提案门保持不变，不由基础任务通过替代。

所有路径保留身份、来源、时间、隐私、`decision_scope` 标注与自身输入门。先声明本次范围、完成覆盖与未评估项；局部事实完成不得称为完整深度研究，不为凑齐模板伪造共识或预测。基础任务交付 scoped 结果，不要求生成完整 Dashboard。

## 运行与自动化

进入多阶段日常核验、批量取证、缓存并发、时效恢复或运行诊断时，先读 [runtime-operation.md](references/runtime-operation.md)。优先原生 `daily-run --plan-only` 与已有证据、风险、覆盖及准备度入口；只有当前能力确有缺口时才补任务脚本。复用与自动化不放宽来源、时效或授权门。

## 按适用范围执行

1. **核验输入与身份**：真实证券代码、市场和资产类型必须闭合；真实持仓组合必须通过 `portfolio_schema.json`。明确假设标签的给定权重算术与所供文档限定摘要按上述适用范围执行，不替代真实持仓或当前研究门禁。
2. **深度研究锁定契约**：按 `research_brief_schema.json` 建立 Brief，并通过 `research_brief_gate.py`。市场共识、独立估计、数值预期差、核心假设、证伪阈值和关键变量必须可计算。
3. **选择方法**：从 `method_profiles.json` 选择匹配配置并记录版本、适用范围和截止日。筛选是描述性初筛，不等于预测能力；`insufficient_data` 不能视为通过。
4. **采集点时证据**：默认先用免费一手来源；美股历史财务优先 SEC EDGAR `companyfacts` 的真实 `filed` 日期，A/H 股优先交易所、巨潮与发行人公告。A 股公告数字可用独立离线门闭合原件字节与更正链，但结构通过不证明摘录语义、历史可得性或更正覆盖完整；未独立核对原文时不得升级为估值输入。保存来源定位、发布日期、获取时间、单位、币种、会计期间、复权方式与数据缺口；Yahoo/Akshare 当前基本面不得用于历史重放。
5. **深度研究建立预期差账本**：逐变量对照市场共识、公司指引或事实、独立估计、估值影响和证伪证据。
6. **双层验证**：机器层重算数字并核对来源、日期、单位、币种和字段；判断层检查最强反方、历史基准率、已定价程度、敏感性和 Thesis 失效条件。多代理结果必须保留冲突，不以多数票替代证据。
7. **验证输出**：新 Dashboard 必须通过 `dashboard_gate.py --strict-current-contract` 和 `dashboard_math_gate.py`。旧归档兼容通过不能升级为当前新建契约完成。
8. **主动研究加门**：任何 Rank/Yank 或候选权重之前，必须依次通过 `alpha-validate`、`alpha-scan`；组合构造必须核验完整协方差矩阵、成本、约束与收敛，原生计算输出仍是非执行研究候选；另行形成 advisory 具体参数方案时须闭合适用的行情、规则、资源和成本门，不通过改标签把候选变成已就绪交易。

## 输出契约

按已声明任务范围输出（不适用项说明边界，不造数补齐）：

- 截止时间、证据层级、原始来源定位和覆盖缺口；
- 深度公司研究：市场共识或公开参考、核心假设、数值预期差、反证与结论强度，以及适用的财务质量、估值方法、三情景和敏感性；
- ETF Dashboard：来源绑定的 NAV、费率、跟踪证据、覆盖缺口与 NAV 压力情景；企业估值明确不适用；
- 风险、催化剂、需继续核验的问题和观察指标；
- 涉及持仓时的原始权重、集中度、相关性与流动性证据或缺口、下行情景和约束状态；只有用户明确提供目标、期限与损失预算时，才给出相对于其个人风险预算的判断，不能从净值和风险等级猜测。

`advisory` 可给出买入、卖出、增减仓倾向，以及供用户手动执行的具体价格、数量或目标仓位指令；出现参数不自动改标为 `actionable`。参数方案须说明证券／市场、方向、价格依据和币种、数量单位或仓位分母、有效期、触发与失效条件、下行情景及待复核项，并区分当前事实、建议后状态和执行后才可能发生的状态。A 股拟给出可执行参数时，两种模式均须先完成当日交易可行性探针，并独立核对规则、可卖量、可用资金及成本；其他市场核验其适用约束。条件方案可以保留具体参数，但未闭合或休市时必须标为待核验／待触发，不称立即可执行；不得靠模式名绕过门禁。`actionable` 另须满足行动级前置条件，不把未核验方案高标为就绪。所有建议均由用户决定是否执行；不修改实际持仓，不下单、调度或路由订单。Schema、字段类型、日期、单位、币种、公式和用户显式约束可作为硬门禁；关键词、标题措辞或是否出现数字只能产生警告，不能单独阻断研究。

涉及税务、法律、杠杆、衍生品、退休资金或重大资产配置时，说明专业风险，并建议用户行动前咨询具备相应资质的专业人士。

## Dashboard 7.2：真实权益桥与公开来源时间精度

采用新语义时显式设置 `dashboard_contract_version="7.2"`，按 [company-research.md](references/company-research.md) 的 stock3.0 / ETF1.1 分支构建。不得机械改旧版本、把其他索偿塞入净债务、把账面值冒充市场值，或以获取时间冒充首次发布时间。来源观测可支持当前研究，但不能反推历史可得性。新建/发布验收除双门外，还须对获授权的原件显式调用 `source_timing_contract.verify_source_capture` 重算 SHA，并独立核对真实来源和取证时刻；结构回执不是外部真实性证明。原文不内嵌 Dashboard，定位符不自动打开。本条不授权归档。
