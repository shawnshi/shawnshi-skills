# Intelligence Quality Standard 1.3

## 1. 证据与推演等级

- **L1 Signal**：原始信号，尚未形成可靠上下文。
- **L2 Info**：事实与基本上下文已核验，行动价值有限。
- **L3 Insight**：完成 `fact -> connection -> deduction -> actionability`，并说明近期决策影响。
- **L4 Alpha**：非共识且可直接触发动作；必须有独立逻辑红队回执覆盖该条目的完整哈希。

等级表示推演深度，不代表扫描覆盖充分。`confidence` 只描述条目主张可信度；运行覆盖另用 `coverage.coverage_confidence` 表达，来源佐证另用 `corroboration_status` 表达。

## 2. 条目硬门槛

每条正式资讯必须同时具备：

- 稳定 `event_id`、结构化 `event_identity` 和 `identity_quality`；
- 至少一个来自已登记候选池的 `candidate_ref`，并由语义回执绑定候选对象哈希；
- 原文 `title` 与中文显示名 `title_zh`，归档不得用翻译覆盖原文；
- 直接 URL、`source_type` 和成功的 `access_check`；其中 `requested_url` 必须匹配条目 URL，`final_url` 仅记录跳转落点；
- 已知且位于报告窗口内的 `published_at` 及其来源；
- 分开的 `event_date`、`observed_at`、`retrieved_at` 和日期来源；
- 唯一 `primary_domain`，可选且不重复主领域的 `secondary_domains`；
- 分开的 `fact`、`connection`、`deduction`、`actionability` 与 `summary_zh`；
- `intelligence_level`、条目 `confidence`、`corroboration_status`；
- `major_signal`、`major_signal_reason`、`near_term_decision_impact` 和原因。

未知或无效发布日期进入隔离池，不得进入正式 Top。观察时间、检索时间、网页更新时间不得冒充发布日期。

## 3. 来源与事件卫生

1. 原始来源优先；二手来源只有在存在多个独立佐证时才可作为正式条目。
2. 先按结构化 `event_id` 合并同一事件，再按规范化 URL 和标题指纹兜底。
3. 同一事件的多个来源作为佐证合并，不得重复计数。
4. 来源无法访问、发布日期不明、候选不足、车道失败和来源集中均写入结构化缺口。
5. 单一来源占比超过配置阈值只产生软警报，不自动证明条目错误。

## 4. 领域配比

- 合同默认：`technology=0.6`、`healthcare_digital=0.4`。
- 用户指定比例时写入 `requested_ratio`、`ratio_source=user` 和理由；该请求比例是当日调整基线。
- 先执行证据门槛，再按最大余数法计算目标条数；证据不足时保留少于 10 条。
- 只有经红队覆盖的 L4，或“高可信 L3 + 原始来源 + 访问已核验 + 近期决策影响”可声明重大资讯。
- 单日最多偏移 20 个百分点；两个领域同时出现合格重大资讯时不调比。
- 合格候选不足可跨领域补位，但必须记录 `supply_exception`，不得用弱资讯补数。

## 5. 运行覆盖与候选漏斗

`coverage` 必须从真实运行记录复算：来源尝试、成功、失败、有效日期比例、基线状态、必要车道失败和降级原因。HTTP 200 的阻断页或不可识别 feed 不算成功；来源成功但零候选仍为 degraded。基线全灭或必要车道失败时，`run_status` 不得是 `complete`，`coverage_confidence` 与 `reasons` 必须和复算状态一致。

`candidate_funnel.observed` 必须等于所有 `terminal_dispositions` 之和；`retained` 必须等于正式条目数。隔离、窗口外、排除、历史重复、质量门淘汰、容量淘汰、语义淘汰和红队淘汰不得混入含义不明的 `noise_count`。

## 6. 回执与归档

1. 启发式脚本只生成 `candidates_only`，不得生成或授权最终事实、等级、推断和置信度。
2. 补检结果必须绑定 `run_id`、补检请求 SHA-256、基线与候选池 SHA-256、gap、非空查询、逐次访问日志、从日志派生的覆盖计数、data provenance、轮次和停止条件。
3. 语义与红队先登记 challenge-bound review request；回执必须原样返回 request、reviewer、invocation 和 challenge，轮次不得超过请求。
4. 语义回执必须绑定输入 bundle 与 refined core SHA-256，覆盖每个最终条目的完整对象哈希，并验证候选对象到输出条目的血缘及正式访问记录。
5. L4 必须有逻辑红队 `passed` 回执及对应条目哈希；没有 L4 时允许明确 `not_required`。
6. `briefing_gate.py` 按 `schema_version` 路由冻结的历史 validator；新产物固定使用 1.3。
7. JSON 通过 gate 后，Markdown 必须从同一 payload 确定性渲染。JSON、Markdown 和 commit sidecar 使用目标哈希前置条件与可恢复提升；按新闻目录派生的操作系统级排他守卫必须覆盖旧锁判断、恢复、接管、历史重检和整个提交区。Windows 使用跨登录会话的 `Global\` mutex，创建或取得失败时封闭拒绝；不得回退为 `Local\`。目录元数据锁携带随机 owner token，回收前复核观测字节、释放前复核 token；活动进程和无法验证的异地主机锁不得被回收，只有同机已确认死亡且元数据未变化的锁可触发恢复；可捕获失败时回滚。
8. history v2 快照按档案时间重建并纳入输入哈希；正式成稿不得重复该快照中的近期事件。归档器必须在排他守卫内、创建 staging 前从正式 JSON 档案重建并比对快照，再对最终条目逐项去重；三件套验证完成后仍在同一守卫内更新派生 history v2。正式 JSON 始终是事实源；若派生索引更新失败，正式集合保留并明确报错，后续运行仍以正式档案重建结果封闭拒绝重复事件。

challenge 只证明回执读取了本次预登记请求并防止旧回执重放，不证明外部运行时身份；调用层必须真实使用独立语义与红队代理，不得把同进程合成回执描述为独立审查。

## 7. 交付标准

- 结论、证据、影响、行动和未知项可追踪；行动项包含责任角色、启动条件和检查指标。
- `top_10` 为 0–10 条；URL 和 `event_id` 均不重复。
- 请求比例、生效比例、目标条数、实际条数、调整和供给例外可以机器复算。
- JSON 与 Markdown 路径、条目数、实际比例、链接核验和覆盖缺口必须回报。
- 任一硬错误、回执不匹配或事务失败时，不得宣称归档完成。
