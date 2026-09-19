# 正式周报编制与归档

编制正式周报或完整模板预览前，完整读取本文件、[模板](template.md)及[正式模板填充](research-workflow.md#正式模板填充)；预览仍严格只读，不执行临时落盘或归档命令。正式归档前必须完整读取[共享契约](../../shared/references/report_archive.md)。路径变量均从 skill_dir 解析，不以本参考目录解析。

## 自动保存与命名

- 目录优先级：用户本次指定 > 已确认的稳定归档目录 > 唯一既有 MEMORY 工作区的 `raw/DigitalHealthWeeklyBrief`。路径歧义即 BLOCKED，不另建平行目录；不授权对外发布、知识库或其他系统写入。
- 默认文件名 `DHWB-YYYYMMDD.md`，日期等于出刊日及周期结束日，不是生成日。文件名、标题周期、出刊日、截止说明联动，任一修改后全部重验。
- 会话隔离临时目录生成同名 UTF-8 定稿，经自有校验器及共享门禁归档；禁止自行 rename/replace/shutil/复制。保留私有草稿，其权限不得成为正式文件权限。
- 归档身份注意：当前共享归档身份未绑定专题名称与报告时区，同一出刊日仅对应单一标准周报档期。同日不同地区或受众周报若需并存，在多刊归档合同批准前须使用自定义文件名或独立目录，不得擅自修改既有受保护归档身份规则。
- 仅同一技能、周期、档期且全部门禁通过才可替换既有目标；身份不明、不同语义、快照漂移即 BLOCKED，不静默覆盖/改名。旧目标只核身份；缺元数据或规范标题须人工身份复核，不自动重写历史以通过新 schema。
- 提交后回读 UTF-8、核对 SHA-256 与 Windows 安全描述符/访问证据。答复给绝对路径、状态、哈希及访问证据限制；仅退出 0 且 `COMMITTED` 才算成功。BLOCKED 保留草稿/回执/恢复证据，不盲目回滚；POSTCOMMIT 失败可能已写入。

未来正式报告的事件表每行必须**六列非空**：事件日期、主体与已核实动作、事实或来源主张、分析判断、证据强度、直接来源；最后一列须有直接 `http(s)` URL（允许 Markdown 链接，不接受仅来源编号或搜索结果页）。URL 形式不代表原文可访问或已经核验。旧目标只核身份，不强制迁移正文。

[合成示例](../examples/DHWB-Reference.md) 仅演示格式，不是事实来源或待归档报告；assets 是检索提示，不得流入正式正文。

## 验证门禁

保存前必须满足以下断言：

- 起始日不晚于结束日；默认同一周周一至周日，出刊日等于结束日及文件名日期；自定义须用户明确指定。
- 规范标题与周期一致；首个二级标题前各一次未加粗字段：`报告周期`、`出刊日期`、`生成时点`、`报告时区`。精确格式及标题跨月/跨年规则见填充说明，不以代码围栏或缩进代码块提供元数据/有效事件，正式文件不保留 HTML 注释。
- cutoff 为带偏移 ISO-8601，不晚于真实系统当前时间；与正文生成时点表示同一时刻。默认 `Asia/Shanghai`，日历日期及完结判断按报告时区换算，cutoff 日期不早于起始日。未完结声明须位于头部，不可被正文替代。
- 唯一 `## 关键事件与来源` 收纳全部本期日期行，六列非空且直接 URL。当有事件行存在时，必须包含唯一合法的六列表头及紧随其后的分隔行；无合格事件时仅一次独立行写 `本周期未发现符合纳入标准的事件`，可留表头，不与事件行并存。其他节的旧事件标背景，不替代本期结果。
- 本期事件日期须在起始日、结束日及截止日交集内；历史补刊 cutoff 可晚于结束日，但不得扩大事件窗口。校验器仅核日期/结构；原始来源时刻、可访问性、真实性及证据门仍须人工核验，结构通过不等于研究完成。

使用绝对路径：自有 `scripts/validate_weekly_brief.py`、`scripts/test_validate_weekly_brief.py` 从本技能绝对目录 `skill_dir` 解析；共享脚本 `report_archive.py`、`report_archive_windows.py`、`test_report_archive.py` 从 `skill_dir.parent / "shared/scripts"` 解析，共享文档从 `skill_dir.parent / "shared/references/report_archive.md"` 解析，不依赖 cwd。归档前必须读 [共享契约](../../shared/references/report_archive.md)。

```powershell
python -B "$validator" --file "$draft" --period-start YYYY-MM-DD --period-end YYYY-MM-DD --issue-date YYYY-MM-DD --cutoff "带偏移ISO-8601时间" --report-timezone Asia/Shanghai
```

`--report-timezone` 默认 `Asia/Shanghai`；其他有效 IANA 名须与正文一致。`Z`/其他偏移可表示同一 cutoff；生产无 `--now`，历史补刊不得伪造系统时钟。

如用户明确指定自定义周期，附加 `--allow-custom-period`；如用户明确指定非标准文件名，附加 `--allow-custom-filename`。随后必须按共享文档执行归档 `validate`（stdout JSON 计划）→ `commit --plan 文件 --allow-target 精确目标`。同样的用户授权自定义选项须传给归档 validate。

能力缺失或非 Windows 一律 BLOCKED，人工检查不能替代发布门禁。严格 owner/group/DACL/protection 相等及访问证据门不得放宽；不自动安装、提权、扩 ACL、清锁或不安全回退。共享契约定义并发/恢复和公共来源边界；早期检查通过不保证运行可归档。

