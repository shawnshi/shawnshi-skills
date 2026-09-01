---
name: mentat-collaboration-audit
description: 基于真实会话记录、日志、工具调用和遥测事件审计系统效率与人机协作摩擦，复算等待、技能载入、错误重试、子代理Token、上下文压缩和写入授权指标，并按需生成Markdown报告和HTML审计面板。用于复盘执行效率、排查系统绕路、核验连接器失败或权限阻塞、生成证据化协作报告；默认只读，不自动修改或持久化。
---

# 系统与协作审计

## 权限边界

- 默认执行只读审计。读取、分析和报告不授权修改任何配置、规则、代码、技能或外部系统。
- 用户明确要求实施范围内本地可逆修复后直接执行，不增加第二次确认；外部、不可逆和长期记忆写入仍按授权合同处理。
- 不自动保存报告、写入知识库或登记长期记忆。只有用户明确要求时才持久化。
- 日志可能包含私人内容、凭据或业务数据。只读取任务所需范围，输出前脱敏，禁止回显秘密和完整个人内容。

## 执行流程

1. 明确根任务、时间范围、数据来源、缺失数据和目标指标。数据不足时先说明能回答与不能回答的问题。
   - 完整读取任一选定技能后，运行 `python scripts/skill_load_receipt.py --skill-path <SKILL.md> --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --output <SESSION_SCRATCH>/skill-load.jsonl`，记录规范化路径哈希、内容哈希和基于 `cl100k_base` 的可复算内容 Token。相同 `root_task_id + actor_id + context_epoch + skill_name + skill_sha256` 的重复调用以排他锁幂等返回，不追加第二条正式回执。该 Token 仅用于技能文本比较，不冒充模型账单 Token。
2. 收集真实证据并建立事件序列，区分观察事实、计算结果、用户陈述和解释性推断。
   - 活动 JSONL 仍在增长或被占用时，先运行 `python scripts/freeze_jsonl_snapshot.py --source <ACTIVE_JSONL> --output <SESSION_SCRATCH>/activity.snapshot.jsonl --receipt <SESSION_SCRATCH>/activity.snapshot.receipt.json`；后续只读取冻结文件。
   - 报告必须披露冻结时间、源文件捕获字节数、稳定前缀终点、快照 SHA-256、记录数和是否排除了尾部不完整记录。
   - 输入为 Codex rollout 快照时，必须运行 `python scripts/standardize_codex_rollout.py --input <SNAPSHOT> --output <SESSION_SCRATCH>/events.jsonl --summary <SESSION_SCRATCH>/standardize-summary.json --start <ISO8601> --end <ISO8601>`，不得继续使用临时编写、未经测试的标准化脚本。已有技能载入、逐写入授权或上下文恢复回执时，分别添加 `--skill-receipts <JSONL>`、`--authorization-receipts <JSONL>`、`--context-receipts <JSONL>`。
   - 标准化器只输出哈希、行号和有限状态，不保存工具输入、输出或业务正文。它把写入调用拆成 `write_attempt/write_commit`，仅从实际执行载荷中解析受白名单约束的日记授权／提交回执，并同时兼容 `diary-write-scope-v1` 与 `schema_version: 2 + component: diary_ops`。包装层结果按稳定签名细分；`no_match` 和预期 `validation_guard` 保持可见但不计为执行失败。无法绑定授权回执的写入必须保持未匹配。
3. 输入为 JSON/JSONL 时，按 [references/SCHEMA.md](references/SCHEMA.md) 核对字段，并使用 `python generate_final_report.py --input <path> --strict` 聚合；不得忽略部分覆盖。
4. 按 [references/WORKFLOW.md](references/WORKFLOW.md) 检查等待、技能载入、错误重试、子代理和写入授权；没有对应字段时标记不可计算。
   - 批次 A 门禁同时检查：写入提交是否可见、嵌套错误是否上浮、技能候选与正式回执是否分离、同状态第三次超时是否记为门禁违例、压缩恢复是否只有“存在”证据而缺少语义字段核验。
   - 已安装生命周期钩子时，`scripts/hooks/codex_hook.py` 分别承接等待熔断、确定性写前预检和压缩恢复；未知或专用工具覆盖必须失败开放并留下有界回执，不得宣称钩子是完整安全边界。非托管钩子还必须在 `/hooks` 审核当前定义后，才可把正常会话中的执行状态写成“已生效”。
