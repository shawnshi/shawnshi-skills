# 协作审计工作流

只在需要事件级指标、等待与重试分析、子代理效率或授权审计时读取本文件。

## 1. 建立范围

1. 定义根任务、时间范围、会话或仓库、数据来源和目标指标。
2. 区分只读审计与已授权整改；只读审计不新增批准回合。
3. 列出缺失时段、不可访问来源和可能改变结论的未知项。

## 2. 收集与标准化

只读取用户提供、已连接授权或当前工作区内的证据。按 [SCHEMA.md](SCHEMA.md) 标准化事件，保留来源和行号，不回显提示词正文、凭据或私人内容。活动 JSONL 可能被运行时持续追加，必须先通过 `scripts/freeze_jsonl_snapshot.py` 冻结完整换行前缀；冻结器不重复解析 JSON 语义。提供回执时，快照先发布、回执最后发布并作为提交标记；聚合、引证和行号全部绑定已验证回执中的快照 SHA-256，不直接绑定活动文件。

Codex rollout 快照先执行：

```powershell
python scripts/standardize_codex_rollout.py --input <snapshot.jsonl> --output <events.jsonl> --summary <standardize-summary.json> --start <ISO8601> --end <ISO8601>
```

已有技能、授权或上下文恢复回执时再分别添加 `--skill-receipts`、`--authorization-receipts`、`--context-receipts`。标准化器不得从自然语言推断授权，不得把工具输入、输出或业务正文写入事件。它仅在实际 `diary_ops.py` 执行载荷中接受白名单回执，兼容新式 `diary-write-scope-v1` 与历史 `schema_version: 2 + component: diary_ops`；冲突回执失败关闭。只读查看 `generate_resource_manifests.ps1` 不算写入；实际调用该脚本和 `apply_patch` 才生成写入意图。

对 JSON/JSONL 输入运行：

```powershell
python generate_final_report.py --input <evidence-path> --strict
```

需要保存 JSON 时必须由用户指定输出位置，再添加 `--output <report.json>`。`--strict` 遇到跳过文件或记录、非事件信封、等待同键时间回退或缺失时间时返回 2；零条有效记录返回 1。部分覆盖不能宣告审计完成。CLI 对 JSONL 使用流式聚合，不把全部事件字典保留到内存。

## 3. 五类控制

### 等待

- 根任务同时最多保留一个等待调用。
- 有独立本地工作可推进时先工作，不为查看进度而等待。
- 等待超时不等于子代理失败；以状态变化、最终回包和产物验证判断。
- 同一 `state_version` 连续两次超时后，只读一次代理状态；若仍无变化，停止轮询并转做本地工作或结束等待。
- 第三次及以后同状态超时必须记入 `wait_gate_breach_count`；降低平均等待时长不能抵消门禁违例。
- 同一根任务和执行者内的等待时间必须单调；缺失或回退时，重复等待、连续超时和门禁违例指标不得继续给出数值。
- 本机 `PreToolUse/PostToolUse` 钩子以哈希后的会话回合键执行同一门禁：两次相同超时后拒绝再次 `wait_agent`，只允许一次 `list_agents` 探针，且只有可比较的状态指纹确实变化才复位。工具路径不经过通用 Hooks、响应不可分类或运行态写入失败时必须失败开放并留下有界 coverage 回执。

### 技能载入

- 继续遵守每回合完整读取已选择技能的要求。
- 只把同一 `root_task_id + actor_id + context_epoch + skill_sha256` 的再次全文读取算作重复。
- `SKILL.md` 保留核心工作流和资源路由；详细 Schema、模板、变体与示例按需读取。
- 上下文压缩是系统健康指标；只有记录了技能载入 Token 占比时才能讨论技能归因。
- 原始命令推断的 `skill_load_candidate` 与正式 `skill_load` 回执分开；候选只与同一根任务、执行者、epoch、技能名称和路径哈希的正式回执配对。只对字段完整的正式回执计算重复率与 Token，不用当前文件哈希反填历史候选。
- 正式回执同时保存规范化路径哈希、内容哈希、Token 和 tokenizer。相同唯一键的重复调用由排他锁下的幂等检查抑制；“脚本运行了两次”不能生成两次正式载入证据。

### 错误与重试

- 每次失败先分类并生成错误签名，再决定重试、降级或停止。
- 每次重试只验证一个清晰假设，并记录变化；不得通过换组件或改错误标签规避重试预算。
- 第二次出现相同组件、操作和错误签名后停止盲试。
- 连接器 EOF 后，读取操作最多降级一次；写操作先确认远端副作用状态，未知时不得重放。
- 包装层分类以实际执行载荷为界并先移除 ANSI。`no_match`、预期 `validation_guard` 是可观测 outcome，不是执行器故障；语法、路径、工具接口、Unicode、Python traceback、嵌套工具和无法细分的脚本失败使用稳定签名分别计数。

### 子代理

