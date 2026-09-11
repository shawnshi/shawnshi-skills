# discovery-call

医疗卫生信息化售前客户研究与重要拜访准备技能，当前为 **2.6.2 独立候选／限定内部试用**。入口规则见 [SKILL.md](SKILL.md)，本地工程记录与候选交付边界见随包的 [真实发布验收](references/release-acceptance.md)。前期审计报告和候选交付说明未随本包提供，不将其视为可回查的本地证据。

## 四种成果

- `briefing`：会前速览。
- `standard_visit`：标准拜访包。
- `strategic_account`：战略客户包；无会议时使用账户经营计划。
- `letter`：有研究依据的内部待审核客户信，不自动发送。

脚本负责初始化、规划、校验、审批声明绑定和事务提交，不会自行联网完成研究，也不证明企业连接器可用。研究与真实人工审核由具备相应能力及授权的运行环境负责。

## 新建

在本目录运行 Python；原附件记录的环境为 Windows/Python 3.13.12；本轮执行环境与结果见 references/release-acceptance.md，不把一个环境的通过外推到另一环境。运行脚本仅使用标准库。任务时区需要本机可用的 IANA 时区数据。若无法解析时区，不要猜测当地日期；可明确提供 `--evidence-cutoff-date YYYY-MM-DD` 并按 UTC 口径执行。

```bash
python scripts/init_workspace.py "客户规范名称" --output-root "工作区父目录" --business-mode briefing --task-timezone Asia/Shanghai --runtime-owner "实际负责人" --json
```

将 briefing 换成其他模式即可。没有内部三重授权及真实可执行连接器时，保持公开资料路径。不要为通过门禁填写虚假负责人、日期或审批人。

## 写入与续建

研究模块只改隔离候选，不直接覆盖正式 Markdown。主流程读取当前 manifest 的 `transaction_sequence` 和原文件 SHA-256，通过 `commit_run.py` 的两个 expected 参数提交。完整命令与恢复规则见 [SKILL.md](SKILL.md)。

自然过期时按原模式显式 `--resume --refresh-modules institution,leader` 定向刷新；只选实际存在且需要刷新的研究模块。证据日期不能仅因续建就更新，任务时区不能被续建或候选切换。`--recover` 只修复事务/状态，不是绕过哈希、身份或权限校验的开关。

## 草稿与正式交付

```bash
# 先检查含唯一briefing标记的UTF-8候选正文；也支持stdin（参数-）。
python -B scripts/check_briefing_draft.py "候选正文.md"

# 普通校验通过的草稿仍不是正式可用成果。
python scripts/validate_outputs.py "工作区" --json

# 只有取得真实人工审核并完成相应审批、mark-ready后，才做正式校验。
python scripts/validate_outputs.py "工作区" --strict --json

# 已通过strict的速览：stdout输出，不发送，不修改正文。
python scripts/export_briefing.py "工作区" --format markdown
python scripts/export_briefing.py "工作区" --format html
```

速览必须置于总报告唯一的 briefing:start/end 注释区，包含可回溯 claim_id；超出1600字符或折行后48行会拒绝导出。HTML按A4、100%缩放、关闭浏览器页眉页脚打印；任意重排需要重新检查页数。输出包含内部研究信息，不能据此直接向客户外发。

草稿形状检查不会修改输入、解析来源台账或完成审批。超限先减少非必要空行再重查，不删除关键事实、不裁切。正文使用台账定义的完整CLM编号，不新建C01/S01等简称；未知主张不能为通过形状检查而伪造。

所有正式模式都需登记 account_owner 和唯一主动作、owner、有效 due_date；日期格只写YYYY-MM-DD，原始“前”、时区及其他截止条件放入依赖/备注。策略备选单独列示。未知预算可保留为待验证，不必编造机会。

## 本地验证

```bash
python -B scripts/run_tests.py --json --verbosity 2 --failfast
python -B scripts/research_plan.py validate-config
```

测试仅创建合成临时工作区。请在机器保持唤醒时运行；合盖进入 Modern Standby 会导致墙钟超时。不要用提高超时或自动批准掩盖失败。

## 缓存调用

主流程可通过 `SourceCache.lookup_many(locators)` 按批查询，最多256项；每批重新读取。默认缓存5000项／8 MiB，TTL和内容哈希不符为miss，坏缓存或超限为错误。缓存单写者，不允许研究模块并发读改写同一文件。

本地测试通过不替代真实客户试点、人工权限核验、连接器权限测试或外发批准。

本版基于用户提供的2.6.0附件独立修订，不替换已安装的其他同名版本。候选构建入口见 references/candidate-workflow.md；发布未完成项见 references/release-acceptance.md。审批命令由真人执行。
