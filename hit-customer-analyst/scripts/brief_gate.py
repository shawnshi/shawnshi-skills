import argparse
import re
import sys
from pathlib import Path


SECTION_HEADERS = [
    "### 第一部分：机构全景志",
    "### 第二部分：客户穿透画像",
    "### 第三部分：拜访策略",
]

REQUIRED_PHRASES = [
    "Target_Intent",
    "核心目标判断",
    "机构风险",
    "个人风险",
    "厂商格局判断",
    "认知重合点",
    "认知分歧预警",
    "绝对禁忌 1",
    "绝对禁忌 2",
]

PLACEHOLDER_PATTERNS = [
    r"\[来源\]\(URL\)",
    r"\[来源\]\(https://example\.com/full-url\)",
    r"\[姓名\]",
    r"\[职务\]",
    r"\[所在机构\]",
    r"\[项目\]",
    r"\[厂商\]",
    r"\[金额\]",
    r"\[\.\.\.\]",
    r"\[本次拜访的核心功利目的\]",
]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def count_demo_scripts(text: str) -> int:
    return len(re.findall(r"^\d+\.\s+\*\*Demo 剧本", text, flags=re.MULTILINE))


def find_incomplete_links(text: str) -> list[str]:
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    bad = []
    for link in links:
        if not re.match(r"^https?://", link):
            bad.append(link)
    return bad


def find_placeholders(text: str) -> list[str]:
    hits = []
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits


def validate(text: str) -> list[str]:
    errors = []

    for header in SECTION_HEADERS:
        if header not in text:
            errors.append(f"missing section header: {header}")

    for phrase in REQUIRED_PHRASES:
        if phrase not in text:
            errors.append(f"missing required phrase: {phrase}")

    demo_count = count_demo_scripts(text)
    if demo_count < 2:
        errors.append(f"expected at least 2 Demo scripts, found {demo_count}")

    if "“" not in text and '"' not in text:
        errors.append("missing direct quote in mind map section")

    bad_links = find_incomplete_links(text)
    if bad_links:
        errors.append("found non-absolute links: " + ", ".join(bad_links[:5]))

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("found placeholder markers: " + ", ".join(placeholders))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate hit-customer-analyst briefing markdown."
    )
    parser.add_argument("brief_path", help="Path to the generated briefing markdown")
    args = parser.parse_args()

    path = Path(args.brief_path)
    if not path.exists():
        print(f"[FAIL] file not found: {path}")
        return 1

    text = load_text(path)
    errors = validate(text)
    if errors:
        print("[FAIL] brief gate blocked delivery")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[PASS] brief gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
