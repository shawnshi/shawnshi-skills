# CLI reference

脚本可从任意当前工作目录执行。始终使用绝对 `SKILL_DIR` 和绝对输入/输出路径，避免依赖 shell 的路径分隔或技能目录作为 cwd。

## Bash / zsh

```bash
SKILL_DIR=/root/.codex/skills/remote-skills/skill-6a8ea3e569d481919470b66fd82e0991

# 生成可通过结构校验的 v2 草稿；相同 seed 产生稳定 Slide_ID
python3 "$SKILL_DIR/scripts/scaffold.py" \
  --mode full --slides 8 --topic "AI governance" --seed "governance-v1" \
  --output /absolute/path/outline.md

# 单文件、目录、标准输入或多文件批量结构校验
python3 "$SKILL_DIR/scripts/validator.py" /absolute/path/outline.md
python3 "$SKILL_DIR/scripts/validator.py" /absolute/path/deck-a.md /absolute/path/deck-b.md
python3 "$SKILL_DIR/scripts/validator.py" - < /absolute/path/outline.md

# 仅预览修复后的页码；显式 --write 才会原子替换输入文件
python3 "$SKILL_DIR/scripts/renumber.py" /absolute/path/outline.md
python3 "$SKILL_DIR/scripts/renumber.py" /absolute/path/outline.md --write

# 仅在需要机器交接或实际 PPT 时生成 JSON
python3 "$SKILL_DIR/scripts/build-deck.py" /absolute/path/outline.md \
  --output /absolute/path/blueprint_bundle.json

# 与上一版 JSON 比较，分别报告变化和删除的稳定 Slide_ID
python3 "$SKILL_DIR/scripts/build-deck.py" /absolute/path/outline.md \
  --output /absolute/path/blueprint_bundle-v2.json \
  --previous /absolute/path/blueprint_bundle-v1.json

# 将 v1 草稿迁移为新的 v2 起点；迁移后必须人工复核
python3 "$SKILL_DIR/scripts/migrate_v1.py" /absolute/path/outline-v1.md \
  --output /absolute/path/outline-v2.md
```

## PowerShell

```powershell
$SkillDir = "/root/.codex/skills/remote-skills/skill-6a8ea3e569d481919470b66fd82e0991"

python "$SkillDir/scripts/scaffold.py" --mode one_pager --slides 1 `
  --topic "AI governance" --output "C:\work\outline.md"

python "$SkillDir/scripts/validator.py" "C:\work\outline.md"

Get-Content -Raw "C:\work\outline.md" |
  python "$SkillDir/scripts/validator.py" -

python "$SkillDir/scripts/renumber.py" "C:\work\outline.md" --write

python "$SkillDir/scripts/build-deck.py" "C:\work\outline.md" `
  --output "C:\work\blueprint_bundle.json"

python "$SkillDir/scripts/migrate_v1.py" "C:\work\outline-v1.md" `
  --output "C:\work\outline-v2.md"
```

## Input and report behavior

- `validator.py` 接受一个或多个 Markdown 文件、包含 `outline.md` 的目录，或一次标准输入 `-`；批量报告包含逐来源结果和总计。
- `build-deck.py` 只接受单个蓝图来源，输出 JSON handoff，不生成 `.pptx`。
- `scaffold.py` 生成 `draft` 骨架；骨架中的假设和开放项不是业务结论。
- 只交付大纲时不要运行 `build-deck.py`；经过结构校验的 `outline.md` 就是交付物。
- `Status: draft` 的未结构化占位符产生警告；`Status: final` 时阻断。非法枚举、日期、引用、布局和区块顺序始终阻断。
- 报告固定声明 `validation_scope: structural`。退出码为零也不代表事实、合规、视觉或发布审核已经完成。

## Safe output and incremental work

- 写入型脚本默认不覆盖已有输出；确认目标后才使用 `--force`。`renumber.py` 的原地修改使用单独的 `--write`。
- 输入和输出必须是不同文件；不要把输出指向输入路径、硬链接、符号链接或其目录别名。
- 写入采用独占锁和同目录原子替换；并发任务应使用独立输出路径。异常遗留的锁文件需先确认没有活动写入者，再由操作者处理。
- `build-deck.py --previous` 依赖稳定 `Slide_ID` 分别计算 `changed_slide_ids` 与 `removed_slide_ids`；重排页面只修改 `Page`，不要重建 ID。
- JSON 只供后续能力读取，不要把它改名为 `.pptx` 或称作演示文稿。
