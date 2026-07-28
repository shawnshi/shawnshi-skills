"""Validate an outline and package it as JSON; this command does not render PPTX."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from validator import SCHEMA_VERSION, audit_outline, load_source


def normalized_slide(slide: dict[str, Any]) -> dict[str, Any]:
    key_content = slide["key_content"]
    visual = slide["visual_directive"]
    script = slide["script"]
    return {
        "page": int(slide["page"]),
        "type": slide["type"],
        "narrative_goal": slide["narrative_goal"],
        "key_content": {
            "title": key_content["Title"],
            "arc_logic": key_content["Arc Logic"],
            "sub_headline": key_content["Sub-headline"],
            "key_insight": key_content["Key Insight"],
            "content_data": key_content["Content / Data"],
            "evidence_trust_anchor": key_content["Evidence / Trust Anchor"],
        },
        "visual_directive": {
            "layout": visual["Layout"],
            "visual_description": visual["Visual Description"],
            "chart_suggestion": visual["Chart Suggestion"],
        },
        "script": {
            "speaker_notes": script["Speaker Notes"],
            "delivery_notes": script["Delivery Notes"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="outline.md or a directory containing outline.md")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("blueprint_bundle.json"),
        help="JSON output path. Relative paths are resolved beside the input outline.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        content, source_files = load_source(args.path)
        report, document = audit_outline(content, allow_placeholders=False)
    except (OSError, UnicodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "fail",
                    "errors": [{"code": "E_FILE_READ", "message": str(exc)}],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if report["errors"]:
        report["source_files"] = source_files
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "presentation_blueprint_bundle",
        "pptx_generated": False,
        "source_files": source_files,
        "metadata": document["metadata"],
        "style_instructions": document["style_instructions"],
        "slides": [normalized_slide(slide) for slide in document["slides"]],
        "validation": {
            "status": report["status"],
            "warnings": report["warnings"],
            "review": report["review"],
        },
    }

    base_dir = args.path if args.path.is_dir() else args.path.parent
    output_path = args.output if args.output.is_absolute() else base_dir / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    temporary_path.write_text(rendered, encoding="utf-8")
    temporary_path.replace(output_path)

    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "packaged",
                "artifact_type": "presentation_blueprint_bundle",
                "output": str(output_path),
                "slide_count": len(bundle["slides"]),
                "warning_count": len(report["warnings"]),
                "pptx_generated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
