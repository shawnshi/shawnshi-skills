# 候选构建与运行记录

只在主体已锁定后初始化正式工作区。新构建器适用于未批准草稿；已批准成果先由真人按原治理流程开启修订。旧路由及四模式选择以business-modes.md为准。

1. 仅在已进入获授权的实际运行，且已确定独立计量文件的路径及写入范围后，调用 `python scripts/run_metrics.py start <独立计量文件.json>`。只读预览或审计不得启动计量；仅加载 SKILL 不构成运行或写入授权。该文件只记时与计数，不存客户原文；已启动的运行若因主体冲突停止，调用 `finish --reason safe_stop`，不创建客户目录。
2. 初始化后调用 `python scripts/build_candidate.py <workspace> --output-root <候选父目录>`。使用返回路径，不使用任意candidate名称直接校验。
3. 只填写候选Markdown业务正文及module_status。策略三个上下文字段只填frontmatter；正文保留`{{strategy.target_contact_level}}`、`{{strategy.visit_objective}}`、`{{strategy.minimum_next_step}}`，finalize统一渲染。手写正文不被静默改写；不一致仍报错。保留模板状态表、版本表、刷新表头；策略导航用“序号｜claim_id｜来源成果｜使用位置”，不要把导航当主张定义。partial/blocked须在状态表写具体缺口；未核实不能改completed。
4. 调用 `python scripts/build_candidate.py <workspace> --finalize <candidate>`。构建器继承身份和授权，固定 ready=false，更新状态登记及当前 run 记录；总报告沿用 init/resume 已分配的版本。信件同 run 保留版本并更新候选中的当前草稿行，新 run 在正式信件版本基础上加 1 并追加记录；旧 run 历史从正式信件继承，不改写。重复 finalize 不累计版本或记录；不补事实、不批准。报错时按具体字段修订后重跑，保留首次日志；最多两轮，不以重写验证器求通过。
5. 若使用规划器，search-plan与run-metrics是正式审计记录，连同evidence-manifest经commit一起提交；source-cache只作可丢弃的临时性能缓存，不证明事实，不纳入交付及审批。candidate-base为本地CAS定位，不是授权证明。
6. 按实际操作调用 `python scripts/run_metrics.py record <计量文件> --count queries_executed=2 --count sources_opened=3`。查询按查询条目数、open按请求数计；失败open同样计数。重读原文计open，不算新来源；计算指纹的字节读取用`--event hash_bytes_read=1`，读取Skill规则用`--event rule_read=1`，二者均不计sources_opened。推荐原文读取用`--event business_source_open=1`；未知token保持null。
7. 提交前 `python scripts/run_metrics.py attach <计量文件> --candidate <candidate>` 将计量启动至提交前快照绑定context/run，写入候选run-metrics。该快照不含提交及后续人工审核时间。
8. 使用finalize返回的expected参数调用commit；成功后只从正式结果报告提交状态。在正式验证结束、进入人工审核等待前执行 `python scripts/run_metrics.py finish <计量文件> --reason validation_complete`，保留计量启动至验证结束耗时；它是独立运行日志，不伪装为已提交版本的一部分。待人工审核的等待时间与生成耗时分开。

容量检查check_briefing_draft仍仅检查形状。正式速览内容检查另要求七个模板章节、三个编号现场问题、时间化节奏、唯一动作、Owner、Due date和红线。支持紧凑列表，不靠空标题通过；该检查不证明事实正确或物理一页。

计量快照的unmeasured_counters列出未观测字段；兼容结构中的默认0不能解释为实际零次。只对实际记录的计数作效率比较；结束后不补造计数。

## 结构化台账输入

需要生成来源/主张表时，用 `python scripts/draft_fields.py ledger <台账输入.json>` 输出到stdout，再将两张表放入候选机构或人物/内部研究正文的既有台账章节。不要再追加第二份台账。此命令只格式化与预检，不查证内容；仍须普通校验和人工复核。输入仅包含sources、claims数组，行字段均为字符串，字段如下：

- sources：source_id, title, publisher, locator, published_date, accessed_date, level, source_group, permission, scope, notes, fingerprint, upstream_id, external_use。
- claims：claim_id, claim_type, provenance, verification_status, text, time_scope, support, counter, confidence, notes。

accessed_date只填YYYY-MM-DD，访问方式/存档说明放notes；external_use仅true/false。C级来源支持非H主张时拒绝，不替使用者改类型或提高等级；由执行者重新评估证据和表述。策略渲染同样不推导新业务事实。

计量起止统一为“获授权运行且路径确定后实际启动”至“验证结束或安全停止”；不回填启动前的起点或估计耗时，提交快照在此之前。最终答复、此前读取及finish之后的真人等待不在区间内；脚本不会自动暂停，finish之前的等待仍计入。旧记录无范围字段时按legacy披露，不能追认为端到端测量。
