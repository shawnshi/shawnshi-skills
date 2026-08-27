"""Generate a valid v2 draft scaffold with deterministic, stable slide IDs."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path

from safe_io import SafeWriteError, atomic_write_text, reject_symlink_path
from validator import SCHEMA_VERSION, StructuredArgumentParser, VALIDATION_SCOPE, audit_outline, issue


LAYOUT_BY_TYPE = {
    "Cover": "title-hero",
    "Executive-Summary": "executive-summary",
    "Section": "title-hero",
    "Content": "two-columns",
    "Data": "chart-plus-insight",
    "Comparison": "comparison-matrix",
    "Roadmap": "linear-roadmap",
    "Decision": "decision-card",
    "Risk": "risk-register",
    "Closing": "quote-callout",
    "Appendix": "appendix-detail",
    "References": "reference-list",
}


def _slide_id(seed: str, ordinal: int, slide_type: str) -> str:
    token = uuid.uuid5(uuid.NAMESPACE_URL, f"tool-slide-architect:v2:{seed}:{ordinal}:{slide_type}").hex[:12]
    return f"SLD-{token}"


def _types(mode: str, count: int) -> list[str]:
    if mode == "one_pager":
        if count != 1:
            raise ValueError("--mode one_pager requires --slides 1")
        return ["Content"]
    if mode == "full":
        if count < 2:
            raise ValueError("--mode full requires at least 2 slides")
        if count == 2:
            return ["Cover", "Decision"]
        middle_cycle = ["Executive-Summary", "Content", "Roadmap", "Risk", "Comparison", "Data"]
        return ["Cover"] + [middle_cycle[index % len(middle_cycle)] for index in range(count - 2)] + ["Decision"]
    cycle = ["Content", "Data", "Comparison", "Roadmap", "Risk"]
    return [cycle[index % len(cycle)] for index in range(count)]


def _content_blocks(slide_type: str, ordinal: int) -> str:
    if slide_type in {"Cover", "Section", "Closing"}:
        return ""
    decision = ""
    if slide_type == "Decision":
        decision = "\n[Decision]:\n- D1 | approve | Confirm the decision request and resource boundary | decision owner | unscheduled"
    risk = "none"
    if slide_type == "Risk":
        risk = "- R1 | delivery | medium | Confirm the principal delivery risk | Define an accountable mitigation owner"
    evidence = "none"
    if slide_type in {"Data", "References"}:
        evidence = "- E1 | {{SOURCE_NAME}} | undated | {{EVIDENCE_SCOPE}} | {{SOURCE_LOCATOR}}"
    return f"""

// CONTENT
[Body]: Define the minimum content required to perform slide task {ordinal}.
{decision}
[Action]: Replace the scaffold text with decision-relevant content.

