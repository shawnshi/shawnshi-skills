#!/usr/bin/env python3
"""Validate the heading topology of one periodic audit payload."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PERIODIC_HEADING_PATTERNS = {
    "weekly": re.compile(
        r"^## \[(\d{4}-W\d{2})\] Weekly Cognitive Audit(?:[^\r\n]*)$"
    ),
    "monthly": re.compile(
        r"^## \[(\d{4}-\d{2})\] Monthly Cognitive Audit(?:[^\r\n]*)$"
    ),
    "quarterly": re.compile(
        r"^## \[(\d{4}-Q[1-4])\] Quarterly Cognitive Audit(?:[^\r\n]*)$"
    ),
}
ATX_H1 = re.compile(r"(?m)^ {0,3}#(?!#)(?:[ \t]+|$)[^\r\n]*\r?$")
ATX_H2 = re.compile(r"(?m)^ {0,3}##(?!#)(?:[ \t]+|$)[^\r\n]*\r?$")
SETEXT_UNDERLINE = re.compile(r"(?m)^ {0,3}(?:=+|-+)[ \t]*\r?$")


def validate_periodic_topology(
    text: str,
    period_type: str | None,
    period_id: str | None,
) -> list[str]:
    if period_type is None and period_id is None:
        return []
    if period_type not in PERIODIC_HEADING_PATTERNS or not period_id:
        return ["period type and period id must identify one periodic audit"]
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    match = PERIODIC_HEADING_PATTERNS[period_type].fullmatch(first_line)
    if (
        match is None
        or match.group(1) != period_id
        or ATX_H1.search(text)
        or len(ATX_H2.findall(text)) != 1
        or SETEXT_UNDERLINE.search(text)
    ):
        return [
            "periodic audit must start with its unique target H2 heading; "
            "indented ATX H1/H2 and Setext H1/H2 are prohibited; "
            "all remaining headings must be H3 or deeper"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload_path")
    parser.add_argument(
        "--period-type",
        required=True,
        choices=tuple(PERIODIC_HEADING_PATTERNS),
    )
    parser.add_argument("--period-id", required=True)
    args = parser.parse_args()
    try:
        text = Path(args.payload_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        print(f"[FAIL] unable to read periodic payload: {exc}")
        return 1
    errors = validate_periodic_topology(text, args.period_type, args.period_id)
    if errors:
        print("[FAIL] periodic topology gate blocked the payload")
        for error in errors:
            print(f"- {error}")
        return 1
    print("[PASS] periodic topology gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
