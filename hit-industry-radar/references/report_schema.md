# 正式行业雷达结构与本地校验

仅正式定稿使用此结构；简短问答/预览不要求文件或元数据。只读答复仍须说明窗口、截止、事实来源和覆盖缺口。新结构不授权迁移既有报告；不得扫描或重写旧归档来通过校验。

## 文件与接口

- 无 BOM 的严格 UTF-8，无替换字符；首行为 `# 医疗行业雷达｜YYYY-MM-DD 至 YYYY-MM-DD`。
- 第一个二级标题前恰有一份未加粗的元数据：报告周期、出刊日期、生成时点、报告时区、窗口模式、报告范围、检索状态。字段以中文冒号分隔；值去除首尾空白后必须非空（包括空格、制表符和全角空格）。
- 出刊日期恒等于窗口结束日；默认文件名 `DHWB-Radar-YYYYMMDD.md`。窗口模式为 rolling7 / natural_week / explicit，算法见 research_contract.md。报告范围写地区、主题/对象，去首尾空白后作为归档身份；同名、同日期但范围、窗口模式或报告时区不同也不能覆盖。时区影响 cutoff 当地日历，即使自定义文件名也绑定时区原值，不自动合并时区别名。
- CLI 保留 weekly/scout 的五个必需参数、`--report-timezone`、`--allow-custom-filename`；函数 `validate_report(...) -> list[str]`，错误非空、CLI 退出 1，成功退出 0，参数语法错误退出 2。`--window-mode` 默认 rolling7；不使用 weekly 专属的 `--allow-custom-period`。自定义文件名仅用户明确指定时允许，不豁免身份、日期或来源校验。

从技能目录运行（这是合成示例，不是实际报告命令）：

```sh
python -B scripts/validate_industry_radar.py --file /session-temp/DHWB-Radar-20260910.md --period-start 2026-09-04 --period-end 2026-09-10 --issue-date 2026-09-10 --cutoff 2026-09-10T09:00:00+08:00 --window-mode rolling7 --report-timezone Asia/Shanghai
python -B -m unittest discover -s scripts -p 'test_validate_industry_radar.py' -v
```

仅用 Python 标准库和已有系统时区数据；缺少时区能力就停止，不安装依赖或猜时区。校验器只读，不检索、不创建报告/目录、不发布或计算归档回执；测试只用临时夹具。

## 表与事实字段

必需章节：结论摘要、关键事件、检索覆盖、来源、信息缺口。三张表头必须与示例一致且各一次，空表也保留表头；表头的下一物理行必须是等列分隔行，每格至少三个 `-`，两端可用 `:` 对齐。数据行紧随分隔行或上一数据行，不得用空行或代码隔断后续表体；结构区只放表和指定空结果行，不放散文。每个单元格非空，未知用“未知/未披露/不适用”并说明限制，不用假数字。单元格内不得使用未转义分隔竖线，需写为 `&#124;`。

新报告支持轻量 Markdown 子集：LF/CRLF；顶层规范二级标题和首尾带竖线的表（允许 0–3 个前导空格）；元数据仍须顶格、未加粗且位于首个可见二级标题前，头部不使用引用/列表容器。HTML 注释在最终报告中一律拒绝，代码外不支持原始 HTML 标签。围栏代码支持至少三个同种反引号或波浪号，闭合须同种且不短于开头；四空格或制表符缩进代码不提供元数据、章节、表格、空结果标记或必需正文。背景可含代码示例，但单独的代码不能使必需章节非空；行内反引号代码须在同一行闭合，不支持跨行代码跨度。不是通用 Markdown/HTML 渲染器。此过滤只作用于新源结构门，旧目标仍只核既有元数据/标题身份，不迁移或重验旧正文。

