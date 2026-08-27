"""Migrate a canonical v1 outline to a new, non-overwriting v2 draft file."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from safe_io import SafeWriteError, atomic_write_text, paths_alias, reject_symlink_path
from validator import LAYOUT_IDS, SCHEMA_VERSION, StructuredArgumentParser, VALIDATION_SCOPE, audit_outline, extract_payload, issue, load_source


V1_SLIDE_RE = re.compile(
    r"(?ms)^---[ \t]*\n"
    r"(?P<header>(?:[A-Za-z][A-Za-z0-9_-]*[ \t]*:[^\n]*\n)+)"
    r"^---[ \t]*\n"
    r"(?P<body>.*?)"
    r"(?=^---[ \t]*\n(?:[A-Za-z][A-Za-z0-9_-]*[ \t]*:[^\n]*\n)+^---[ \t]*\n|\Z)"
)
V1_MARKERS = ["// NARRATIVE GOAL", "// KEY CONTENT", "// VISUAL DIRECTIVE", "// SCRIPT"]
V1_FIELDS = {
    "// KEY CONTENT": ["Title", "Arc Logic", "Sub-headline", "Key Insight", "Content / Data", "Evidence / Trust Anchor"],
    "// VISUAL DIRECTIVE": ["Layout", "Visual Description", "Chart Suggestion"],
    "// SCRIPT": ["Speaker Notes", "Delivery Notes"],
}
STRUCTURAL_FIELD_NAMES = {
    "Goal", "Title", "Takeaway", "Body", "Decision", "Action", "Claims", "Evidence", "Open Items", "Risk Flags",
    "Layout", "Visual Description", "Chart", "Assets", "Speaker Notes", "Delivery Notes",
}


def _tag(payload: str, name: str) -> str:
    match = re.search(rf"(?s)<{name}>(.*?)</{name}>", payload)
    if not match:
        raise SafeWriteError("E_V1_TAG", f"Legacy outline is missing {name}.")
    return match.group(1).strip()


def _key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _split_v1_blocks(body: str) -> dict[str, str]:
    positions = [(body.find(marker), marker) for marker in V1_MARKERS]
    if any(position < 0 for position, _ in positions):
        raise SafeWriteError("E_V1_BLOCK", "Legacy slide is missing a canonical v1 block.")
    positions.sort()
    blocks: dict[str, str] = {}
    for index, (position, marker) in enumerate(positions):
        start = position + len(marker)
        end = positions[index + 1][0] if index + 1 < len(positions) else len(body)
        blocks[marker] = body[start:end].strip()
    return blocks


def _parse_v1_fields(text: str, fields: list[str]) -> dict[str, str]:
    names = "|".join(re.escape(field) for field in fields)
    regex = re.compile(rf"(?m)^\[(?P<name>{names})\]:[ \t]*(?P<inline>[^\n]*)$")
    matches = list(regex.finditer(text))
    parsed: dict[str, str] = {}
    for index, match in enumerate(matches):
        tail_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = "\n".join(part for part in (match.group("inline").strip(), text[match.end():tail_end].strip()) if part)
        parsed[match.group("name")] = value
    return parsed


def _safe_value(value: str, fallback: str) -> str:
    value = value.strip() or fallback
    output: list[str] = []
    for line in value.splitlines():
        bracket = re.match(r"^\[([^\]]+)\]:", line)
        if line.strip() in {"// NARRATIVE", "// CONTENT", "// EVIDENCE", "// VISUAL", "// DELIVERY", "// END SLIDE"} or (bracket and bracket.group(1) in STRUCTURAL_FIELD_NAMES):
            output.append("> " + line)
        else:
            output.append(line)
    return "\n".join(output)


def _record_text(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.strip()).replace("|", "/")
    return compact or "No legacy evidence text was supplied"


def _stable_id(topic: str, index: int, title: str) -> str:
    token = uuid.uuid5(uuid.NAMESPACE_URL, f"tool-slide-architect:migrate-v1:{topic}:{index}:{title}").hex[:12]
    return f"SLD-{token}"


def _migrated_layout(value: str) -> str:
    original = value.strip()
    if original in LAYOUT_IDS:
        return original
    slug = re.sub(r"[^a-z0-9]+", "-", original.lower()).strip("-")[:48]
    return f"custom:{slug or 'legacy-layout'}"


def migrate(content: str) -> str:
    payload = extract_payload(content)
    metadata_v1 = _key_values(_tag(payload, "DECK_METADATA"))
    style_v1 = _key_values(_tag(payload, "STYLE_INSTRUCTIONS"))
    matches = list(V1_SLIDE_RE.finditer(payload))
    if not matches:
        raise SafeWriteError("E_V1_SLIDES", "No canonical v1 slides were found.")

    parsed_slides: list[dict[str, Any]] = []
    for index, match in enumerate(matches, 1):
        header = _key_values(match.group("header"))
        blocks = _split_v1_blocks(match.group("body"))
        key_content = _parse_v1_fields(blocks["// KEY CONTENT"], V1_FIELDS["// KEY CONTENT"])
        visual = _parse_v1_fields(blocks["// VISUAL DIRECTIVE"], V1_FIELDS["// VISUAL DIRECTIVE"])
        script = _parse_v1_fields(blocks["// SCRIPT"], V1_FIELDS["// SCRIPT"])
        parsed_slides.append({"header": header, "goal": blocks["// NARRATIVE GOAL"], "content": key_content, "visual": visual, "script": script})

    topic = metadata_v1.get("Topic", "Migrated legacy presentation")
    if len(parsed_slides) == 1:
        mode = "one_pager"
    elif parsed_slides[0]["header"].get("Type") == "Cover" and parsed_slides[-1]["header"].get("Type") == "Closing":
        mode = "full"
    else:
        mode = "section"
    generated = metadata_v1.get("Generated", "")
    try:
        date.fromisoformat(generated)
    except ValueError:
        generated = date.today().isoformat()

    lines = [
        "<DECK_METADATA>",
        f"Schema_Version: {SCHEMA_VERSION}",
        f"Topic: {topic}",
        f"Audience: {metadata_v1.get('Audience', 'Legacy audience; confirm before use')}",
        f"Objective: {metadata_v1.get('Objective', 'Review and complete the migrated blueprint')}",
        "Occasion: Migrated legacy blueprint review",
        f"Deck_Mode: {mode}",
        f"Duration_Minutes: {max(5, len(parsed_slides) * 2)}",
        f"Language: {metadata_v1.get('Language', 'Not specified')}",
        "Aspect_Ratio: 16:9",
        "Confidentiality: internal",
        "Status: draft",
        f"Slide_Count: {len(parsed_slides)}",
        f"Generated: {generated}",
        "Source_Cutoff: not-applicable",
        "Revision: migrated-from-v1",
        "</DECK_METADATA>",
        "",
        "<STYLE_INSTRUCTIONS>",
        "Style_ID: custom",
        f"Design_Aesthetic: {style_v1.get('Design_Aesthetic', 'Migrated legacy style; confirm before rendering')}",
        f"Background: {style_v1.get('Background', 'Legacy background direction not specified')}",
        f"Typography: {style_v1.get('Typography', 'Legacy typography direction not specified')}",
        f"Color_Palette: {style_v1.get('Color_Palette', 'Legacy color direction not specified')}",
        "Density: balanced",
        "Citation_Treatment: source-note",
        "Brand_Rules: Reconcile migrated directions with the approved template and asset rights",
        "Accessibility: Verify contrast, type size, labels, and non-color cues",
        "</STYLE_INSTRUCTIONS>",
    ]

    type_map = {"Cover": "Cover", "Content": "Content", "Closing": "Closing"}
    for index, slide in enumerate(parsed_slides, 1):
        content = slide["content"]
        old_type = slide["header"].get("Type", "Content")
        slide_type = type_map.get(old_type, "Content")
        title = _safe_value(content.get("Title", ""), f"Migrated slide {index}")
        evidence_text = _record_text(content.get("Evidence / Trust Anchor", ""))
        body_parts = [content.get("Sub-headline", ""), content.get("Key Insight", ""), content.get("Content / Data", ""), content.get("Arc Logic", "")]
        body = _safe_value("\n\n".join(part for part in body_parts if part), "Review migrated legacy content")
        takeaway = "" if slide_type in {"Cover", "Closing"} else f"\n[Takeaway]: {_safe_value(content.get('Key Insight', ''), 'Confirm the migrated slide conclusion')}"
        legacy_layout = _safe_value(slide["visual"].get("Layout", ""), "Legacy layout direction not specified")
        visual_description = _safe_value(slide["visual"].get("Visual Description", ""), "Review legacy visual direction")
        lines += [
            "",
            "---",
            f"Slide_ID: {_stable_id(topic, index, title)}",
            f"Type: {slide_type}",
            f"Page: {index}",
            "---",
            "",
            "// NARRATIVE",
            f"[Goal]: {_safe_value(slide['goal'], 'Review the migrated slide task')}",
            f"[Title]: {title}{takeaway}",
            "",
            "// CONTENT",
            f"[Body]: {body}",
            "[Action]: Review migrated content against the current brief.",
            "",
            "// EVIDENCE",
            "[Claims]:",
            f"- C1 | inference | unverified | Legacy evidence text retained for review: {evidence_text} | none",
            "[Evidence]:",
            "none",
            "[Open Items]:",
            f"- O1 | data | Verify and locate migrated legacy evidence: {evidence_text} | content owner | unscheduled",
            "[Risk Flags]:",
            "- R1 | delivery | medium | Legacy evidence was not machine-verifiable | Re-source before changing claim status",
            "",
            "// VISUAL",
            f"[Layout]: {_migrated_layout(slide['visual'].get('Layout', ''))}",
            f"[Visual Description]: Legacy layout direction: {legacy_layout}. {visual_description}",
            f"[Chart]: {_safe_value(slide['visual'].get('Chart Suggestion', ''), 'none')}",
            "",
            "// DELIVERY",
            f"[Speaker Notes]: {_safe_value(slide['script'].get('Speaker Notes', ''), 'Review migrated speaker notes')}",
            f"[Delivery Notes]: {_safe_value(slide['script'].get('Delivery Notes', ''), 'State that the blueprint was migrated and requires review')}",
            "",
            "// END SLIDE",
        ]
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StructuredArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Canonical v1 outline.md or directory containing outline.md")
    parser.add_argument("--output", "-o", type=Path, help="New v2 .md path; defaults to <input>.v2.md")
    parser.add_argument("--force", action="store_true", help="Replace an existing non-symlink migration output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        reject_symlink_path(args.path)
        content, source_files = load_source(args.path)
        source_path = Path(source_files[0])
        reject_symlink_path(source_path)
        output = args.output or source_path.with_name(f"{source_path.stem}.v2.md")
        if not output.is_absolute():
            output = source_path.parent / output
        if output.suffix.lower() not in {".md", ".markdown"}:
            raise SafeWriteError("E_OUTPUT_EXTENSION", "Migration output must use .md or .markdown.", path=str(output))
        reject_symlink_path(output)
        if paths_alias(source_path, output):
            raise SafeWriteError("E_INPUT_OUTPUT_ALIAS", "Migration output must be a new file.", input=str(source_path), output=str(output))
        migrated = migrate(content)
        report, _ = audit_outline(migrated)
        if report["errors"]:
            raise SafeWriteError("E_MIGRATION_INVALID", "Migrated draft failed v2 structural validation.", validation_errors=report["errors"])
        atomic_write_text(output, migrated, force=args.force)
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": 1, "validation_scope": VALIDATION_SCOPE, "status": "migrated", "output": str(output), "slide_count": report["summary"]["slide_count"], "warning_count": report["summary"]["warning_count"]}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, SafeWriteError, OSError, UnicodeError) as exc:
        error = exc.as_issue() if isinstance(exc, SafeWriteError) else issue("E_FILE_IO", str(exc))
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": 1, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [error]}, ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": 1, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [issue("E_INTERNAL", "Unexpected migration failure.", detail=f"{type(exc).__name__}: {exc}")]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
