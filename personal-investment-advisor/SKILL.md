---
name: personal-investment-advisor
description: 面向个人投资者，默认使用 SEC EDGAR、交易所与发行人披露、Yahoo Finance、Akshare 等免费公开来源，结合用户明确提供的持仓，执行证券身份核验、财报研究、估值情景、组合风险审计、主动机会验证和研究复盘。用于“股票调研”“分析财报”“持仓审计”“批量筛选”“情景压力测试”“主动收益研究”“Rank & Yank”“复盘投资判断”等请求；仅输出 research_only 研究支持，不生成交易指令，也不替代持牌投资、税务或法律意见。
---

# 投资研究与组合分析

## 不可突破的边界

- 所有研究、Dashboard、组合分析和分配实验固定为 `research_only`。不得生成进出场、止损止盈、订单或可直接执行的交易指令。只有通过 P0 Alpha 推广门禁的主动研究链路，才可输出明确标记、不可执行的 `candidate_weight` 与 `allocation_gap`；不得称为 `target_weight`，不得据此声称需要买卖。
- 不执行订单、不登录券商、不自动同步账户或改变组合。只读取用户提供或明确授权的持仓文件；导入、归档、日记及其他持久化需逐项获得授权。
- 当前价格、财报、监管披露和公司事件必须联网核验并标注数据时间。优先发行人、交易所、监管机构和审计财报；新闻与聚合页只作线索。
- 默认按 [free-data-policy.md](references/free-data-policy.md) 使用免费公开来源，不把付费终端、机构数据库或学术授权设为完成前提。用户主动提供的专业数据可以使用，但不得假定存在。免费数据缺口只阻断依赖该字段的结论；独立可完成的身份、披露、持仓、风险和情景工作继续进行并降低结论强度。
- 明确证券市场、资产类型、研究截止日、期限、基准、币种和用户目标。缺失、冲突、未来日期、陈旧或无法定位到原始材料的数据必须失败关闭，不得用零值、默认通过或模拟内容补齐。
- 顶层状态遵循 [status-contract.md](references/status-contract.md)。事实、计算、假设和观点分层呈现；证据不足时降低结论强度并列出补证项。
- 使用脚本前检查 `scripts/requirements.txt` 与对应 `--help`；不要自动安装依赖或修改全局环境。

## 任务路由

- 单一公司、财报、估值、股票筛选或 Thesis 证伪：读取 [company-research.md](references/company-research.md)。
- 持仓审计、集中度、情景压力测试或分配实验：读取 [portfolio-audit.md](references/portfolio-audit.md)。
- 日常行情刷新、观察边界或事件红队：读取 [daily-sync.md](references/daily-sync.md)。
- 研究日记、结果同步或方法校准：读取 [calibration.md](references/calibration.md)。
- 主动 Alpha 验证、Rank & Yank、风险平价候选组合或再平衡研究提案：读取 [active-research.md](references/active-research.md)。
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

## 通用执行顺序

1. **核验输入与身份**：证券代码、市场和资产类型必须闭合；组合必须通过 `portfolio_schema.json`。
2. **锁定研究契约**：按 `research_brief_schema.json` 建立 Brief，并通过 `research_brief_gate.py`。市场共识、独立估计、数值预期差、核心假设、证伪阈值和关键变量必须可计算。
3. **选择方法**：从 `method_profiles.json` 选择匹配配置并记录版本、适用范围和截止日。筛选是描述性初筛，不等于预测能力；`insufficient_data` 不能视为通过。
4. **采集点时证据**：默认先用免费一手来源；美股历史财务优先 SEC EDGAR `companyfacts` 的真实 `filed` 日期，A/H 股优先交易所、巨潮与发行人公告。保存来源定位、发布日期、获取时间、单位、币种、会计期间、复权方式与数据缺口；Yahoo/Akshare 当前基本面不得用于历史重放。
5. **建立预期差账本**：逐变量对照市场共识、公司指引或事实、独立估计、估值影响和证伪证据。
6. **双层验证**：机器层重算数字并核对来源、日期、单位、币种和字段；判断层检查最强反方、历史基准率、已定价程度、敏感性和 Thesis 失效条件。多代理结果必须保留冲突，不以多数票替代证据。
7. **验证输出**：新 Dashboard 必须通过 `dashboard_gate.py --strict-current-contract` 和 `dashboard_math_gate.py`。旧归档兼容通过不能升级为当前新建契约完成。
8. **主动研究加门**：任何 Rank/Yank 或候选权重之前，必须依次通过 `alpha-validate`、`alpha-scan`；组合构造必须核验完整协方差矩阵、成本、约束与收敛，最终仅输出不可执行的研究提案。

## 输出契约

输出至少包含：

- 截止时间、证据层级、原始来源定位和覆盖缺口；
- 市场共识、核心假设、数值预期差、反证和结论强度；
- 财务质量、估值方法、显式假设、三情景与敏感性；
- 风险、催化剂、需继续核验的问题和观察指标；
- 涉及持仓时的原始权重、集中度、相关性与流动性证据或缺口、下行情景和约束状态。

除主动研究链路中明确标记的候选权重和配置差额外，不得包含方向、价格或仓位指令；候选值也不得被解释为执行建议。Schema、字段类型、日期、单位、币种、公式和用户显式约束可作为硬门禁；关键词、标题措辞或是否出现数字只能产生警告，不能单独阻断研究。

涉及税务、法律、杠杆、衍生品、退休资金或重大资产配置时，说明专业风险，并建议用户行动前咨询具备相应资质的专业人士。
