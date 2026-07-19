#!/usr/bin/env python3
"""Validate weekly brief date, filename, cutoff, and event-date invariants."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
from pathlib import Path
import re
import sys


EVENT_DATE_RE = re.compile(
    r"^\|\s*(?P<month>\d{1,2})月(?P<day>\d{1,2})(?:日)?"
    r"(?:[—-](?P<end_day>\d{1,2})日)?(?:发布)?\s*\|"
)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_cutoff(value: str) -> datetime:
    return datetime.fromisoformat(value)


def canonical_title(period_start: date, period_end: date) -> str:
    if period_start.year == period_end.year and period_start.month == period_end.month:
        return (
            f"# 数字健康周报｜{period_start.year}年{period_start.month}月"
            f"{period_start.day}日—{period_end.day}日"
        )
    if period_start.year == period_end.year:
        return (
            f"# 数字健康周报｜{period_start.year}年{period_start.month}月"
            f"{period_start.day}日—{period_end.month}月{period_end.day}日"
        )
    return (
        f"# 数字健康周报｜{period_start.year}年{period_start.month}月"
        f"{period_start.day}日—{period_end.year}年{period_end.month}月{period_end.day}日"
    )


def resolve_event_date(month: int, day: int, period_start: date, period_end: date) -> date | None:
    for year in sorted({period_start.year, period_end.year}):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if period_start <= candidate <= period_end:
            return candidate
    return None


def validate_report(
    file_path: Path,
    period_start: date,
    period_end: date,
    issue_date: date,
    cutoff: datetime,
    allow_custom_filename: bool = False,
) -> list[str]:
    errors: list[str] = []

    if period_start.weekday() != 0:
        errors.append("period_start must be Monday")
    if period_end.weekday() != 6:
        errors.append("period_end must be Sunday")
    if (period_end - period_start).days != 6:
        errors.append("period must span one Monday-to-Sunday natural week")
    if issue_date != period_end:
        errors.append("issue_date must equal period_end")
    if not period_start <= cutoff.date() <= period_end:
        errors.append("cutoff date must fall inside the reporting period")

    expected_name = f"DHWB-{issue_date:%Y%m%d}.md"
    if not allow_custom_filename and file_path.name != expected_name:
        errors.append(f"filename must be {expected_name}")

    try:
        content = file_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return errors + [f"cannot read UTF-8 report: {exc}"]

    if "\ufffd" in content:
        errors.append("report contains Unicode replacement characters")

    first_heading = next(
        (line.strip() for line in content.splitlines() if line.strip().startswith("# ")),
        "",
    )
    expected_title = canonical_title(period_start, period_end)
    if first_heading != expected_title:
        errors.append(f"first heading must be: {expected_title}")

    period_end_in_cutoff_zone = datetime.combine(period_end, time.max, cutoff.tzinfo)
    if cutoff < period_end_in_cutoff_zone:
        preamble = "\n".join(content.splitlines()[:15])
        if not ("截至" in preamble or "生成时点" in preamble):
            errors.append("partial-week report must state its cutoff time in the preamble")
        if "尚未结束" not in preamble:
            errors.append("partial-week report must state that the week has not ended")

    event_rows = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        match = EVENT_DATE_RE.match(line)
        if not match:
            continue
        event_rows += 1
        month = int(match.group("month"))
        start_day = int(match.group("day"))
        end_day = int(match.group("end_day") or start_day)
        for day_value in (start_day, end_day):
            event_date = resolve_event_date(month, day_value, period_start, period_end)
            if event_date is None:
                errors.append(f"line {line_number}: event date is outside the reporting period")
            elif event_date > cutoff.date():
                errors.append(f"line {line_number}: event date is later than the cutoff")

    if event_rows == 0:
        errors.append("no dated event rows found in Markdown tables")

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--period-start", required=True, type=parse_date)
    parser.add_argument("--period-end", required=True, type=parse_date)
    parser.add_argument("--issue-date", required=True, type=parse_date)
    parser.add_argument("--cutoff", required=True, type=parse_cutoff)
    parser.add_argument("--allow-custom-filename", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validate_report(
        file_path=args.file,
        period_start=args.period_start,
        period_end=args.period_end,
        issue_date=args.issue_date,
        cutoff=args.cutoff,
        allow_custom_filename=args.allow_custom_filename,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"OK: {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