- 事件ID E1、E2…用于引用（`[E1]`）；证据强度 E1/E2 是另一列枚举，定义见研究合同。事件日期必须已知且位于窗口及 cutoff 当地日期内；发布日期为主直接来源的实际发布日期或“未知”，未知须在限制解释。次要来源日期如影响判断，在信息缺口或背景中说明。日期精度不足以判定同日 cutoff，必须人工补核。
- 事件键依研究合同归一化，区分不同项目/标段；同项目不同阶段区分但不得计成多个独立项目。校验器只按重复 ID、归一化键硬性去重，不因日期/主体/动作相同而拒绝不同项目/标段；不识别语义改写或项目别名，人工仍须对账。
- 影响列明确是推断，无足够依据可写“暂不能判断”；建议动作与传导影响按需另设章节，不强制每条有商业结论。
- 来源编号 S1…；只接受裸 HTTP(S) URL（优先 HTTPS），不是搜索结果页/Markdown 链接/带中文注释 URL，不含凭证，允许合法的方括号 IPv6 主机。URL 去重仅规范 scheme/主机名大小写并忽略 fragment，保留 path/query 内容（包括尾斜线）和端口区别，不推断联网等价性。血缘 L1…；类型 primary/secondary/marketing/unverified；访问 accessed/unavailable（只是记录的声明，不是校验器联网确认）。E1/E2 事件至少有一个已访问直接来源（primary 或仅支持发布的 marketing）；E2 至少两条可用独立血缘且非纯营销。转载不得伪造新血缘。
- 检索覆盖每行写一个实际选择的面，状态 complete/partial/blocked，说明查询、来源范围、访问/筛除结果及缺口，不要求 fabricated counts。complete 仅所有选择面 complete；partial 至少有可用覆盖和一项缺口；blocked 全部阻塞且无已访问来源或已核实事件。
- 有事件时不出现空结果标记；零事件按状态分别写独立一行：complete 用“本周期未发现符合纳入标准的公开事件”，partial 用“覆盖不完整，暂无可纳入的已核实事件”，blocked 用“检索阻塞，不能判定本期事件”。blocked 结构仅可作诊断夹具/隔离诊断，不是可成功归档的正式报告。complete 空结果也必须有覆盖依据，不等于全行业无事件。
- 背景、未来生效日期、财务期间和事件日期未知的线索放可选“背景与待核线索”章节，标明日期含义与来源，禁止计入关键事件。

## 合成定稿示例（非真实新闻）

下例使用保留示例域名，纯结构夹具，不证明链接或事实真实。

```markdown
# 医疗行业雷达｜2026-09-04 至 2026-09-10
报告周期：2026-09-04 至 2026-09-10
出刊日期：2026-09-10
生成时点：2026-09-10T09:00:00+08:00
报告时区：Asia/Shanghai
窗口模式：rolling7
报告范围：中国医疗 IT；合成采购示例
检索状态：complete
截至生成时点，当天尚未结束。

## 结论摘要
合成医院公布采购结果，不能由此认定已完成交付。

## 关键事件
| 事件ID | 事件日期 | 发布日期 | 主体 | 已核实动作 | 事件键 | 证据强度 | 来源编号 | 影响（推断） | 限制 |
|---|---|---|---|---|---|---|---|---|---|
| E1 | 2026-09-09 | 2026-09-09 | 合成医院 | 公布 A 项目包 1 中标结果；金额未披露 | 合成医院/A/包1/中标 | E1 | S1 | 可能进入合同环节 | 未核验合同与交付 |

## 检索覆盖
| 检索面 | 状态 | 查询/来源及结果说明 |
|---|---|---|
| 采购 | complete | 合成夹具：窗口内采购公告；已核验该示例结果并排除重复转载 |

## 来源
| 来源编号 | 原始链接 | 血缘 | 类型 | 访问状态 |
|---|---|---|---|---|
| S1 | https://example.org/award | L1 | primary | accessed |

## 信息缺口
合同金额与实施进度未披露；示例不代表真实访问。
```

## 人工与归档门

结构通过不证明新闻真实、URL 可访问、主张有证据、血缘独立、采购归一正确或同日事件早于 cutoff；须逐项人工复核。无强制金额、条数、双链、临床/经营指标或 ROI。

