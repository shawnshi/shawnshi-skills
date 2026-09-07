# HIT 报告安全归档契约（Windows）

仅供 hit-weekly-brief 与 hit-lectures-scout。自动归档权限不等于扩大路径、权限或发布范围的权限；用户要求草稿/预览/不保存时不运行 commit。不能唯一解析既有 MEMORY 工作区或用户目标时先停止，不创建平行归档目录。本规范不授权改写既有报告或 ACL。

## 路径与能力

`skill_dir` 是当前技能的绝对目录。自有校验器从 `skill_dir / "scripts"` 解析；共享资源从 `skill_dir.parent`（skills root）解析：

- `shared/scripts/report_archive.py`：唯一共享 validate/commit 入口。
- `shared/scripts/report_archive_windows.py`：Windows owner/group/DACL 和访问证据后端。
- `shared/scripts/test_report_archive.py`：仅在独立临时夹具执行的回归测试。
- `shared/references/report_archive.md`：本契约。

使用 Python 3 和**已有的 pywin32**，不自动安装、不获取 Explorer/shell token、不启用权限或更改账号。POSIX owner/ACL 保真未实现，返回 BLOCKED/CAPABILITY；Python、校验器、时区数据或 Windows 能力缺失均停止，不能改用普通复制或人工检查后不安全发布。技能不得自行用 os.rename/os.replace/shutil 归档；这些操作只可由共享门禁在验证后受控执行。

路径仅支持既有目录内的本地、非数据流 Markdown 文件。源必须为非空、严格 UTF-8、无替换字符且不超过 8 MiB；符号链接、reparse 路径、报告硬链接、UNC、Windows 别名尾点/空格路径拒绝。源和目标不同，目标必须逐次等于调用方精确 allow-target 白名单；它不是目录授权或通配符。

## 先结构校验，再 validate → commit

1. 在会话私有隔离临时目录写 UTF-8 定稿，保留草稿。使用技能自有校验器及真实参数；所有元数据位于首个二级标题前，格式和语义见技能模板。人工核验来源、版本、时间和研究结论不可省略。
2. 将共享脚本解析为绝对路径。`validate` 是只读 dry-run，成功 stdout 是 JSON 快照计划（不是提交回执），非零退出则 BLOCKED，不运行 commit。
3. 保存完整 stdout 为独立临时 UTF-8 JSON 文件，不手工改计划字段。检查源/目标、skill/周期/档期、源 SHA-256、目标和父目录快照及自定义选项符合任务；随后用同一个精确 allow-target 提交。计划不是放宽路径或权限的授权。

下面为 PowerShell 调用骨架；变量须事先解析为本次任务的绝对路径，`$planFile` 位于会话临时目录。`$skillName` 只能是 `hit-weekly-brief` 或 `hit-lectures-scout`。不要把提示文本或错误输出写成计划。