- 仅按相互独立的证据面拆分，不把阻塞主任务的紧急步骤外包。
- 任务包传文件指针、哈希或行号、授权边界、最大回合、二元停止条件和回包 Schema。
- 任务包足以自洽时使用最小 fork；不能安全重述用户约束时传递必要的近期回合。
- 主任务继续处理本地工作；只接收结构化状态和证据指针，不回传完整历史或大段原文。
- rollout 的首条 `session_meta` 定义该文件 actor；全历史 fork 中内嵌的父线程 `session_meta` 只能作为历史证据，不能重新绑定当前 rollout 的执行者。

### 写入授权

- 只读审计不请求写入确认，也不生成持久报告。
- 用户已明确要求的范围内本地可逆编辑不追加确认。
- 外部、不可逆或长期记忆写入按动作、目标和载荷生成授权指纹；任何变化都需要重新确认。
- 连接器返回不确定结果时先查状态，不能把超时当成未写入。

### 确定性写前预检

- `PreToolUse` 只拒绝能够在调用前确定证明的错误：补丁更新／删除目标不存在、仓库型 Git 操作不在仓库、字面通配路径为零匹配或多匹配。
- 新增文件补丁、有效 `git -C` 和普通非仓库命令必须放行。复合命令、变量展开、替代 Git 布局和动态路径无法可靠判断时失败开放并记录覆盖缺口。
- 该预检用于减少无效调用，不是权限系统或完整安全边界；专用工具可能不经过通用 Hook 路径。

## 4. 指标与防刷绿

- 等待同时看重复等待率、同状态超时簇和“有本地工作时等待”的次数；不能只降低等待调用占比。
- 重试使用盲重试率和同签名超预算次数；不能通过切换组件降低指标。
- 子代理使用 `child_tokens / (root_tokens + child_tokens)` 作为占比；另报 `child_tokens / root_tokens`，不要混称放大率。
- 子代理指标必须与完成率、返工率、质量门禁和相同任务类型的 P95 一起比较。
- 永久写入以授权指纹匹配率验证；“未发现越权”不等于没有事件证据。
- 写入尝试、成功提交和授权匹配分别报告；提交为零但存在写入意图或标准化缺口时，授权结论必须失败关闭。
- 上下文压缩后的恢复制品存在率不等于语义恢复率。只有最小目标、授权边界、已完成步骤和输出路径均经结构化字段核验时，才设置 `required_fields_verified=true`。
- 需要生成语义恢复回执时，把四类最小字段写入当前会话 `scratch` 状态包，运行 `scripts/context_recovery_receipt.py`；正文只留在状态包，回执仅保留哈希和计数。本机 Hooks 约定路径为 `brain/<ROOT_TASK_ID>/scratch/mentat-collaboration-audit/context-state.json`，重要里程碑后更新。`PreCompact` 只封存摘要，`SessionStart(source=compact)` 复核未变化后才注入最小恢复上下文。
- P95 样本不足时报告样本数和原始分布，不作稳定趋势判断。

## 5. 形成发现

1. 分开写观察事实、计算结果、解释性推断和用户陈述。
2. 每条发现绑定可解析的事件或文件位置、置信度和替代解释。
3. 按安全影响、收益、成本和可逆性排序；连接器未知写入优先于纯效率问题。
4. 把技能可修、编排可修、运行时可修和政策待决分开，不把散文规则当成运行时实现。

## 6. 交付

在当前答复中先给结论，再给覆盖范围、指标、发现、动作、验证方法和残余风险。只有用户明确要求文件、仪表盘或整改时才产生对应写入；报告模板位于 [report-template.md](report-template.md)。

需要持久化MD/HTML时，先运行：

```powershell
python scripts/report_output.py --period <1d|7d|30d|90d|year>
```

然后在会话 `scratch` 建立唯一 canonical manifest，并运行：

```powershell
python scripts/report_pair.py --manifest <manifest.json> --markdown <allocated.md> --html <allocated.html> [--previous-manifest <previous.json>] [--markdown-template <filled.md>] [--html-template <filled.html>]
```

默认归档目录为当前工作区的 `output/mentat-collaboration-audit`。建议编号、状态、验证结果、标准和证据只能在 manifest 中维护；脚本先验证 MD/HTML 可见内容一致，再写入并刷新隐藏暂存文件，排他发布 MD/HTML，最后发布 receipt 作为提交标记。上一批编号不得消失或静默换义。写后复算三份文件哈希、确认 HTML 自包含，并对大屏做一次视觉检查。原始事件、聚合 JSON、manifest、模板和调试文件仍放在当前会话 `scratch`，除非用户另行指定持久化目标。

非托管 Hooks 的配置解析成功不等于正常会话已启用。使用一次性 `--dangerously-bypass-hook-trust` 仅可做已审核脚本的接线探针；正式使用仍需在 `/hooks` 审核当前定义。若网络、模型或专用工具路径阻止真实调用，报告“已安装／待激活”并保留残余风险。
