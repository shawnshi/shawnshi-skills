---
name: hit-industry-radar
description: 检索并分析指定周期内的医疗信息化、数字健康、医疗AI、监管政策和竞争厂商动态，生成带来源、事件日期、影响判断和行动建议的行业雷达。用于本周战报、医疗IT动态、竞对监测、政策变化或行业事件扫描；需要当前信息时必须联网核验，不把旧闻改写成新事件；正式行业雷达生成后默认自动归档。
---

# 医疗行业雷达

## 执行流程

1. 默认中国医疗 IT，按采购、实施、合规和竞争价值筛选。默认含今天的滚动 7 日（rolling7）；明确“本周”用周一至截止日（natural_week），历史区间用 explicit。默认 Asia/Shanghai，固定带偏移的截止时点，禁止未来事件；日期细则见研究合同。仅范围或写入身份有实质歧义才问一个问题。
2. 检索前读 [references/research_contract.md](references/research_contract.md)：有界检索、记录覆盖；区分事件/发布日期、背景/未知日期线索，按项目/标段/阶段去重，转载不算独立证据。预算仅为规划界限，不保证运行时强制执行。
3. 分开事实、来源主张、推断和建议。金额、版本、进度未披露就保留未知；营销材料只支持“发布/宣称”，不证明临床或经营成效。重要结论核对独立证据，不为数字或条数补旧闻。
4. 正式雷达/战报默认自动归档，无需再确认；事实问答、临时分析、预览、草稿或明确不保存只在答复交付，不落盘报告。只读答复也须遵循事实与覆盖规则，不强制完整文件结构。

## 自动保存与命名

- 保存目录优先级为：用户本次指定目录 > 已确认的既有稳定归档目录 > 当前用户既有 MEMORY 工作区下的 `raw/HealthcareIndustryRadar`。解析不到唯一 MEMORY 工作区时停止写入并报告路径歧义，不另建平行目录。默认行为不授权发布、更新知识库或写入其他系统。
- 默认文件名 `DHWB-Radar-YYYYMMDD.md`，日期恒为窗口结束日。
- 正式定稿按 [references/report_schema.md](references/report_schema.md) 在当前会话隔离临时目录生成同名 UTF-8 文件，运行 [scripts/validate_industry_radar.py](scripts/validate_industry_radar.py)，再人工核验事实。结构通过不是写入授权或安全发布能力。
- 仅 complete 或显式披露缺口的 partial 正式定稿进入共享安全归档；blocked 检索只交付诊断与恢复条件，不能归档成成功报告。按 report_schema.md 的绝对路径与 CLI 顺序运行共享 `validate --skill hit-industry-radar`，将成功 stdout 保存为隔离临时 JSON 计划，再 `commit --plan`；两步逐次使用相同精确 `--allow-target`。预览/草稿/不保存不执行报告落盘或归档 validate/commit。
- 目标父目录必须已经存在；缺目录、路径歧义、校验器/Windows 权限能力缺失均 BLOCKED，不自动建目录、安装依赖、冒用 skill、复制、rename/replace 或放宽权限绕过。保留隔离定稿和失败回执。
- 保存前由门禁检查目标。替换身份必须同时匹配技能、周期起止、出刊日（结束日）、窗口模式、去首尾空白的非空报告范围和报告时区；自定义文件名不豁免身份。旧目标缺元数据、标题不符或不同身份都拒绝，不自动迁移旧报告、改名或覆盖。`--allow-custom-period` 为 weekly 专属，radar 传入即拒绝。
- 发布后以 UTF-8 重新读取正式文件，复核标题、时间窗口、文件名、来源链接和非空内容，并计算 SHA-256。最终答复报告绝对路径、验证结果和哈希。

共享资源从本技能绝对目录的父目录（skills root）解析，不从 radar 子目录拼接。本机解析值：

- `shared/scripts/report_archive.py` → `C:/Users/shich/.pi/agent/skills/shared/scripts/report_archive.py`（唯一 validate/commit 入口）。
- `shared/scripts/report_archive_windows.py` → `C:/Users/shich/.pi/agent/skills/shared/scripts/report_archive_windows.py`（复用原生后端，不复制）。
- `shared/references/report_archive.md` → `C:/Users/shich/.pi/agent/skills/shared/references/report_archive.md`（执行前读权限、事务与恢复边界）。
- `shared/scripts/test_report_archive.py` → `C:/Users/shich/.pi/agent/skills/shared/scripts/test_report_archive.py`（仅临时夹具回归）。

## 按需资源与验收

S-T-C 分析按需读 [references/stc_framework.md](references/stc_framework.md)，保持厂商中立。`assets/` 只读相关地区/对象提示，不是事实来源。不得全量加载资产或盲扫既往归档、个人历史。

行为验收见 [evals/benchmark.json](evals/benchmark.json) 和 [evals/evals.json](evals/evals.json)；确定性测试见 [scripts/test_validate_industry_radar.py](scripts/test_validate_industry_radar.py)。历史 hit_audit_gate.py 的 radar 分支不是当前验收入口，本技能不依赖其数字、口号或双链要求。

## 完成检查

- 来源、日期、证据血缘、采购阶段和金额口径经人工复核；403/超时不等于“无事件”，结构通过不证明事实。
- 明确 complete（声明范围检索完成，允许成功空结果）、partial（覆盖缺口）或 blocked（无可用检索证据），不把失败包装为空结果。
- 内容状态与归档状态分开；只有 commit 退出 0 且回执 `status=COMMITTED` 才报告归档成功。记录绝对目标、SHA-256 和真实访问证据；limited-token AccessCheck 不等于实际非提升进程打开。SACL 不在保证范围，非合作写者仍有竞争窗口；POSTCOMMIT 失败可能已写入，保留证据而非自动回滚。