```powershell
$planJson = & python -B "$archiveScript" validate --source "$draft" --target "$target" --allow-target "$target" --skill "$skillName"
if ($LASTEXITCODE -ne 0) { throw "BLOCKED: archive validate" }
[System.IO.File]::WriteAllText($planFile, ($planJson -join "`n"), [System.Text.UTF8Encoding]::new($false))
# 只读检查计划，确认后再执行；不要编辑快照来绕过冲突。
& python -B "$archiveScript" commit --plan "$planFile" --allow-target "$target"
if ($LASTEXITCODE -ne 0) { throw "BLOCKED: preserve receipt and recovery evidence" }
```

实际 CLI：

- `validate --source FILE --target FILE --allow-target FILE --skill {hit-weekly-brief,hit-lectures-scout}`；可选 `--allow-custom-filename`、`--allow-custom-period`，只在用户明确指定时使用。后者用于 weekly 自定义周期，scout 按其窗口元数据处理。
- `commit --plan FILE --allow-target FILE`；无强制覆盖、放宽 ACL、自动恢复或 stale-lock 删除参数。计划读取支持 UTF-8 BOM；重复 JSON 键拒绝。
- 自有 weekly 校验器：`--file --period-start --period-end --issue-date --cutoff` 均必需，可选 `--report-timezone`（默认 Asia/Shanghai）、`--allow-custom-filename`、`--allow-custom-period`。
- 自有 scout 校验器：同样五个必需参数，可选 `--window-mode {explicit,generated}`（默认 explicit）、`--report-timezone`（默认 Asia/Shanghai）、`--allow-custom-filename`；没有 `--allow-custom-period`。

共享 validate 从报告头提取参数并再次调用自有校验器；草稿临时文件名可不同，但默认目标仍须为身份指定的 DHWB/DHLS 文件名。结构通过不证明 DOI 真实、临床证据强度、原文链接可访问或日期行在同日 cutoff 之前；仍需人工来源门禁。

## 新版身份与既有报告

两个技能都要求唯一的 `报告周期：start 至 end`、`出刊日期`、带时区 `生成时点`、`报告时区`。scout 还要求唯一 `命名依据：explicit/generated`。替换身份包括技能、周期起止、出刊日期和 scout 命名依据；既有目标还须具有对应技能的规范标题/命名身份。自定义文件名不允许将 scout 当成 weekly 覆盖。

新版模板/正文 schema 只用于未来报告，受保护的命名与日期默认值保持不变。即使文件名和窗口看似相同，旧目标缺少必要身份字段、标题不规范或存在歧义时仍 fail closed；须人工身份规范化/复核，**禁止自动重写旧报告来通过验证**。正文无需为身份检查强制迁移所有新表格字段；新源必须完整通过当前结构校验。

## 权限与事务边界

- 新报告：创建一个唯一拥有的**目标父目录直接子文件**作为空 candidate，让 Windows 计算 immediate-child FILE 继承 DACL（包含只传播一代的 ACE）；owner/group 来自确认的父目录。应用并严格验证该策略后才写入报告字节。不能通过 staging 目录的孙文件来推导父目录文件策略。
- 替换：使用旧目标精确 owner、primary group、DACL 及 DACL protection 状态；不合并或放宽策略。候选文件和保留的 original.md 都应用原策略并严格比较，不能因 native canonicalization 差异降低生产相等检查。
- 私有草稿保留。唯一 `.report-archive-*` 恢复目录包含 journal.json，替换时还保留 original.md；candidate 在同父目录旁边，journal 记录其绝对路径和哈希。成功 rename 后该 candidate 路径不存在是正常的；失败时不得猜测或删除保留证据。
- 覆盖的是 owner/group/DACL/protection，不是完整 SACL、审计或强制完整性策略保证。权限失败不能授权添加 Everyone/Users 写权限、take ownership、提升权限或改 ACL。
- 原生 limited-token AccessCheck 检查 read/write/modify，另做当前 host token 的读写/删除权打开及内容读取。提升宿主使用已有 linked limited token 作 AccessCheck；回执 `actual_non_elevated_open=false`，不能声称做了实际非提升进程打开。非提升宿主有可用实际打开证据；始终区分两类证据，不获取 shell token。
- 排他锁序列化**遵守本门禁的调用方**；源内容、目标内容/身份/安全描述符和父目录身份/安全描述符在提交中重新快照检查。锁存在即冲突，无自动 stale-lock 删除。
- 新目标使用 Windows no-replace rename，竞争出现的新文件不被覆盖。替换使用受控原子 replace，但对**不合作的外部写者**，最后检查与 replace 之间仍有 TOCTOU 窗口；这不是任意写者间的 compare-and-swap。不要宣称无条件并发安全。
- 提交后核对目标内容哈希、安全策略、访问证据及父目录漂移；POSTCOMMIT/BLOCKED 可能已经改动目标，不能当作“未写入”。失败保留证据，不盲目回滚。

## 回执与恢复

commit stdout JSON 包含 status、code、target、sha256、security、rollback、recovery_directory，失败时有 detail。仅 `status=COMMITTED` 且退出 0 可报告成功；记录绝对目标、SHA-256、访问证据及限制。非零退出应保存 stdout 回执，不扩大重试权限。

发生冲突/访问失败/POSTCOMMIT 时先保留草稿、journal、original 和可能仍在父目录的 candidate；只读比对当前目标、较新内容、原始备份、源哈希与安全描述符。锁的所有权或存活不明时停止升级人工处置，不能自动清锁。恢复无专用子命令：明确确认恢复意图且排除竞争/较新版本后，选定源（例如 original.md）对**当前目标**重新运行 validate 获取新快照，再 commit；恢复源也须通过当前结构校验。不能复用旧计划、跳过冲突、静默覆盖竞争版本或自动执行破坏性回滚。
