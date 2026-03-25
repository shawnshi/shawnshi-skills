#!/usr/bin/env python3
"""
Self-Improving Skill — Improver

从人类修改中提取规则，更新目标 SKILL.md。

用法:
    python3 improve.py extract [--days 7] [--date 2026-03-17]
    python3 improve.py auto                  # 提取 + 自动应用 P0（cron 用）
    python3 improve.py show                  # 查看所有提案
    python3 improve.py apply <proposal_id>   # 应用指定提案
    python3 improve.py rollback              # 回滚上次应用

环境变量:
    SKILL_LOG_DIR      — 日志目录
    SKILL_TARGET_PATH  — 目标 SKILL.md 路径
    SKILL_PROPOSAL_DIR — 提案目录
    SKILL_BACKUP_DIR   — 备份目录
"""

import sys
import json
import os
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# 默认路径 — 自动检测 Gemini CLI 物理主权路径
def _detect_base():
    """Gemini CLI 适配：默认指向 MEMORY 目录"""
    if os.environ.get("SKILL_BASE_DIR"):
        return Path(os.environ["SKILL_BASE_DIR"])
    return Path("C:/Users/shich/.gemini/MEMORY")

_BASE = _detect_base()
DEFAULT_LOG_DIR = _BASE / "skill_audit" / "style_runs" / "personal-writing-assistant"
DEFAULT_PROPOSAL_DIR = _BASE / "skill_audit" / "style_proposals" / "personal-writing-assistant"
DEFAULT_BACKUP_DIR = _BASE / "skill_audit" / "style_backups" / "personal-writing-assistant"


def get_paths(args=None):
    """解析所有路径配置"""
    skill_name = "personal-writing-assistant"
    if args and hasattr(args, 'skill') and args.skill:
        skill_name = Path(args.skill).name

    base = _detect_base() / "skill_audit"

    log_dir = Path(os.environ.get("SKILL_LOG_DIR",
                   getattr(args, 'log_dir', None) or
                   str(base / "style_runs" / skill_name)))

    proposal_dir = Path(os.environ.get("SKILL_PROPOSAL_DIR",
                        getattr(args, 'proposal_dir', None) or
                        str(base / "style_proposals" / skill_name)))

    backup_dir = Path(os.environ.get("SKILL_BACKUP_DIR",
                      getattr(args, 'backup_dir', None) or
                      str(base / "style_backups" / skill_name)))

    # 目标 SKILL.md
    if os.environ.get("SKILL_TARGET_PATH"):
        target = Path(os.environ["SKILL_TARGET_PATH"])
    elif args and hasattr(args, 'target') and args.target:
        target = Path(args.target)
    elif args and hasattr(args, 'skill') and args.skill:
        target = Path(args.skill) / "SKILL.md"
    else:
        # 默认硬锁 personal-writing-assistant
        target = Path("C:/Users/shich/.gemini/skills/personal-writing-assistant/SKILL.md")

    for d in (log_dir, proposal_dir, backup_dir):
        d.mkdir(parents=True, exist_ok=True)

    return log_dir, proposal_dir, backup_dir, target


def read_log_entries(log_file):
    if not log_file.exists():
        return []
    entries = []
    with log_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def collect_edits(log_dir, days=1, date_str=None):
    """收集有实际修改的 final/edited 记录"""
    edits = []
    if date_str:
        log_file = log_dir / f"{date_str}.jsonl"
        entries = read_log_entries(log_file)
        edits.extend([e for e in entries
                      if e["type"] in ("final", "edited") and not e.get("no_change")])
    else:
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            log_file = log_dir / f"{date}.jsonl"
            entries = read_log_entries(log_file)
            edits.extend([e for e in entries
                          if e["type"] in ("final", "edited") and not e.get("no_change")])
    return edits


