import argparse
import re
import sys
from pathlib import Path


SECTION_HEADERS = [
    "### 第一部分：机构与业务画像",
    "### 第二部分：已核实项目、厂商线索与公开职业角色",
    "### 第三部分：机会、风险和拜访议题",
    "### 第四部分：信息缺口与建议核实问题",
    "### 第五部分：来源清单",
]

REQUIRED_FIELDS = [
    "研究时间范围：",
    "拜访目标：",
    "报告生成日期：",
    "证据强度",
    "信息缺口",
    "来源清单",
]

DISALLOWED_TERMS = [
    "制造刚需焦虑",
    "权力博弈",
    "学术门派",
    "黑皮书",
    "政治身份",
    "个人风险",
    "个人动机",
    "私人关系",
    "致命三问",
    "靶向打击",
    "降维打击",
]

PLACEHOLDER_PATTERNS = [
    r"\[目标机构\]",
    r"\[YYYY-MM-DD(?:\s*至\s*YYYY-MM-DD)?\]",
    r"\[待填写[^\]]*\]",
    r"\[来源标题\]",
    r"\[公开 URL 或用户提供材料名称\]",
    r"\[需要通过本次交流确认或推进的事项\]",
    r"\[高/中/低(?:[^\]]*)?\]",
]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def count_demo_scripts(text: str) -> int:
    return len(
        re.findall(
            r"^\s*(?:\d+\.|[-*])\s+\*\*Demo 剧本(?:\s*\d+)?",
            text,
            flags=re.MULTILINE,
        )
    )


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


def find_disallowed_terms(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        if any(
            marker in line
            for marker in (
                "合规边界",
                "不得推断",
                "禁止推断",
                "不推断",
                "不得收集",
                "禁止收集",
            )
        ):
            continue
        for term in DISALLOWED_TERMS:
            if term in line:
                hits.append(term)
    return sorted(set(hits))


def audit(text: str) -> dict[str, list[str]]:
    errors = []
    warnings = []

    for header in SECTION_HEADERS:
        if header not in text:
            errors.append(f"missing section header: {header}")

    for field in REQUIRED_FIELDS:
        if field not in text:
            errors.append(f"missing required field: {field}")

    for term in find_disallowed_terms(text):
        errors.append(f"disallowed inference or pressure-language term: {term}")

    bad_links = find_incomplete_links(text)
    if bad_links:
        errors.append("found non-absolute links: " + ", ".join(bad_links[:5]))

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("found placeholder markers: " + ", ".join(placeholders))

    if not re.search(r"\|\s*S\d+\s*\|", text):
        errors.append("source list must contain at least one numbered source row")

    demo_count = count_demo_scripts(text)
    if demo_count == 0:
        warnings.append(
            "no Demo script found; add one only when verified needs justify a demonstration"
        )

    if "“" not in text and '"' not in text:
        warnings.append("no direct quote found; this is acceptable when no reliable quote exists")

    if not re.search(r"\d", text):
        warnings.append(
            "no numeric content found; quantify only when a sourced metric is available"
        )

    return {"errors": errors, "warnings": warnings}


def validate(text: str) -> list[str]:
    """Return deterministic blocking errors for backward compatibility."""
    return audit(text)["errors"]


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
    report = audit(text)
    errors = report["errors"]
    warnings = report["warnings"]
    if errors:
        print("[FAIL] brief gate blocked delivery")
        for error in errors:
            print(f"- {error}")
        return 1

    if warnings:
        print("[PASS_WITH_WARNINGS] deterministic checks passed")
        for warning in warnings:
            print(f"- WARNING: {warning}")
    else:
        print("[PASS] brief gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
