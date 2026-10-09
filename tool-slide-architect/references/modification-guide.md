# Revision and migration guide

## Revise an existing deck

1. 先执行主入口的读取前隐私门，再读取源大纲或演示文稿，建立 `Slide_ID → 当前页码 → 页面任务` 清单。
2. 给每页标记 `keep / rewrite / merge / split / move / remove / add`。
3. 锁定 `Must_Keep`、引用、合规声明、模板规则和已确认数字。
4. 先修复核心主张、章节顺序、证据链和叙事终点，再改标题、正文与视觉。
5. 保持既有 `Slide_ID` 稳定；移动页面只改 `Page`，新增页面使用新 ID，删除页面不回收 ID。
6. 对修改过的 Claim、Evidence、Decision、Risk 和 Asset 做逐项复核。
7. 页面重排后用 `scripts/renumber.py` 修复连续页码并保持 `Slide_ID`；再运行完整结构校验。结构通过不等于内容或视觉可发布。
8. 用户需要实际 `.pptx` 时，生成 JSON handoff，构建并完成物理 QA。

## Change control

| 变更 | 最低复核 |
|---|---|
| 改标题或 Takeaway | 是否改变事实强度或承诺 |
| 改数字或图表 | 来源、口径、单位、时间和范围 |
| 合并页面 | 是否丢失限定条件、风险或引用 |
| 拆分页面 | Claim 与 Evidence 是否仍正确关联 |
| 更换样式或模板 | 引用、保密标记、品牌和可访问性 |
| 更换截图或图片 | 权利、脱敏和适用场景 |
| 改 Decision | 请求、责任人、计划日期和授权边界 |

## Migrate v1 to v2

v1 只有 `Cover / Content / Closing` 和扁平 `Evidence / Trust Anchor`。迁移不是字段改名，必须重建主张、证据和拓扑。

从任何工作目录调用迁移脚本：

```bash
SKILL_DIR="$HOME/.pi/agent/skills/tool-slide-architect"
python "$SKILL_DIR/scripts/migrate_v1.py" /absolute/path/outline-v1.md \
  --output /absolute/path/outline-v2.md
```

PowerShell：

```powershell
$SkillDir = Join-Path $HOME ".pi/agent/skills/tool-slide-architect"
python "$SkillDir/scripts/migrate_v1.py" "C:\work\outline-v1.md" `
  --output "C:\work\outline-v2.md"
```

路径与解释器以 [cli-reference.md](cli-reference.md) 的实际环境约定为准；输入为 UTF-8 文件，不通过未验证编码的 PowerShell 管道。

迁移保留已提供的比例、时长、保密级别、资料截止日期、模板、必须保留内容及可映射追踪字段，重算页数并始终生成 `draft`。缺失的保密级别暂按 `restricted` 处理并建立开放项；其他关键缺失值用可检测占位符表示，不替用户确定业务约束。无法映射的元数据、重复字段或非法保留字段值必须阻断，不静默丢弃。原版本的 Prepared/Reviewed 主体只保留为开放项中的来源记录，不代表审核了迁移稿；Revision 保留旧值并追加迁移标记。

迁移后必须人工完成：

- 核对保留下来的约束，补齐缺失元数据和新稿实际作者/复核主体，完成复核后才改变 `Status`。
- 把扁平证据拆为 Claim、Evidence、Open Item 和 Risk。
- 为资产补充权利和脱敏状态。
- 把旧 Content 页改为最贴切的新页面类型。
- 建立明确叙事终点；检查附录和参考文献位置。
- 清除最终稿中的未结构化占位符。

迁移脚本输出只是结构化起点，不是已审核蓝图。