// EVIDENCE
[Claims]:
- C1 | assumption | unverified | The slide task and evidence boundary require author confirmation | none
[Evidence]:
{evidence}
[Open Items]:
- O1 | data | Confirm the evidence, scope, and locator needed for this slide | content owner | unscheduled
[Risk Flags]:
{risk}"""


def render_scaffold(args: argparse.Namespace) -> str:
    slide_types = _types(args.mode, args.slides)
    seed = args.seed or f"{args.topic}|{args.mode}"
    duration = args.duration_minutes or max(5, args.slides * 2)
    lines = [
        "<DECK_METADATA>",
        f"Schema_Version: {SCHEMA_VERSION}",
        f"Topic: {args.topic}",
        f"Audience: {args.audience}",
        f"Objective: {args.objective}",
        f"Occasion: {args.occasion}",
        f"Deck_Mode: {args.mode}",
        f"Duration_Minutes: {duration}",
        f"Language: {args.language}",
        f"Aspect_Ratio: {args.aspect_ratio}",
        f"Confidentiality: {args.confidentiality}",
        "Status: draft",
        f"Slide_Count: {args.slides}",
        f"Generated: {date.today().isoformat()}",
        "Source_Cutoff: not-applicable",
        "</DECK_METADATA>",
        "",
        "<STYLE_INSTRUCTIONS>",
        f"Style_ID: {args.style_id}",
        "Design_Aesthetic: Restrained decision-oriented documentation",
        "Background: High-contrast neutral background",
        "Typography: Accessible sans serif with a clear hierarchy",
        "Color_Palette: Neutral base with one semantic accent",
        "Density: balanced",
        "Citation_Treatment: visible-footer",
        "Brand_Rules: Apply only verified brand assets and approved templates",
        "Accessibility: Maintain readable type, contrast, labels, and non-color cues",
        "</STYLE_INSTRUCTIONS>",
    ]

    for ordinal, slide_type in enumerate(slide_types, 1):
        slide_id = _slide_id(seed, ordinal, slide_type)
        takeaway = "" if slide_type in {"Cover", "Section", "Closing"} else f"\n[Takeaway]: State the single conclusion for slide task {ordinal}."
        blocks = _content_blocks(slide_type, ordinal)
        lines.extend(
            [
                "",
                "---",
                f"Slide_ID: {slide_id}",
                f"Type: {slide_type}",
                f"Page: {ordinal}",
                "---",
                "",
                "// NARRATIVE",
                f"[Goal]: Define the communication task for slide {ordinal}.",
                f"[Title]: Draft title for slide {ordinal}.{takeaway}",
                blocks,
                "",
                "// VISUAL",
                f"[Layout]: {LAYOUT_BY_TYPE[slide_type]}",
                "[Visual Description]: Describe hierarchy, encoding, and required labels before rendering.",
                "[Chart]: none",
                "",
                "// DELIVERY",
                "[Speaker Notes]: Explain the claim, evidence boundary, and requested action without adding unsupported facts.",
                "[Delivery Notes]: Keep the spoken message aligned with the visible slide.",
                "",
                "// END SLIDE",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StructuredArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["full", "section", "one_pager"], default="full")
    parser.add_argument("--slides", type=int, default=5)
    parser.add_argument("--topic", default="Untitled presentation")
    parser.add_argument("--audience", default="Named decision audience")
    parser.add_argument("--objective", default="Define the decision or action this deck must enable")
    parser.add_argument("--occasion", default="Working session")
    parser.add_argument("--duration-minutes", type=int)
    parser.add_argument("--language", default="English")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--confidentiality", choices=["public", "internal", "confidential", "restricted"], default="internal")
    parser.add_argument("--style-id", default="custom")
    parser.add_argument("--seed", help="Stable ID seed; defaults to topic and mode.")
    parser.add_argument("--output", "-o", type=Path, help="Write a .md file; default is stdout.")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.slides <= 0:
            raise ValueError("--slides must be a positive integer")
        if args.duration_minutes is not None and args.duration_minutes <= 0:
            raise ValueError("--duration-minutes must be a positive integer")
        content = render_scaffold(args)
        report, _ = audit_outline(content)
        if report["errors"]:
            raise SafeWriteError("E_SCAFFOLD_INVALID", "Generated scaffold failed structural validation.", validation_errors=report["errors"])
        if args.output is None:
            sys.stdout.write(content)
            return 0
        if args.output.suffix.lower() not in {".md", ".markdown"}:
            raise SafeWriteError("E_OUTPUT_EXTENSION", "Scaffold output must use .md or .markdown.", path=str(args.output))
        reject_symlink_path(args.output)
        atomic_write_text(args.output, content, force=args.force)
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "created", "output": str(args.output), "slide_count": args.slides, "warning_count": len(report["warnings"])}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, SafeWriteError) as exc:
        error = exc.as_issue() if isinstance(exc, SafeWriteError) else issue("E_ARGUMENT", str(exc))
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [error]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [issue("E_INTERNAL", "Unexpected scaffold failure.", detail=f"{type(exc).__name__}: {exc}")]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
