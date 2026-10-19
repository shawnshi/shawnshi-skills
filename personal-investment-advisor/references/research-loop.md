# 显式离线研究闭环 v1

固定入口：`python -B scripts/pia.py research-loop --input-file <bundle.json> --evidence-root <explicit-root> --task-dir <explicit-task> [--decisions-file <decisions.json>]`。仅 research_only，不接受权限升级参数；不加入 daily-run、不扫描持仓/Dashboard/Thesis、不联网/下载/模型/账户/Vector Lake，不执行订单。此入口不是每次研究的额外前置门。

## JSON 与输入边界

[research_loop_schema.json](research_loop_schema.json) 是 bundle、decision_file、持久化 record 三种自有结构的共同规范；运行时以同一文件作标准库结构校验，不改旧 evidence_items schema。全部对象拒绝额外字段，数值仅 finite nonboolean，超大整数不能转成有限float时结构化失败。

Bundle根：schema_version=pia_research_loop_v1、安全字符record_id（字母/数字/下划线/横线，至多80）、带时区as_of、scope=listed_events_only、events/conditions/links。events至多100；conditions/links至多200。每个event有event_id/symbol/published_at/retrieved_at/source_locator/artifact/content_sha256/body_retrieved/health/source_error/coverage_complete/coverage_limits。无原件时artifact与hash都null；不能同时宣称body已取得。health为ok/empty/broken；broken必须保留原错误，empty不表示证券没有重大事件。

条件副本含condition_id/symbol/version/confirmed_at/effective_from/metric/operator/threshold/unit/period/due/channel及source_locator/artifact/hash。operator复用Thesis字段lt/lte/gt/gte/eq/qualitative；due为ISO日期或持续；period为start/end日期对象或null。只选择截至as_of已确认且effective_from已生效的最高版本，重复同ID/版失败；链接与决定必须绑定该版，不能用旧rev判断新版本。仅当前选中的有效条件版本缺原件时生成业务补证；未来或未选版本仍执行全部结构、身份和摘要校验，不伪造用户确认。

links显式提供link_id/event_ids/condition_id/condition_version/reason/locator（原文page-table-line，可null）、actual、actual_period(start/end/complete)与unit，以及counterevidence事件ID/定位清单（可null）。同symbol不自动形成关联。缺反证或空清单不能当已证明无反证。qualitative仅记录人工语义复核，不自动提炼正文；数字比较只在到期、期间/单位匹配、完整期间结束且实际值/阈值有效时进行，并要求该关联的选中条件原件、主事件及反证引用正文、来源健康、覆盖完整、原文定位和反证清单全部具备。缺任一证明则 assessment=insufficient_evidence、comparison_result=null；未到期可 not_due，不比较。其他无关条件缺口不改变已有完整证明关联的单项评估。

Decision文件：schema_version=pia_research_decisions_v1、独立record_id、proposal_sha256、decisions（至多200）。每项link_id/action=accept|return|reject/reviewer/reviewed_at/reason/event_ids/condition_version，时间不晚于as_of，且逐关联覆盖其主事件与反证引用并集的发表/取得时间及条件确认时间，不能由其他关联的较晚复核代替。必需的 reviewer、reason、locator 等声明必须含非空白字符；Schema 使用 `\S`，运行时实际执行该 pattern，拒绝 Unicode 纯空白，保留正常含空格文本，不自动填值。输入声明的reviewer没有外部身份认证。proposal_sha256取首次返回的字段（等于持久化proposal.record_sha256），为去掉record_sha256字段后规范JSON摘要：Unicode、键排序、紧凑分隔符、非有限值禁用；不是带checksum字段文件的整文件摘要。

## 状态与记录

没有decisions时生成proposal及稳定task_id补证任务。缺正文/版本/原文定位/分页覆盖/单位期间/反证/来源故障为insufficient_evidence；仅待人工复核或未关联为incomplete。空事件范围为insufficient_evidence。未到期为not_due且comparison_result=null；不提前met/missed。

随后提供decisions：return生成补证；reject仅关闭该关联、撤销其关联层补证，事件/来源缺口仍保留，绝不判Thesis安全；accept不能消除机器检出的业务缺口。只有有限listed_events_only范围的全部事件已显式关联、所有关联有人工决定且无补证缺口才complete。任何状态下orders_executed/investment_authorized/formal_use_allowed都false；hash/locator只能证明内容与元信息绑定，不自动认证业务事实、来源真实或完整重大事件覆盖。

非法结构/未来时点/hash漂移/身份或版冲突/超限/路径逃逸/提交失败为failed（exit3）；其余exit complete=0、incomplete=1、insufficient_evidence=2。原始retrieved_at不改写。URL+内容身份去重保留全部aliases和逐来源回执，不只留newest。

## 文件安全与幂等

仅读显式artifact清单；相对路径拒绝..、absolute、Windows drive、symlink/reparse，resolve必须包含在evidence-root内。输入至多2MiB，单原件8MiB、累计64MiB，输出record16MiB。task必须与evidence及输入文件分离，输出祖先/目标路径不能是链接。检查不是OS沙箱；调用方须保持已授权输入/目录不被并发替换。

输出仅 `<task-dir>/research_loop/<record_id>.json`，补证与人工记录嵌入单文件，同目录临时+fsync+原子提交。规则版本 research_loop_proof_v3_two_phase 进入 proposal key，receipt key 继承该绑定；旧规则记录即使原输入相同也冲突，须新明确 record_id，不覆盖历史。同record_id同规则/输入/根身份/版/决定key返回旧文件，不改mtime/generated_at；不同key拒绝覆盖，用新的明确record_id记录新输入/决定。proposal 与 receipt 是两个独立阶段，不是假跨文件事务。第一阶段必须先提交 proposal；带 decisions 的第二阶段只读此前已提交且 Schema/摘要/规则 key/record_id 全部有效的 proposal，最终只原子提交一个 receipt。缺 proposal 或无效决定不得创建或修改任何文件；既有 proposal 是上一阶段的正常结果，不是本次半提交。旧 receipt 不改，不自动重试/补偿。持久化文件带规范摘要，复用先校验Schema/摘要/key；旧manifest不能静默复用为complete。

