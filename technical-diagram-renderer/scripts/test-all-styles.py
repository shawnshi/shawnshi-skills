#!/usr/bin/env python3
"""Exercise all automatic styles across the major semantic diagram types."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
RENDERER = SCRIPT_DIR / "render-diagram.py"
DEFAULT_TYPES = ("architecture", "data-flow", "flowchart", "sequence", "state-machine", "er-diagram")


def _parse_styles(raw: str) -> list[int]:
    styles: list[int] = []
    for item in raw.split(","):
        try:
            style = int(item.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid style '{item}'") from exc
        if style not in range(1, 8):
            raise argparse.ArgumentTypeError("styles must be in the range 1-7")
        if style not in styles:
            styles.append(style)
    if not styles:
        raise argparse.ArgumentTypeError("at least one style is required")
    return styles


def _parse_types(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one diagram type is required")
    return list(dict.fromkeys(values))


def _sample(template_type: str, style: int) -> dict[str, object]:
    shared: dict[str, object] = {
        "template_type": template_type,
        "style": style,
        "width": 960,
        "height": 640,
        "title": f"{template_type} / style {style}",
        "subtitle": "Automated regression fixture",
    }
    if template_type in {"architecture", "data-flow"}:
        shared.update(
            {
                "nodes": [
                    {"id": "source", "kind": "rect", "x": 90, "y": 210, "width": 190, "height": 84, "label": "Source"},
                    {"id": "service", "kind": "double_rect", "x": 385, "y": 210, "width": 190, "height": 84, "label": "Service"},
                    {"id": "store", "kind": "cylinder", "x": 680, "y": 200, "width": 150, "height": 104, "label": "Store"},
                ],
                "arrows": [
                    {"source": "source", "target": "service", "label": "request", "flow": "control"},
                    {"source": "service", "target": "store", "label": "write", "flow": "write"},
                ],
            }
        )
    elif template_type == "flowchart":
        shared.update(
            {
                "steps": [
                    {"id": "start", "type": "start", "label": "Start"},
                    {"id": "check", "type": "decision", "label": "Valid?"},
                    {"id": "work", "type": "process", "label": "Process"},
                    {"id": "end", "type": "end", "label": "End"},
                    {"id": "reject", "type": "end", "label": "Reject"},
                ],
                "flows": [
                    {"from": "start", "to": "check"},
                    {"from": "check", "to": "work", "label": "yes"},
                    {"from": "check", "to": "reject", "label": "no"},
                    {"from": "work", "to": "end"},
                ],
            }
        )
    elif template_type == "sequence":
        shared.update(
            {
                "participants": [
                    {"id": "client", "label": "Client"},
                    {"id": "api", "label": "API"},
                    {"id": "db", "label": "Database"},
                ],
                "messages": [
                    {"from": "client", "to": "api", "label": "request", "type": "sync"},
                    {"from": "api", "to": "db", "label": "query", "type": "async"},
                    {"from": "db", "to": "api", "label": "rows", "type": "return"},
                ],
            }
        )
    elif template_type == "state-machine":
        shared.update(
            {
                "states": [
                    {"id": "initial", "type": "initial", "label": "Initial"},
                    {"id": "active", "type": "state", "label": "Active"},
                    {"id": "final", "type": "final", "label": "Final"},
                ],
                "transitions": [
                    {"from": "initial", "to": "active", "label": "begin"},
                    {"from": "active", "to": "final", "label": "finish"},
                ],
            }
        )
    elif template_type == "er-diagram":
        shared.update(
            {
                "entities": [
                    {
                        "id": "user",
                        "label": "User",
                        "attributes": [
                            {"name": "id", "key": "PK", "type": "UUID"},
                            {"name": "name", "type": "TEXT"},
                        ],
                    },
                    {
                        "id": "order",
                        "label": "Order",
                        "attributes": [
                            {"name": "id", "key": "PK", "type": "UUID"},
                            {"name": "user_id", "key": "FK", "type": "UUID"},
                        ],
                    },
                ],
                "relationships": [
                    {
                        "from": "user",
                        "to": "order",
                        "label": "places",
                        "from_cardinality": "1",
                        "to_cardinality": "0..*",
                    }
                ],
            }
        )
    else:
        # A generic fixture lets maintainers include another registered type via
        # --types without editing this script first.
        shared.update(
            {
                "nodes": [
                    {"id": "a", "x": 140, "y": 240, "width": 180, "height": 80, "label": "A"},
                    {"id": "b", "x": 620, "y": 240, "width": 180, "height": 80, "label": "B"},
                ],
                "arrows": [{"source": "a", "target": "b", "label": "relation"}],
            }
        )
    return shared


def _matrix(styles: Sequence[int], diagram_types: Sequence[str], quick: bool) -> list[tuple[int, str]]:
    if not quick:
        return [(style, diagram_type) for style in styles for diagram_type in diagram_types]
    pairs: list[tuple[int, str]] = []
    for index, style in enumerate(styles):
        pairs.append((style, diagram_types[index % len(diagram_types)]))
    for diagram_type in diagram_types:
        pair = (styles[0], diagram_type)
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run style and diagram-type rendering regressions.")
    parser.add_argument("--styles", type=_parse_styles, default=list(range(1, 8)), help="comma-separated styles (default: 1-7)")
    parser.add_argument("--types", type=_parse_types, default=list(DEFAULT_TYPES), help=f"comma-separated types (default: {','.join(DEFAULT_TYPES)})")
    parser.add_argument("--quick", action="store_true", help="cover every style and type without the full cross-product")
    parser.add_argument("--png", action="store_true", help="also exercise the available PNG exporter")
    parser.add_argument("--output-dir", type=Path, help="keep generated artifacts in this directory")
    parser.add_argument("--report", type=Path, help="write the JSON summary to this file")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds allowed per render (default: 30)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("Error: --timeout must be positive.", file=sys.stderr)
        return 2
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.output_dir:
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="technical-diagram-regression-")
        output_dir = Path(temporary.name)
    input_dir = output_dir / ".inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    results: list[dict[str, object]] = []
    formats = "svg,json,png" if args.png else "svg,json"
    for style, diagram_type in _matrix(args.styles, args.types, args.quick):
        case_name = f"{diagram_type}-style{style}"
        input_path = input_dir / f"{case_name}.json"
        input_path.write_text(json.dumps(_sample(diagram_type, style), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            str(RENDERER),
            "--type",
            diagram_type,
            "--input",
            str(input_path),
            "--output",
            str(output_dir / case_name),
            "--formats",
            formats,
            "--validate",
        ]
        case_started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout,
            )
            ok = completed.returncode == 0
            details = (completed.stderr or completed.stdout).strip()
            results.append(
                {
                    "case": case_name,
                    "style": style,
                    "type": diagram_type,
                    "ok": ok,
                    "returncode": completed.returncode,
                    "seconds": round(time.monotonic() - case_started, 4),
                    **({"details": details[-2000:]} if not ok else {}),
                }
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "case": case_name,
                    "style": style,
                    "type": diagram_type,
                    "ok": False,
                    "returncode": None,
                    "seconds": round(time.monotonic() - case_started, 4),
                    "details": f"timed out after {args.timeout:g}s",
                }
            )

    passed = sum(1 for result in results if result["ok"])
    payload: dict[str, object] = {
        "ok": passed == len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "seconds": round(time.monotonic() - started, 4),
        "styles": args.styles,
        "types": args.types,
        "full_cross_product": not args.quick,
        "png": bool(args.png),
        "artifacts_kept": bool(args.output_dir),
        "output_dir": str(output_dir) if args.output_dir else None,
        "results": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        args.report.expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
    if temporary:
        temporary.cleanup()
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