共享入口已接入 radar 自有 `metadata` / `canonical_title` / `validate_report`；从 `窗口模式` 传 `window_mode`，不传 weekly 的 `allow_custom_period`。源须 complete 或披露实际失败面、影响和恢复条件的 partial；partial 的覆盖表与信息缺口必须一致，人工核验不得省略。blocked 诊断可通过结构校验，但共享归档源硬性拒绝。旧目标要求全部七个唯一非空元数据、对应规范标题、合法状态和命名身份；不全量迁移旧正文。状态不作为替换身份：旧 blocked 诊断只有合法同身份时可被新的合格定稿替换，未知状态/跨技能伪装拒绝。新源仍须完整通过当前结构校验。

### 正式定稿 validate → commit（非预览）

执行前读 skills root 下的 `shared/references/report_archive.md`（本机绝对路径 `C:/Users/shich/.pi/agent/skills/shared/references/report_archive.md`）。共享脚本为 `C:/Users/shich/.pi/agent/skills/shared/scripts/report_archive.py`，后端为 `C:/Users/shich/.pi/agent/skills/shared/scripts/report_archive_windows.py`。下列 PowerShell 骨架仅用于已获正式自动归档意图的任务；`$draft`、`$target`、`$planFile` 必须事先解析为本次实际绝对路径，不把示例当生产目标。`$draft` 与 `$planFile` 在会话隔离临时目录，`$target` 的父目录必须存在；不自动创建缺失归档目录。目录优先级与默认既有 MEMORY 下 `raw/HealthcareIndustryRadar` 不变，不能静默另建平行路径。

```powershell
$skillDir = 'C:/Users/shich/.pi/agent/skills/hit-industry-radar'
$skillsRoot = Split-Path -Parent $skillDir
$archiveScript = Join-Path $skillsRoot 'shared/scripts/report_archive.py'
# 先按上文用真实日期、截止、时区和窗口模式运行本技能结构校验并人工复核。
$planJson = & python -B -X utf8 "$archiveScript" validate --source "$draft" --target "$target" --allow-target "$target" --skill hit-industry-radar
if ($LASTEXITCODE -ne 0) { throw 'BLOCKED: archive validate; do not commit' }
[System.IO.File]::WriteAllText($planFile, ($planJson -join "`n"), [System.Text.UTF8Encoding]::new($false))
# 只读核对快照的精确路径、身份、SHA-256 与目标/父目录，不手工编辑计划。
$receiptJson = & python -B -X utf8 "$archiveScript" commit --plan "$planFile" --allow-target "$target"
$commitExit = $LASTEXITCODE
$receiptJson
if ($commitExit -ne 0) { throw 'BLOCKED: retain receipt, draft and recovery evidence' }
if (($receiptJson -join "`n" | ConvertFrom-Json).status -ne 'COMMITTED') { throw 'BLOCKED: no committed receipt' }
```

仅用户明确指定自定义文件名时给 validate 加 `--allow-custom-filename`；`--allow-custom-period` 传给 radar 会拒绝。默认目标恒为 `DHWB-Radar-YYYYMMDD.md`（周期结束日）。替换比较技能、周期起止、出刊日、窗口模式、去首尾空白后的报告范围及报告时区。旧目标缺少身份字段或不同身份一律 fail closed，不自动改写、迁移、改名或清锁。

发布后以 UTF-8 回读正式文件，核对标题、周期、文件名、来源和非空正文及 SHA-256；只有退出 0 且 COMMITTED 才报告成功。缺 Python/校验器/时区/原生 Windows 能力或权限则停止，不安装、不普通复制、不放宽 ACL。共享门保留 owner/group/DACL/protection，不保证完整 SACL；limited-token AccessCheck 与 `actual_non_elevated_open` 分别记录，不能将提升宿主的实际打开称为非提升打开。非合作写者仍存在最后检查到 replace 的竞争窗口；POSTCOMMIT/BLOCKED 可能已改目标，保留 journal/original/candidate，不自动回滚。恢复必须明确确认并排除较新版本，重新 validate 当前目标后 commit，不能复用旧计划。

历史 hit_audit_gate.py 的 radar 分支不是当前 gate，也不是本技能依赖。