def call_llm(prompt, timeout=180):
    """调用 LLM — 自动检测可用的 CLI (gemini / claude / llm)"""
    # 优先级: gemini CLI → claude CLI → generic llm CLI
    candidates = [
        ["gemini", "prompt", "--stdin"],               # Gemini CLI
        ["claude", "--print", "--model", "sonnet"],  # Claude Code
        ["claude", "--print"],                         # Claude Code (default model)
        ["llm", "-m", "claude-sonnet"],               # simon willison's llm CLI
        ["llm"],                                       # llm CLI default
    ]
    for cmd in candidates:
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=timeout, encoding='utf-8')
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # fallback: 如果 IMPROVE_LLM_CMD 环境变量设置了，用它
    custom_cmd = os.environ.get("IMPROVE_LLM_CMD")
    if custom_cmd:
        try:
            result = subprocess.run(custom_cmd.split(), input=prompt,
                                    capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    print("❌ LLM 调用失败。支持的方式：")
    print("   - 安装 Claude Code CLI (claude --print)")
    print("   - 安装 llm CLI (pip install llm)")
    print("   - 设置 IMPROVE_LLM_CMD 环境变量")
    return None


def extract_improvements(args):
    log_dir, proposal_dir, _, target = get_paths(args)
    days = getattr(args, 'days', 1) or 1
    date_str = getattr(args, 'date', None)

    edits = collect_edits(log_dir, days=days, date_str=date_str)
    if not edits:
        print("⚠️  没有修改记录")
        return None

    print(f"📊 找到 {len(edits)} 次修改，正在分析...")

    # 读当前 SKILL.md
    current_skill = ""
    if target and target.exists():
        current_skill = target.read_text(encoding="utf-8")

    # 构建对比数据
    edit_summaries = []
    for i, edit in enumerate(edits):
        orig = edit.get("original_content", "")[:3000]
        final = edit.get("final_content", edit.get("edited_content", ""))[:3000]
        ctx = edit.get("context", {})
        edit_summaries.append({
            "index": i + 1,
            "account": ctx.get("account", "unknown"),
            "content_type": ctx.get("content_type", "unknown"),
            "original": orig,
            "final": final,
        })

    proposal_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    prompt = f"""你是 writing style skill 的改进助手。

分析人类对 AI 生成文章的修改，提取可以加入 SKILL.md 的新规则。

## 当前 SKILL.md（最后 3000 字）
{current_skill[-3000:]}

## 修改记录（original vs final）
{json.dumps(edit_summaries, ensure_ascii=False, indent=2)}

## 要求
1. 对比 original 和 final，找出系统性修改。
2. 重点寻找：
   - 应该加入 **Anti-Patterns (绝对禁令)** 的违禁词。
   - 需要调整的 **Voice Dimensions (量化风格锚点)**（如果风格表现与分数不符）。
   - 具体的句式偏好。
3. 不要提取已在 SKILL.md 中的规则。
4. 每条规则必须可执行。

## 输出格式

---
id: {proposal_id}
date: {datetime.now().isoformat()}
source: {len(edits)} edits
status: pending
---

# Improvement Proposal

## 提取的改进建议

### 1. 新禁止词 (Anti-Patterns)
- **`词`** → 替代: "YYY" | 理由: ... | 优先级: **P0/P1/P2**

### 2. 风格维度调整 (Voice Dimensions)
- 维度名称 | 原分 -> 现分 | 理由: ... | 优先级: **P0/P1/P2**

### 3. 新风格规则 (Execution Protocol)
- 规则描述 | 理由: ... | 优先级: **P0/P1/P2**

P0=高置信度(多次), P1=中置信度, P2=低置信度(仅1次)
"""

    suggestions = call_llm(prompt)
    if not suggestions:
        return None

    proposal_file = proposal_dir / f"{proposal_id}.md"
    proposal_file.write_text(suggestions, encoding="utf-8")

    print(f"✅ 改进建议已保存: {proposal_file}")
    print(f"\n{suggestions[:2000]}")
    if len(suggestions) > 2000:
        print(f"\n... (完整内容见文件)")
    return proposal_id


def show_proposals(args):
    _, proposal_dir, _, _ = get_paths(args)
    proposals = list(proposal_dir.glob("*.md"))

    if not proposals:
        print("⚠️  没有提案")
        return

    print(f"\n📋 共 {len(proposals)} 个提案:\n")
    for p in sorted(proposals, reverse=True):
        content = p.read_text(encoding="utf-8")
        status = "unknown"
        for line in content.split("\n")[:10]:
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
        icon = {"pending": "⏳", "applied": "✅", "rejected": "❌"}.get(
            status.split("(")[0].strip(), "❓")
        print(f"  {icon} {p.stem} — {status}")


def backup_skill(target, backup_dir):
    if not target or not target.exists():
        return None
    name = f"SKILL-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    backup_path = backup_dir / name
    shutil.copy2(target, backup_path)
    print(f"📦 备份: {backup_path}")
    return backup_path


def apply_proposal(args):
    _, proposal_dir, backup_dir, target = get_paths(args)
    proposal_id = args.proposal_id
    proposal_file = proposal_dir / f"{proposal_id}.md"

    if not proposal_file.exists():
        print(f"❌ 提案不存在: {proposal_id}")
        return

    if not target or not target.exists():
        print(f"❌ 目标 SKILL.md 不存在（用 --skill 或 --target 指定）")
        return

    proposal_content = proposal_file.read_text(encoding="utf-8")
    current_skill = target.read_text(encoding="utf-8")

    auto_mode = getattr(args, 'auto', False)
    filter_level = "P0" if auto_mode else "P0 和 P1"

    backup_skill(target, backup_dir)

    prompt = f"""把改进提案中的 **{filter_level}** 规则合并到 SKILL.md。

规则：
1. 新禁止词 → 插入到 `## Anti-Patterns (绝对禁令)` 列表中。
2. 风格维度调整 → 更新 `### Voice Dimensions (量化风格锚点)` 的 Markdown 表格。
3. 新风格规则 → 加到对应 section 或 Phase 描述中。
4. 不删除已有核心架构，不改 5-Patterns 结构。
5. 保持 Mentat 风格：冷酷、简洁、动词驱动。

## 提案
{proposal_content}

## 当前 SKILL.md
{current_skill}

输出完整更新后的 SKILL.md。不加代码块包裹。"""

    updated = call_llm(prompt, timeout=300)
    if not updated:
        print("❌ 合并失败")
        return

    target.write_text(updated, encoding="utf-8")

    new_content = proposal_content.replace(
        "status: pending",
        f"status: applied ({datetime.now().strftime('%Y-%m-%d')})")
    proposal_file.write_text(new_content, encoding="utf-8")

    print(f"✅ 已应用提案 {proposal_id}")
    print(f"💡 回滚: python3 improve.py rollback")


def auto_improve(args):
    log_dir, _, _, _ = get_paths(args)
    edits = collect_edits(log_dir, days=7)

    if not edits:
        print("⚠️  最近 7 天没有修改记录，跳过")
        return

    print(f"🤖 自动模式: {len(edits)} 次修改")

    args.days = 7
    args.date = None
    proposal_id = extract_improvements(args)

    if not proposal_id:
        return

    _, proposal_dir, _, _ = get_paths(args)
    content = (proposal_dir / f"{proposal_id}.md").read_text(encoding="utf-8")

    if "P0" not in content:
        print("ℹ️  没有 P0 规则，跳过自动应用")
        return

    print("\n🔄 自动应用 P0 规则...")
    apply_args = argparse.Namespace(**vars(args))
    apply_args.proposal_id = proposal_id
    apply_args.auto = True
    apply_proposal(apply_args)


def rollback(args):
    _, _, backup_dir, target = get_paths(args)

    if not target:
        print("❌ 未指定目标 SKILL.md")
        return

    backups = sorted(backup_dir.glob("SKILL-*.md"), reverse=True)
    if not backups:
        print("❌ 没有备份")
        return

    latest = backups[0]
    # 保存当前版本
    if target.exists():
        emergency = backup_dir / f"SKILL-pre-rollback-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        shutil.copy2(target, emergency)

    shutil.copy2(latest, target)
    print(f"✅ 已回滚到: {latest.name}")


def add_common_args(parser):
    parser.add_argument("--skill", help="目标 skill 目录")
    parser.add_argument("--target", help="目标 SKILL.md 路径")
    parser.add_argument("--log-dir", help="日志目录")
    parser.add_argument("--proposal-dir", help="提案目录")


def main():
    parser = argparse.ArgumentParser(description="Self-Improving Skill — Improver")
    subparsers = parser.add_subparsers(dest="action")

    p_ext = subparsers.add_parser("extract", help="提取改进建议")
    p_ext.add_argument("--date", help="指定日期")
    p_ext.add_argument("--days", type=int, default=1)
    add_common_args(p_ext)

    p_show = subparsers.add_parser("show", help="查看提案")
    add_common_args(p_show)

    p_apply = subparsers.add_parser("apply", help="应用提案")
    p_apply.add_argument("proposal_id")
    add_common_args(p_apply)

    p_auto = subparsers.add_parser("auto", help="自动提取+应用P0")
    add_common_args(p_auto)

    p_rb = subparsers.add_parser("rollback", help="回滚")
    add_common_args(p_rb)

    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "extract": extract_improvements,
        "show": show_proposals,
        "apply": apply_proposal,
        "auto": auto_improve,
        "rollback": rollback,
    }
    actions[args.action](args)


if __name__ == "__main__":
    main()
