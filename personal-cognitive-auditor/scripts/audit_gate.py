import argparse
import re
import sys
import json
from pathlib import Path

COMMON_SECTIONS = [
    "肉体与情绪实况 (Physical & Emotional Reality)",
    "自欺欺人行为剖析 (Self-Deception Analysis)",
    "战术清算 (Tactical Liquidation)",
    "今日打脸点 (Slap in the face)",
    "能量管理 (Biological-Cognitive Correlation)",
    "物理指令 (Physical Next Steps)",
    "Handoff Payload",
]

PLACEHOLDER_PATTERNS = [
    r"\[YYYY",
    r"\[星期X\]",
    r"\[事件\]",
    r"\[主线\]",
    r"\[一句话\]",
    r"\[高优先级\]",
    r"\[Root Cause\]",
    r"\[\.\.\.\]",
]

JARGON_BLACKLIST = [
    "热力学", "二阶效应", "负熵", 
    "物理坍缩", "降维打击", "熵增", "架构洁癖",
    "底层逻辑", "认知带宽", "能量防御"
]

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def parse_period_type(text: str) -> str:
    match = re.search(r'"period_type"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""

def find_placeholders(text: str) -> list[str]:
    hits = []
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits

def scan_for_jargon(text: str) -> list[str]:
    violations = []
    for jargon in JARGON_BLACKLIST:
        matches = re.findall(jargon, text, re.IGNORECASE)
        if len(matches) > 0:
            violations.append(f"'{jargon}' (出现了 {len(matches)} 次)")
    return violations

def validate(text: str, strict_human_mode: bool) -> list[str]:
    errors = []

    for section in COMMON_SECTIONS:
        if section not in text:
            errors.append(f"missing section: {section}")

    if "战术清算 (Tactical Liquidation)" in text and "|" not in text:
        errors.append("tactical accountability is missing markdown table structure")

    if "今日打脸点 (Slap in the face)" not in text:
        errors.append("missing slap in the face statement")

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("found placeholder markers: " + ", ".join(placeholders))
        
    if strict_human_mode:
        jargon_violations = scan_for_jargon(text)
        if jargon_violations:
            errors.append("Jargon_Abuse triggered! Found: " + ", ".join(jargon_violations))
            errors.append("请使用碳基生物的大白话 (如: '很累', '没睡好', '找借口')，剥离所有极客隐喻。")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate personal-cognitive-auditor markdown output."
    )
    parser.add_argument("audit_path", help="Path to the generated audit markdown")
    parser.add_argument("--strict-human-mode", action="store_true", help="Enforce anti-jargon rules")
    args = parser.parse_args()

    path = Path(args.audit_path)
    if not path.exists():
        print(f"[FAIL] file not found: {path}")
        return 1

    text = load_text(path)
    errors = validate(text, args.strict_human_mode)
    if errors:
        print("[FAIL] audit gate blocked delivery")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[PASS] audit gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
