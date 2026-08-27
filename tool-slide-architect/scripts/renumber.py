"""Renumber v2 Page fields while preserving stable Slide_ID values."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from safe_io import SafeWriteError, atomic_write_text, reject_symlink_path
from validator import SCHEMA_VERSION, SLIDE_RE, StructuredArgumentParser, VALIDATION_SCOPE, audit_outline, issue, load_source


def renumber_content(content: str) -> tuple[str, int]:
    matches = list(SLIDE_RE.finditer(content))
    if not matches:
        raise SafeWriteError("E_NO_SLIDES", "No complete v2 slides were found.")

    ordinal = 0

    def replace_slide(match: re.Match[str]) -> str:
        nonlocal ordinal
        ordinal += 1
        whole = match.group(0)
        relative_start = match.start("header") - match.start()
        relative_end = match.end("header") - match.start()
        header = whole[relative_start:relative_end]
        updated, count = re.subn(r"(?m)^Page:[ \t]*[^\n]*$", f"Page: {ordinal}", header)
        if count != 1:
            raise SafeWriteError("E_PAGE_FIELD", "Each slide header must contain exactly one Page field.", slide=ordinal, count=count)
        return whole[:relative_start] + updated + whole[relative_end:]

    result = SLIDE_RE.sub(replace_slide, content)
    result, count = re.subn(r"(?m)^Slide_Count:[ \t]*[^\n]*$", f"Slide_Count: {ordinal}", result)
    if count != 1:
        raise SafeWriteError("E_SLIDE_COUNT_FIELD", "DECK_METADATA must contain exactly one Slide_Count field.", count=count)
    return result, ordinal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StructuredArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="outline.md or a directory containing outline.md")
    parser.add_argument("--write", action="store_true", help="Atomically replace the input file; default writes Markdown to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        reject_symlink_path(args.path)
        content, source_files = load_source(args.path)
        source_path = Path(source_files[0])
        reject_symlink_path(source_path)
        updated, count = renumber_content(content)
        report, _ = audit_outline(updated)
        if report["errors"]:
            raise SafeWriteError("E_RENUMBER_VALIDATION", "Renumbered blueprint still has structural errors.", validation_errors=report["errors"])
        if not args.write:
            sys.stdout.write(updated)
            return 0
        atomic_write_text(source_path, updated, force=True)
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "renumbered", "output": str(source_path), "slide_count": count}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, SafeWriteError, OSError, UnicodeError) as exc:
        error = exc.as_issue() if isinstance(exc, SafeWriteError) else issue("E_FILE_IO", str(exc))
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [error]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "source_schema_version": SCHEMA_VERSION, "validation_scope": VALIDATION_SCOPE, "status": "fail", "errors": [issue("E_INTERNAL", "Unexpected renumber failure.", detail=f"{type(exc).__name__}: {exc}")]}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
