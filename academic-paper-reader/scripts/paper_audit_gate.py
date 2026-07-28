import argparse
import re
import sys
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "template.md"
SUGGESTED_SECTIONS = [
    r"1\.\s*学术河流与演化叙事",
    r"2\.\s*目标论文：核心拆解",
    r"3\.\s*核心概念拆解",
    r"4\.\s*(?:综合评价与启发|启发与博导审稿)",
]

STYLE_PHRASES = [
    "值得注意的是",
    "近年来随着",
    "本文提出了一种",
    "本文提出",
    "填补了空白",
    "具有重要的理论意义和实际应用价值",
    "被锁在",
    "由...引起的",
    "进行分析",
    "进行了",
    "protagonist",
    "climax",
    "resolution",
]

PLACEHOLDER_PATTERNS = [
    r"(?<!\\)\{(?=[^{}\n]*[\u4e00-\u9fff])[^{}\n]{1,160}\}",
    r"\{(?:YYYY|Date|Title|Authors?|URL|DOI|Target Paper)[^{}\n]*\}",
    r"\[(?:YYYY|Date|日期|作者|标题|一句话|URL|DOI|待填|待补)[^\]\n]*\]",
    r"(?im)^\s*(?:TODO|TBD|待填写|待补充)\s*[:：]?",
]


def known_template_placeholders() -> set[str]:
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    tokens: set[str] = set()
    for pattern in PLACEHOLDER_PATTERNS:
        tokens.update(str(hit) for hit in re.findall(pattern, template))
    return tokens


KNOWN_TEMPLATE_PLACEHOLDERS = known_template_placeholders()


def safe_print(message: str) -> None:
    encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
    print(
        message.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        ),
        file=sys.stderr,
    )


def validate_paper_draft(content: str) -> tuple[list[str], list[str]]:
    """Return deterministic errors and non-blocking editorial warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    if not content.strip():
        errors.append("draft is empty")
        return errors, warnings

    placeholder_hits = sorted(
        token for token in KNOWN_TEMPLATE_PLACEHOLDERS if token in content
    )
    if placeholder_hits:
        preview = ", ".join(str(hit)[:80] for hit in placeholder_hits[:5])
        errors.append(f"unresolved template placeholders: {preview}")

    for section in SUGGESTED_SECTIONS:
        if not re.search(section, content, re.IGNORECASE):
            warnings.append(f"optional section not found: {section}")

    if not re.search(
        r"溯源地图\s*\(Traceback Map\)", content, re.IGNORECASE
    ) and not re.search(r"\[年份:\s*奠基\]", content):
        warnings.append("optional traceback map not found")

    for phrase in STYLE_PHRASES:
        if phrase in content:
            warnings.append(f"editorial phrase to review: '{phrase}'")

    if re.search(r"\$\$.+?\$\$", content, re.DOTALL):
        warnings.append(
            "block LaTeX found; explain symbols and intuition when the audience needs it"
        )

    has_denote_metadata = bool(re.search(r"(?m)^#\+\w+:", content))
    if has_denote_metadata:
        if not re.search(r"(?m)^#\+title:\s*\S", content):
            warnings.append(
                "Denote-style metadata is present but '#+title:' is empty or absent"
            )
        if not re.search(
            r"(?m)^#\+identifier:\s*\d{8}T\d{6}\s*$", content
        ):
            warnings.append(
                "Denote-style identifier is absent or not YYYYMMDDTHHMMSS"
            )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Academic Paper Reader drafts. Deterministic errors block; "
            "editorial suggestions are warnings."
        )
    )
    parser.add_argument("file_path", help="Path to the Markdown draft to audit.")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    if not file_path.is_file():
        safe_print(f"[FAIL] file not found: {file_path}")
        return 1

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        safe_print(f"[FAIL] unable to read UTF-8 draft: {exc}")
        return 1

    errors, warnings = validate_paper_draft(content)

    for warning in warnings:
        safe_print(f"[WARN] {warning}")

    if errors:
        safe_print("[FAIL] deterministic audit errors:")
        for error in errors:
            safe_print(f"- {error}")
        return 1

    print(f"[PASS] audit completed with {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