5. 每条发现绑定证据位置、置信度、替代解释、影响和复现条件；不把相关性写成因果关系。
6. 按安全影响、收益、成本和可逆性排序，区分技能、编排、运行时和政策层修改。
7. 只在证据面可独立拆分且并行确有收益时使用子代理；传最小任务包、文件指针、停止条件和结构化回包要求。
8. 在当前答复中交付结果。只有用户明确要求文件、仪表盘或整改时才产生对应写入。
9. 用户要求持久化报告、仪表盘或审计面板时，先运行 `python scripts/report_output.py --period <1d|7d|30d|90d|year>`，取得同一批次的 `markdown` 和 `html` 绝对路径；再在当前会话 `scratch` 建立 canonical manifest。每条建议必须使用稳定 `R-xx`、关联 `F-xx`、状态、授权、验证标准、验证结果和证据；有上一批 manifest 时传入并禁止编号消失或语义漂移。
10. 运行 `python scripts/report_pair.py --manifest <MANIFEST_JSON> --markdown <ALLOCATED_MD> --html <ALLOCATED_HTML> [--previous-manifest <PREVIOUS_JSON>] [--markdown-template <FILLED_MD_TEMPLATE>] [--html-template <FILLED_HTML_TEMPLATE>]`。脚本先从同一 manifest 渲染并交叉核验两种格式，再排他写入 MD、HTML 和哈希回执；不得分别手写两份建议表，也不得覆盖既有批次。

## 可选资源

- 需要完整报告结构时读取 [references/report-template.md](references/report-template.md)。
- 需要事件字段、错误信封、子代理回包或授权指纹时读取 [references/SCHEMA.md](references/SCHEMA.md)。
- 需要五类控制和防刷绿指标时读取 [references/WORKFLOW.md](references/WORKFLOW.md)。
- 保存过的聚合 JSON 可运行 `python scripts/validate_agent_audit.py <report.json>` 验证。Schema、字段类型、来源标识和覆盖状态错误会阻断；篇幅、关键词、固定条目数和语言比例只产生提示。
- 用户要求交互式仪表盘时，可使用 `assets/template.html`；模板必须保持自包含，不从网络加载脚本。
- 当前唯一数据入口是 `generate_final_report.py` 的显式 `--input` 聚合流程；不保留会扫描私有会话目录的兼容入口。
- `scripts/freeze_jsonl_snapshot.py` 只复制调用时已经完整换行的 JSONL 前缀，默认拒绝覆盖；它不做 JSON 语义解析，也不读取或修复尾部半条记录。提供 receipt 时先暂存并刷新两份文件、最后发布 receipt；只有 receipt 存在且哈希匹配才视为已提交批次。
- `scripts/skill_load_receipt.py` 只对本次实际全文读取的 `SKILL.md` 生成回执；不得扫描技能目录后批量补造载入事件。
- `scripts/standardize_codex_rollout.py` 只消费调用方显式选择并冻结的单个 rollout 快照；不得自行扫描会话目录。首条 `session_meta` 绑定该 rollout 的执行者，内嵌父线程元数据不得改写 actor。它对当前已知写入入口采用保守识别，未知工具语义保持未分类，不以名称猜测授权。
- `scripts/report_pair.py` 的 manifest 是建议清单唯一事实源；Markdown/HTML 的编号、状态、验证结果、标准与证据不一致即阻断写入。三份文件先写入同目录隐藏暂存文件并 `fsync`，Markdown/HTML 发布后最后发布 receipt 作为提交标记。默认模板只提供结构，完整报告必须在调用前填入审计范围、发现、指标和限制。
- 上下文压缩后需要核验语义恢复时，在当前会话 `scratch` 创建只含 `objective`、`authorization_scope`、`completed_steps`、`output_paths` 的 JSON 状态包，再运行 `python scripts/context_recovery_receipt.py --state <STATE_JSON> --root-task-id <ROOT_TASK_ID> --actor-id <ACTOR_ID> --context-epoch <EPOCH> --output <SESSION_SCRATCH>/context-recovery.jsonl [--append]`。本机全局钩子使用 `brain/<ROOT_TASK_ID>/scratch/mentat-collaboration-audit/context-state.json` 作为会话限定状态包；重要里程碑后应原子更新。正文只留在状态包，钩子运行态与回执仅保留哈希和计数。
- `scripts/hooks/codex_hook.py` 仅拒绝可确定证明的情况：同一会话回合两次同状态超时后的再次等待、缺失的补丁更新／删除目标、非仓库中的仓库型 Git 操作，以及零匹配或多匹配的字面通配路径。复合命令、动态路径和专用工具覆盖未知时失败开放并记录覆盖缺口。