## 剩余项的显式可选入口

- `pia.py research-prepare --channel-report <explicit-collector-report> --template-file <explicit-loop-bundle-template> --evidence-root <explicit-root> --task-dir <explicit-task>`：仅消费原生 collect-evidence 输出，不采集、不下载、不扫描账本。模板必须 events/links 为空，提供已授权 conditions 副本、as_of、record_id；输出 `<task>/research_prepare/loop-bundle.json` 可供 research-loop，候选与补证清单在返回 JSON 中。证券相同仅候选，标题不是经营主张，不代填 reviewer。保留所有返回记录和重复 URL aliases、原始 retrieved_at；超过 100 events/200 conditions-links 结构化失败，不截断。所有 coverage_complete 均 false，要求人工补正文、定位、值、单位、期间、分页及反证。准备 task 与随后 loop task 必须分离；输入与原件不改写。
- `pia.py evidence-check --input-file <explicit-assertions> --evidence-root <explicit-root> --output <task-result>`：只验证原件 hash 绑定的内容一致性，成功名为 artifact_claim_match_verified，business_facts_authenticated/human_identity_authenticated 仍 false。输入根精确为 schema_version=pia_artifact_assertions_v1、UTC as_of、1..200 assertions。每条 assertion_id/artifact/content_sha256/kind/expected；json_pointer 类型另提供 pointer 与 bindings（unit/period/observed_at，各为 pointer/expected；period expected 为 start/end 日期对象），text_lines 类型另提供 start_line/end_line（从 1 起，UTF-8 完整行精确匹配）。expected 仅非空白文本或 finite nonboolean 数字，JSON 值与显式单位/期间/UTC 时点均须吻合且不未来。拒绝错 hash/值/单位/期间/非法 pointer/行号/路径逃逸；不 OCR/eval/模型/登录，不认证发行人或客观业务真相。
- `research-loop --require-authenticated-review`：当前没有已授权可信验证器，固定返回 required_capability_unavailable/failed/exit3（BLOCKED），不写入、不用 reviewer 字符串或旧 weak receipt 代替 strict complete。恢复至少需要 owner 提供可信身份验证器、授权范围、规则版本/record key 绑定及可验证回执政策；不创建账号、私钥或凭证数据库。
- `pia.py isolated-research-loop`：与 research-loop 相同显式参数，只执行固定受控脚本。现有 WSL 非 root 上通过 `unshare -Urn` 与 `python3 -I -S -B`、清空/重建环境和 guest timeout 执行；Windows 仅本地 C: 安全路径、无 shell，无权限/能力时 fail closed，不回退 host。文件捕获限制 8 MiB，guest 45 秒 + 3 秒终止宽限；Windows 等待 63 秒，不复用不同 OS 的 monotonic 时钟。实际 proof 比较 parent/new netns，读取 /proc 网络接口与路由并核验 IPv4/IPv6 内核拒绝；返回独立生命周期证据。netns inode 不进入业务 key，跨 Windows/Linux 根身份使用不同 task/record_id。仅隔离 OS IP 网络，不隔离 filesystem、AF_UNIX broker 或 host 其他进程，不是绝对 OS 沙箱。

源通道 requests/urllib 共用 HTTPS-only、验证证书、拒绝所有重定向（在访问目标前阻断 HTTPS→HTTP）、无虚构 contact 的薄 helper。官方相对文档 URL 用 HTTPS，历史原文 URL 不改写；原始列表字节不重写。WAF/TLS/HTTP/格式失败为可定位 broken，不当作 empty。第三方 yfinance/akshare 内部实现不在本安全闭包中。

公开源匿名策略 `pia_anonymous_https_v2`：专属 factory 与请求前强制 `trust_env=False`，不读取 netrc 或环境代理；拒绝显式 auth/cookies/client cert/proxies、认证及 Cookie headers。只检查凭证元数据／header 键，不回显值；每次请求后清空 Cookie。urllib 使用独立 `ProxyHandler({})`，不安装全局 opener。缓存 v3 必须绑定本匿名 policy revision，旧 schema/policy 真实失效重取，不改写旧 retrieved_at；需要代理时由 caller 另行明确无凭证代理授权，禁止自动环境回退。新补证见 audits/residual-reviewfix-20261010：匿名 HTTPS 可用性已实读，Windows 超时仅离线模拟通过；WSL 强制 deadline 探针未闭合，超时物理验证仍 partial，不否定此前正常退出证据。

新证据与剩余外部边界见 audits/residuals-20261010；匿名公开健康读不是公司投资研究，合成负载不是个人生产验收。

## 合成示例

`research_loop.example.json` 与 `research-loop-fixture/evidence/{event,counter,condition}.txt` 完全合成，不是投资事实。可用显式授权的隔离task调用：

```text
python -B scripts/pia.py research-loop --input-file references/research_loop.example.json --evidence-root references/research-loop-fixture/evidence --task-dir <synthetic-task>
```

初次是incomplete/exit1。人工提供独立decision JSON，将proposal_sha256与有效条件版/事件集合逐项绑定，再加 `--decisions-file` 得到receipt；同scope接受/拒绝只记录复核，不给投资授权。初版真实命令 smoke 和离线回归见 audits/phase3-20261010；独立审查修复与最终验证见 audits/phase3-reviewfix-20261010；未宣称无人值守、真实投资闭环或联网验证。
