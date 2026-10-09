# CLI reference

脚本可从任意当前工作目录执行。以 Pi 提供的实际技能位置确定绝对 `SKILL_DIR` 和输入/输出路径；以下使用默认用户技能目录，若技能从包或自定义目录加载，必须替换变量。先确认实际 Python 3 解释器；Bash 示例用 `python`，只有本机提供 `python3` 时才改用该命令，不假定 WindowsApps 别名可用。

## Bash / zsh

```bash
SKILL_DIR="$HOME/.pi/agent/skills/tool-slide-architect"

# 生成可通过结构校验的 v2 草稿；相同 seed 产生稳定 Slide_ID
python "$SKILL_DIR/scripts/scaffold.py" \
  --mode full --slides 8 --topic "AI governance" --seed "governance-v1" \
  --output /absolute/path/outline.md

# 单文件、目录、标准输入或多文件批量结构校验
python "$SKILL_DIR/scripts/validator.py" /absolute/path/outline.md
python "$SKILL_DIR/scripts/validator.py" /absolute/path/deck-a.md /absolute/path/deck-b.md
python "$SKILL_DIR/scripts/validator.py" - < /absolute/path/outline.md

# 仅预览修复后的页码；显式 --write 才会原子替换输入文件
python "$SKILL_DIR/scripts/renumber.py" /absolute/path/outline.md
python "$SKILL_DIR/scripts/renumber.py" /absolute/path/outline.md --write

# 仅在需要机器交接或实际 PPT 时生成 JSON
python "$SKILL_DIR/scripts/build-deck.py" /absolute/path/outline.md \
  --output /absolute/path/blueprint_bundle.json

# 与上一版 JSON 比较，分别报告变化和删除的稳定 Slide_ID
python "$SKILL_DIR/scripts/build-deck.py" /absolute/path/outline.md \
  --output /absolute/path/blueprint_bundle-v2.json \
  --previous /absolute/path/blueprint_bundle-v1.json

# 将 v1 草稿迁移为新的 v2 起点；迁移后必须人工复核
python "$SKILL_DIR/scripts/migrate_v1.py" /absolute/path/outline-v1.md \
  --output /absolute/path/outline-v2.md
```

## PowerShell

```powershell
$SkillDir = Join-Path $HOME ".pi/agent/skills/tool-slide-architect"

python "$SkillDir/scripts/scaffold.py" --mode one_pager --slides 1 `
  --topic "AI governance" --output "C:\work\outline.md"

python "$SkillDir/scripts/validator.py" "C:\work\outline.md"

# 中文材料直接传文件路径，由脚本按 UTF-8 读取；不经 PowerShell 文本管道。
python "$SkillDir/scripts/validator.py" "C:\work\deck-a.md" "C:\work\deck-b.md"

python "$SkillDir/scripts/renumber.py" "C:\work\outline.md" --write

python "$SkillDir/scripts/build-deck.py" "C:\work\outline.md" `
  --output "C:\work\blueprint_bundle.json"

python "$SkillDir/scripts/migrate_v1.py" "C:\work\outline-v1.md" `
  --output "C:\work\outline-v2.md"
```

## Input and report behavior

- `validator.py` 接受一个或多个 UTF-8 Markdown 文件、包含 `outline.md` 的目录，或一次标准输入 `-`；批量报告包含逐来源结果和总计。Windows PowerShell 5.1 默认管道编码可能是 ASCII，中文优先使用文件参数。只有上游读取、发送和 Python 接收均已验证 UTF-8 往返时才使用标准输入；`Get-Content -Encoding UTF8` 单独不能修复管道输出编码。
- `build-deck.py` 只接受单个蓝图来源，输出 JSON handoff，不生成 `.pptx`。
- `scaffold.py` 生成 `draft` 骨架；未填业务内容、责任人、计划日期、时长、语言和截止日期均用可检测的 `{{...}}` 标记，不能仅修改 Status 就通过 final 校验。骨架中的记录不是业务结论；完成后按真实材料设置类型、状态与证据关联。
- 轻量故事线/标题建议不使用本 CLI，不默认保存。完整蓝图才使用 v2 和结构校验；没有机器交接请求时不运行 `build-deck.py`。`outline.md` 是格式契约，用户不保存时交付已校验正文而不是创建文件。
- `Status: draft` 的未结构化占位符产生警告；`Status: final` 时阻断。非法枚举、日期、引用、布局和区块顺序始终阻断。
- 报告固定声明 `validation_scope: structural`。退出码为零也不代表事实、合规、视觉或发布审核已经完成。

## Safe output and incremental work

- 写入型脚本默认不覆盖已有输出；确认目标后才使用 `--force`。`renumber.py` 的原地修改使用单独的 `--write`。
- 输入和输出必须是不同文件；不要把输出指向输入路径、硬链接、符号链接或其目录别名。
- 写入采用独占锁和同目录原子替换；并发任务应使用独立输出路径。异常遗留的锁文件需先确认没有活动写入者，再由操作者处理。
- `build-deck.py --previous` 依赖稳定 `Slide_ID` 分别计算 `changed_slide_ids` 与 `removed_slide_ids`；重排页面只修改 `Page`，不要重建 ID。全局 metadata 或 style instructions 变化时，保守标记所有现存页，并在 `change_set` 中返回 `global_changed_sections` 与 `requires_full_rebuild: true`；旧包缺少全局上下文也要求全量重建，畸形上下文则阻断。全局信息及页面内容都相同时变更集为空。
- JSON 只供后续能力读取，不要把它改名为 `.pptx` 或称作演示文稿。