## 验证分层

- 硬错误：文件缺失或不可读、JSON 非法、Schema 版本或必需字段错误、字段类型错误、覆盖状态与问题清单矛盾。
- 软提示：固定章节或条目数不足、摘要较短、数字比例、关键词覆盖、措辞和建议数量。
- 人工判断：根因、因果、优先级、方案收益和政策建议。校验脚本不得替代这些判断。

## 报告归档契约

- 协作审计产出的 `.md` 和 `.html` 默认保存在当前工作区的 `output/mentat-collaboration-audit`。
- 用户显式指定的 `--output-dir` 优先。只有本次任务明确选择既有配置时，才可加 `--use-configured-output-dir` 读取 `MENTAT_AUDIT_REPORT_DIR`；环境变量本身不授权改变写入位置。
- 同一次审计的 Markdown 与 HTML 必须共享主干，例如 `collaboration_audit_7d_20260727_101530.md` 与 `.html`。
- 原始会话、标准事件集、聚合 JSON、提示词正文、凭据和调试文件不得默认写入报告目录；中间态放入当前会话的 `scratch`，JSON持久化仍需用户指定路径。
- 普通只读审计不自动落盘。用户提出“生成报告、面板、大屏并保存”即授权保存该次请求的本地 MD/HTML，不授权整改、外部发布、长期记忆或 Vector Lake 写入。用户要求草稿、预览或不保存时，则保持只读，不写入归档目录。

## 输出结构

1. 审计范围与数据覆盖
2. 关键结论
3. 发现清单：严重度、证据、根因、影响、复现条件
4. 指标与计算口径
5. 修复建议和优先级
6. 未知项与残余风险

## 完成检查

- 每个结论都引用日志位置、时间点、调用记录或可复算指标。
- 报告披露分子、分母、样本量、缺失数据和跳过记录；严格聚合无未解释失败。
- Codex rollout 回放中，嵌套错误不得保留为顶层成功；写入提交数为 0 时必须同时证明标准化器没有识别到写入意图，否则不得给出授权假绿结论。
- `skill_load_candidate` 不能冒充正式 `skill_load`；只有带路径哈希、内容哈希、Token 与 tokenizer 的回执进入正式载入指标。
- 上下文恢复存在率与最小目标、授权、完成步骤和输出路径的语义核验率分开报告。
- 修改建议必须由 canonical manifest 同源生成；MD/HTML 中的 `R-xx` 集合、顺序、状态、验证结果、标准和证据全部一致，且回执哈希与落盘字节复算一致。
- 钩子脚本单测、配置可解析和实际正常任务生效是三层不同证据；若未完成 `/hooks` 信任或新会话真实调用，只能报告“已安装／待激活”，不得报告“运行时已生效”。
- 不使用不存在的数据填充图表或指标。
- 敏感信息已删除或遮蔽。
- 未经明确授权，没有执行任何修复、持久化或配置修改。
- 持久化任务的MD/HTML位于同一归档目录、共享主干、均非空，并返回实际存在的绝对路径链接。
