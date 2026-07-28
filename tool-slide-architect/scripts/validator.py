"""Validate the canonical presentation blueprint schema without rewriting input files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "references" / "outline-template.md"
SCHEMA_VERSION = 1
METADATA_FIELDS = ["Topic", "Audience", "Objective", "Language", "Slide_Count", "Generated"]
BLOCK_MARKERS = ["// NARRATIVE GOAL", "// KEY CONTENT", "// VISUAL DIRECTIVE", "// SCRIPT"]
BLOCK_FIELDS = {
    "// KEY CONTENT": [
        "Title",
        "Arc Logic",
        "Sub-headline",
        "Key Insight",
        "Content / Data",
        "Evidence / Trust Anchor",
    ],
    "// VISUAL DIRECTIVE": ["Layout", "Visual Description", "Chart Suggestion"],
    "// SCRIPT": ["Speaker Notes", "Delivery Notes"],
}
SLIDE_TYPES = {"Cover", "Content", "Closing"}
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")
FIELD_RE = re.compile(r"(?m)^\[(?P<name>[^\]\n]+)\]:[ \t]*(?P<inline>[^\n]*)$")
SLIDE_RE = re.compile(
    r"(?ms)^---[ \t]*\n"
    r"(?P<header>(?:[A-Za-z][A-Za-z0-9_-]*[ \t]*:[^\n]*\n)+)"
    r"^---[ \t]*\n"
    r"(?P<body>.*?)"
    r"(?=^---[ \t]*\n(?:[A-Za-z][A-Za-z0-9_-]*[ \t]*:[^\n]*\n)+^---[ \t]*\n|\Z)"
)


def known_template_placeholders() -> set[str]:
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    return set(PLACEHOLDER_RE.findall(template))


KNOWN_TEMPLATE_PLACEHOLDERS = known_template_placeholders()


def issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_payload(content: str) -> str:
    normalized = normalize(content)
    fenced = re.search(r"(?ms)```(?:markdown|md)[ \t]*\n(?P<body>.*?)\n```", normalized)
    if fenced and "<DECK_METADATA>" in fenced.group("body"):
        return fenced.group("body").strip() + "\n"
    return normalized


def load_source(path: Path) -> tuple[str, list[str]]:
    if path.is_file():
        return path.read_text(encoding="utf-8-sig"), [str(path)]
    if not path.is_dir():
        raise FileNotFoundError(f"Path does not exist: {path}")

    outline = path / "outline.md"
    if not outline.is_file():
        raise FileNotFoundError(f"Directory does not contain the required outline.md: {path}")
    return outline.read_text(encoding="utf-8-sig"), [str(outline)]


def extract_tag(
    content: str,
    tag: str,
    errors: list[dict[str, Any]],
) -> str:
    opening = f"<{tag}>"
    closing = f"</{tag}>"
    if content.count(opening) != 1 or content.count(closing) != 1:
        errors.append(
            issue(
                "E_TAG_CARDINALITY",
                f"{tag} 必须各有一个开始和结束标签。",
                tag=tag,
                opening_count=content.count(opening),
                closing_count=content.count(closing),
            )
        )
        return ""
    match = re.search(rf"(?s){re.escape(opening)}(.*?){re.escape(closing)}", content)
    if not match or not match.group(1).strip():
        errors.append(issue("E_EMPTY_TAG", f"{tag} 内容为空。", tag=tag))
        return ""
    return match.group(1).strip()


def parse_key_values(
    text: str,
    required: list[str],
    errors: list[dict[str, Any]],
    context: str,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if ":" not in line:
            errors.append(
                issue(
                    "E_METADATA_LINE",
                    f"{context} 中存在无法解析的行。",
                    line=line_number,
                    value=line,
                )
            )
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key in values:
            errors.append(issue("E_DUPLICATE_FIELD", f"{context} 字段重复。", field=key))
        values[key] = value

    for field in required:
        if field not in values:
            errors.append(issue("E_MISSING_FIELD", f"{context} 缺少字段。", field=field))
        elif not values[field]:
            errors.append(issue("E_EMPTY_FIELD", f"{context} 字段为空。", field=field))
    unknown = [field for field in values if field not in required]
    if unknown:
        errors.append(issue("E_UNKNOWN_FIELD", f"{context} 包含未声明字段。", fields=unknown))
    return values


def parse_header(
    text: str,
    slide_index: int,
    errors: list[dict[str, Any]],
) -> dict[str, str]:
    return parse_key_values(text, ["Type", "Page"], errors, f"Slide {slide_index} header")


def split_blocks(
    body: str,
    slide_index: int,
    errors: list[dict[str, Any]],
) -> dict[str, str]:
    positions: list[int] = []
    for marker in BLOCK_MARKERS:
        count = body.count(marker)
        if count != 1:
            errors.append(
                issue(
                    "E_BLOCK_CARDINALITY",
                    f"Slide {slide_index} 的顶层区块必须各出现一次。",
                    block=marker,
                    count=count,
                )
            )
        positions.append(body.find(marker))

    if any(position < 0 for position in positions):
        return {}
    if positions != sorted(positions):
        errors.append(issue("E_BLOCK_ORDER", f"Slide {slide_index} 的顶层区块顺序不符合 Schema。"))
        return {}
    if body[: positions[0]].strip():
        errors.append(
            issue(
                "E_UNEXPECTED_SLIDE_PREFIX",
                f"Slide {slide_index} 在首个顶层区块之前含有未声明内容。",
            )
        )

    blocks: dict[str, str] = {}
    for index, marker in enumerate(BLOCK_MARKERS):
        start = positions[index] + len(marker)
        end = positions[index + 1] if index + 1 < len(positions) else len(body)
        value = body[start:end].strip()
        blocks[marker] = value
        if not value:
            errors.append(
                issue("E_EMPTY_BLOCK", f"Slide {slide_index} 的顶层区块为空。", block=marker)
            )
    return blocks


def parse_fields(
    text: str,
    required: list[str],
    slide_index: int,
    block: str,
    errors: list[dict[str, Any]],
) -> dict[str, str]:
    matches = list(FIELD_RE.finditer(text))
    if not matches:
        errors.append(
            issue("E_NO_NESTED_FIELDS", f"Slide {slide_index} 的区块缺少嵌套字段。", block=block)
        )
        return {}
    if text[: matches[0].start()].strip():
        errors.append(
            issue(
                "E_UNEXPECTED_BLOCK_PREFIX",
                f"Slide {slide_index} 的区块在首个字段前含有未声明内容。",
                block=block,
            )
        )

    parsed: dict[str, str] = {}
    order: list[str] = []
    for index, match in enumerate(matches):
        name = match.group("name").strip()
        inline = match.group("inline").strip()
        tail_start = match.end()
        tail_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tail = text[tail_start:tail_end].strip()
        value = "\n".join(part for part in [inline, tail] if part).strip()
        order.append(name)
        if name in parsed:
            errors.append(
                issue(
                    "E_DUPLICATE_FIELD",
                    f"Slide {slide_index} 的嵌套字段重复。",
                    block=block,
                    field=name,
                )
            )
        parsed[name] = value

    missing = [field for field in required if field not in parsed]
    unknown = [field for field in parsed if field not in required]
    empty = [field for field in required if field in parsed and not parsed[field]]
    if missing:
        errors.append(
            issue(
                "E_MISSING_FIELD",
                f"Slide {slide_index} 的区块缺少字段。",
                block=block,
                fields=missing,
            )
        )
    if unknown:
        errors.append(
            issue(
                "E_UNKNOWN_FIELD",
                f"Slide {slide_index} 的区块包含未声明字段。",
                block=block,
                fields=unknown,
            )
        )
    if empty:
        errors.append(
            issue(
                "E_EMPTY_FIELD",
                f"Slide {slide_index} 的区块包含空字段。",
                block=block,
                fields=empty,
            )
        )
    known_order = [field for field in order if field in required]
    expected_order = [field for field in required if field in parsed]
    if known_order != expected_order:
        errors.append(
            issue(
                "E_FIELD_ORDER",
                f"Slide {slide_index} 的嵌套字段顺序不符合 Schema。",
                block=block,
            )
        )
    return parsed


def audit_outline(
    content: str,
    allow_placeholders: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = extract_payload(content)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    metadata_text = extract_tag(payload, "DECK_METADATA", errors)
    style_text = extract_tag(payload, "STYLE_INSTRUCTIONS", errors)
    metadata = parse_key_values(metadata_text, METADATA_FIELDS, errors, "DECK_METADATA")

    slide_matches = list(SLIDE_RE.finditer(payload))
    if not slide_matches:
        errors.append(issue("E_NO_SLIDES", "未检测到符合 Schema 的幻灯片头。"))

    slides: list[dict[str, Any]] = []
    for slide_index, match in enumerate(slide_matches, 1):
        header = parse_header(match.group("header"), slide_index, errors)
        blocks = split_blocks(match.group("body"), slide_index, errors)
        structured = {
            "page": header.get("Page", ""),
            "type": header.get("Type", ""),
            "narrative_goal": blocks.get("// NARRATIVE GOAL", ""),
            "key_content": {},
            "visual_directive": {},
            "script": {},
        }
        if blocks:
            structured["key_content"] = parse_fields(
                blocks["// KEY CONTENT"],
                BLOCK_FIELDS["// KEY CONTENT"],
                slide_index,
                "// KEY CONTENT",
                errors,
            )
            structured["visual_directive"] = parse_fields(
                blocks["// VISUAL DIRECTIVE"],
                BLOCK_FIELDS["// VISUAL DIRECTIVE"],
                slide_index,
                "// VISUAL DIRECTIVE",
                errors,
            )
            structured["script"] = parse_fields(
                blocks["// SCRIPT"],
                BLOCK_FIELDS["// SCRIPT"],
                slide_index,
                "// SCRIPT",
                errors,
            )
        slides.append(structured)

    page_numbers: list[int] = []
    for index, slide in enumerate(slides, 1):
        try:
            page_numbers.append(int(slide["page"]))
        except (TypeError, ValueError):
            errors.append(issue("E_PAGE_NUMBER", f"Slide {index} 的 Page 必须是整数。"))
        if slide["type"] not in SLIDE_TYPES:
            errors.append(
                issue(
                    "E_SLIDE_TYPE",
                    f"Slide {index} 的 Type 不在允许集合中。",
                    value=slide["type"],
                )
            )

    if page_numbers and page_numbers != list(range(1, len(slides) + 1)):
        errors.append(
            issue(
                "E_PAGE_SEQUENCE",
                "页码必须从 1 开始连续递增。",
                actual=page_numbers,
            )
        )
    if slides and slides[0]["type"] != "Cover":
        errors.append(issue("E_FIRST_SLIDE_TYPE", "第一页必须是 Cover。"))
    if len(slides) >= 2:
        if slides[-1]["type"] != "Closing":
            errors.append(issue("E_LAST_SLIDE_TYPE", "两页及以上时最后一页必须是 Closing。"))
        for index, slide in enumerate(slides[1:-1], 2):
            if slide["type"] != "Content":
                errors.append(
                    issue("E_MIDDLE_SLIDE_TYPE", f"中间页必须是 Content。", slide=index)
                )

    slide_count = metadata.get("Slide_Count")
    if slide_count:
        try:
            declared_count = int(slide_count)
            if declared_count <= 0 or declared_count != len(slides):
                errors.append(
                    issue(
                        "E_SLIDE_COUNT",
                        "Slide_Count 必须为正整数并与实际页数一致。",
                        declared=declared_count,
                        actual=len(slides),
                    )
                )
        except ValueError:
            errors.append(issue("E_SLIDE_COUNT", "Slide_Count 必须是整数。", value=slide_count))

    if not allow_placeholders:
        placeholders = sorted(
            token for token in KNOWN_TEMPLATE_PLACEHOLDERS if token in payload
        )
        if placeholders:
            errors.append(
                issue(
                    "E_UNRESOLVED_PLACEHOLDER",
                    "最终蓝图仍包含未处理占位符。",
                    instances=placeholders[:30],
                )
            )

    for index, slide in enumerate(slides, 1):
        content_data = slide["key_content"].get("Content / Data", "")
        bullet_count = len(re.findall(r"(?m)^[*-]\s+", content_data))
        if len(content_data) > 900 or bullet_count > 7:
            warnings.append(
                issue(
                    "W_CONTENT_DENSITY",
                    f"Slide {index} 的内容可能过密，请人工判断。",
                    characters=len(content_data),
                    bullets=bullet_count,
                )
            )

    review = [
        issue(
            "R_HUMAN_REVIEW",
            "故事线、证据充分性、图表选择、视觉质量和承诺风险必须人工复核。",
        )
    ]
    status = "fail" if errors else "warning" if warnings else "pass"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "review": review,
        "summary": {
            "slide_count": len(slides),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
    }
    document = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "style_instructions": style_text,
        "slides": slides,
    }
    return report, document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="outline.md or a directory containing outline.md")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Validate the reusable template without treating placeholders as release errors.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        content, source_files = load_source(args.path)
        report, _document = audit_outline(content, args.allow_placeholders)
        report["source_files"] = source_files
    except (OSError, UnicodeError) as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "errors": [issue("E_FILE_READ", str(exc))],
            "warnings": [],
            "review": [],
            "summary": {"slide_count": 0, "error_count": 1, "warning_count": 0},
            "source_files": [],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
