---
name: hit-industry-radar
description: 检索指定周期的医疗IT政策、厂商及采购项目阶段事件，生成带来源、事件日期和影响判断的行业雷达。适用于竞对监测、项目阶段追踪和事件扫描；管理层综合周刊、论文证据侦察、基线优先日简报分别由对应技能处理，模糊请求先确定交付物。需要当前信息时必须联网核验，不把旧闻改写成新事件；正式行业雷达生成后默认自动归档。
---

# 医疗行业雷达

## 交付物与路由

- 本技能交付事件/项目阶段雷达：按政策动作、厂商发布、采购/实施阶段组织证据，不等同于管理层综合周刊。
- 管理与经营决策综合周刊用 `hit-weekly-brief`；论文证据、版本及研究假设用 `hit-lectures-scout`；基线优先、带历史去重的技术/医疗数字化日简报用 `personal-intelligence-hub`。按交付物与证据对象路由，不按“本周/动态”关键词隐式同时运行或重复检索。
- 请求仍有实质歧义时只问交付物；确认雷达后沿用下述窗口、状态和命名。路由说明不统一其他技能的周期、归档身份或中间态；本技能预览/不保存仍只读退出，不启动其他技能生产流程。

## 执行流程

1. **确定窗口与范围**：默认中国医疗 IT，按采购、实施、合规和竞争价值筛选。默认含今天的滚动 7 日（rolling7）；明确“本周”用周一至截止日（natural_week），历史区间用 explicit。默认 Asia/Shanghai，固定带偏移的截止时点，禁止未来事件；日期细则见研究合同。仅范围或写入身份有实质歧义才问一个问题。
2. **检索前读研究合同并定预算**：先读 [references/research_contract.md](references/research_contract.md)，按其中的默认规划上限分配发现、精读与独立核验额度，先减少低价值候选，不为补额自动扩张。预算是规划界限，不保证运行时强制执行。
3. **检索与事实分层**：分开事实、来源主张、推断和建议；金额、版本、进度未披露就保留未知；营销材料只支持“发布/宣称”，不证明临床或经营成效。重要结论核对独立证据，不为数字或条数补旧闻。
4. **先定交付模式**：正式雷达/战报默认自动归档，无需再确认；事实问答、临时分析、预览、草稿或明确不保存只在答复交付，不落盘报告。只读答复也须说明窗口、截止、来源和覆盖缺口，但不强制完整文件结构。
5. **正式分支先做只读预检**：正式雷达在检索前只读确认 Python 3、系统时区数据、自有校验器 `scripts/validate_industry_radar.py`、skills root 下共享归档入口 `shared/scripts/report_archive.py`、唯一目标路径及其父目录存在，并记录结论。预检不是结构校验的替代，也不产生写入授权；不得用试写、`commit` 或落盘探测能力。能力不足按 BLOCKED 报告，不改用复制、改名或放宽权限。预览与只读答复不触发预检。
6. **正式定稿归档**：见下节；结构、身份、事务与恢复细则以 report_schema.md 与共享契约为准，本节不重复。

## 正式定稿与归档

- 保存目录优先级为：用户本次指定目录 > 已确认的既有稳定归档目录 > 当前用户既有 MEMORY 工作区下的 `raw/HealthcareIndustryRadar`。解析不到唯一 MEMORY 工作区时停止写入并报告路径歧义，不另建平行目录。默认行为不授权发布、更新知识库或写入其他系统。
- 归档前完整读取 [../shared/references/report_archive.md](../shared/references/report_archive.md)（路径解析、身份、事务、权限与恢复的唯一权威），并按 [references/report_schema.md](references/report_schema.md) 在会话隔离临时目录生成 UTF-8 定稿、运行 [scripts/validate_industry_radar.py](scripts/validate_industry_radar.py) 再人工核验事实。结构通过不是写入授权或安全发布能力。
- 只有 complete 或显式披露缺口的 partial 正式定稿进入共享安全归档；blocked 检索只交付诊断与恢复条件，不能归档成成功报告。validate → commit 的参数、顺序、身份比较、同一精确 `--allow-target`、单写者与恢复边界全部沿用共享契约。
- 本技能相对共享契约的差异只有三项：默认文件名 `DHWB-Radar-YYYYMMDD.md`（日期恒为窗口结束日）、身份另含窗口模式与报告范围、拒绝 weekly 专属的 `--allow-custom-period`。自定义文件名不豁免身份。
- 预览/草稿/不保存不执行落盘或归档 validate/commit；目标父目录必须已经存在。缺目录、路径歧义、校验器或平台权限能力缺失均 BLOCKED，不自动建目录、安装依赖、冒用 skill、复制、rename/replace 或放宽权限绕过；保留隔离定稿和失败回执。
- 发布后以 UTF-8 重新读取正式文件，复核标题、时间窗口、文件名、来源链接和非空内容，并计算 SHA-256；最终答复报告绝对路径、验证结果和哈希。

## 按需资源

- S-T-C 分析按需读 [references/stc_framework.md](references/stc_framework.md)，保持厂商中立。
- `assets/` 是子模式检索提示与建议返回结构，不是事实来源，也不改变本技能窗口、预算与保存边界。只在需要时按对象读取一份：国内厂商 `Task_china_hit.md`，全球厂商 `Task_global_hit.md`，用户明确指定的厂商 `Task_winning_baseline.md`；不全量加载资产。
- 不盲扫既往归档或个人历史。共享资源以本技能目录（`skill_dir`）为基准解析到 skills root 的 `shared/`，不使用记忆化的本机绝对路径；解析不到或路径歧义即停止。
- 行为验收见 [evals/benchmark.json](evals/benchmark.json) 和 [evals/evals.json](evals/evals.json)；确定性测试见 [scripts/test_validate_industry_radar.py](scripts/test_validate_industry_radar.py) 与共享的 `../shared/scripts/test_report_archive.py`（仅临时夹具）。历史 `scripts/hit_audit_gate.py` 的 radar 分支已无调用方，不是本技能的验收入口。

## 完成检查

- 来源、日期、证据血缘、采购阶段和金额口径经人工复核；403/超时不等于“无事件”，结构通过不证明事实。
- 明确 complete（声明范围检索完成，允许成功空结果）、partial（覆盖缺口）或 blocked（无可用检索证据），不把失败包装为空结果。
- 内容状态与归档状态分开；只有 commit 退出 0 且回执 `status=COMMITTED` 才报告归档成功，并记录绝对目标、SHA-256 与真实访问证据。权限、SACL、并发窗口与 POSTCOMMIT 残留下限以共享契约为准。
