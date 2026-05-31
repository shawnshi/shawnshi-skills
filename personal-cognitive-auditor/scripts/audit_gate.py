import argparse
import re
import sys
from pathlib import Path


COMMON_SECTIONS = [
    "## Context Snapshot",
    "## Tactical Accountability",
    "## Signals",
    "## Core Insight",
    "## Strategic Diagnosis",
    "## Next Tactics",
    "## Handoff Payload",
]

LONG_CYCLE_SECTIONS = [
    "## Interaction & Work Patterns",
]

MONTHLY_EXTRA = [
    "## Long-Cycle Outlook",
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


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_period_type(text: str) -> str:
    match = re.search(r'"period_type"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def count_tactics(text: str) -> int:
    return len(re.findall(r"^\d+\.\s", text, flags=re.MULTILINE))


def find_placeholders(text: str) -> list[str]:
    hits = []
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits


def validate(text: str) -> list[str]:
    errors = []

    for section in COMMON_SECTIONS:
        if section not in text:
            errors.append(f"missing section: {section}")

    if "## Tactical Accountability" in text and "|" not in text:
        errors.append("tactical accountability is missing markdown table structure")

    if "【数据缺口】" not in text and "Physiology:" not in text:
        errors.append("missing either data-gap note or signal detail")

    if "核心洞察" not in text:
        errors.append("missing core insight statement")

    if count_tactics(text) < 1:
        errors.append("expected at least one tactic item")

    period_type = parse_period_type(text)
    if period_type in {"weekly", "monthly", "annual"}:
        for section in LONG_CYCLE_SECTIONS:
            if section not in text:
                errors.append(f"missing long-cycle section: {section}")

    if period_type in {"monthly", "annual"}:
        for section in MONTHLY_EXTRA:
            if section not in text:
                errors.append(f"missing extended section: {section}")

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("found placeholder markers: " + ", ".join(placeholders))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate personal-cognitive-auditor markdown output."
    )
    parser.add_argument("audit_path", help="Path to the generated audit markdown")
    args = parser.parse_args()

    path = Path(args.audit_path)
    if not path.exists():
        print(f"[FAIL] file not found: {path}")
        return 1

    text = load_text(path)
    errors = validate(text)
    if errors:
        print("[FAIL] audit gate blocked delivery")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[PASS] audit gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
