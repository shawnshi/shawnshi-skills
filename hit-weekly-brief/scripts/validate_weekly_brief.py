#!/usr/bin/env python3
"""Validate weekly brief date, filename, cutoff, and event-date invariants."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def visible_content(content: str) -> str:
    """Ignore fenced examples while preserving source line numbers."""
    fence = ""
    lines: list[str] = []
    for line in content.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if (
                marker and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence) and not marker[2].strip()
            ):
                fence = ""
            lines.append("")
        elif marker and (marker[1][0] != "`" or "`" not in marker[2]):
            fence = marker[1]
            lines.append("")
        else:
            # Four-space/tab indented Markdown is code, not report structure.
            lines.append("" if line.startswith(("    ", "\t")) else line)
    return "\n".join(lines)


def report_header(content: str) -> str:
    return re.split(r"^ {0,3}##(?:[ \t]+|$)", content, maxsplit=1, flags=re.M)[0]


def metadata(content: str, label: str) -> str:
    """One exact, unformatted header field before the first level-two section."""
    preamble = report_header(visible_content(content))
    values = re.findall(rf"^{re.escape(label)}：[ \t]*(.+?)[ \t]*$", preamble, re.M)
    if len(values) != 1:
        raise ValueError(f"{label} must occur exactly once in the header")
    return values[0]


CHINESE_EVENT_DATE_RE = re.compile(
    r"^\|\s*(?P<month>\d{1,2})月(?P<day>\d{1,2})(?:日)?"
    r"(?:[—-](?P<end_day>\d{1,2})日)?(?:发布)?\s*\|"
)
ISO_EVENT_DATE_RE = re.compile(
    r"^\|\s*(?P<start>\d{4}-\d{2}-\d{2})"
    r"(?:\s*(?:—|至)\s*(?P<end>\d{4}-\d{2}-\d{2}))?\s*\|"
)
EMPTY_EVENT_MARKER = "本周期未发现符合纳入标准的事件"
PLACEHOLDER_RE = re.compile(
    r"\[(?:"
    r"PERIOD_START|PERIOD_END|ISSUE_DATE|REGION|AUDIENCE|"
    r"CUTOFF_TIME[^\]]*|YYYY-MM-DD[^\]]*|"
    r"按报告周期[^\]]*|待填写[^\]]*|"
    r"若周期尚未结束[^\]]*|"
    r"主体与动作|事实/来源主张|推断及适用条件|"
    r"高/中/低|原始页面 URL|直接来源编号|来源编号|"
    r"本期事实及来源|主张及限制|结论、条件及不确定性|"
    r"影响机制、适用地区、生效或实施时点、背景及不确定性|"
    r"事实依据、业务传导链及失效条件|覆盖范围、停止原因及影响结论的待核事项|"
    r"基于本期事件的结论[^\]]*|事实、来源机构主张[^\]]*|"
    r"说明影响机制[^\]]*|从已核实事实出发[^\]]*|未公开、来源冲突[^\]]*"
    r")\]"
)


EVENT_HEADER = ["事件日期", "主体与已核实动作", "事实或来源主张", "分析判断", "证据强度", "直接来源"]


def table_cells(line: str) -> list[str]:
    """Support escaped pipes; all other pipes delimit Markdown cells."""
    body = line.strip()[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def has_source_url(value: str) -> bool:
    """URL syntax only: no network access or claims about source authenticity."""
    for match in re.finditer(r"https?://[^\s<>\[\]）]+", value):
        candidate = match[0].rstrip(").,;，。；")
        try:
            parsed = urlsplit(candidate)
            if parsed.hostname and not parsed.username and not parsed.password and parsed.port != 0:
                return True
        except ValueError:
            continue
    return False


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


def resolve_event_date(
    month: int, day: int, period_start: date, period_end: date
) -> date | None:
    for year in sorted({period_start.year, period_end.year}):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if period_start <= candidate <= period_end:
            return candidate
    return None


def event_dates_from_row(
    line: str, period_start: date, period_end: date
) -> list[date | None]:
    iso_match = ISO_EVENT_DATE_RE.match(line)
    if iso_match:
        values = [iso_match.group("start")]
        if iso_match.group("end"):
            values.append(iso_match.group("end"))
        parsed: list[date | None] = []
        for value in values:
            try:
                parsed.append(date.fromisoformat(value))
            except ValueError:
                parsed.append(None)
        return parsed

    chinese_match = CHINESE_EVENT_DATE_RE.match(line)
    if not chinese_match:
        return []
    month = int(chinese_match.group("month"))
    start_day = int(chinese_match.group("day"))
    end_day = int(chinese_match.group("end_day") or start_day)
    days = [start_day] if start_day == end_day else [start_day, end_day]
    return [
        resolve_event_date(month, day_value, period_start, period_end)
        for day_value in days
    ]


def validate_report(
    file_path: Path,
    period_start: date,
    period_end: date,
    issue_date: date,
    cutoff: datetime,
    allow_custom_filename: bool = False,
    allow_custom_period: bool = False,
    now: datetime | None = None,
    report_timezone: str = "Asia/Shanghai",
) -> list[str]:
    errors: list[str] = []

    if not allow_custom_period:
        if period_start.weekday() != 0:
            errors.append("period_start must be Monday")
        if period_end.weekday() != 6:
            errors.append("period_end must be Sunday")
        if (period_end - period_start).days != 6:
            errors.append("period must span one Monday-to-Sunday natural week")
    else:
        if period_start > period_end:
            errors.append("period_start must be on or before period_end")

    if issue_date != period_end:
        errors.append("issue_date must equal period_end")

    if cutoff.tzinfo is None or cutoff.tzinfo.utcoffset(cutoff) is None:
        errors.append(
            "cutoff must include explicit timezone offset (e.g. 2026-07-19T08:58:00+08:00 or 2026-07-19T00:58:00Z)"
        )

    if now is not None and (now.tzinfo is None or now.tzinfo.utcoffset(now) is None):
        errors.append(
            "now must include explicit timezone offset (e.g. 2026-07-20T00:00:00+08:00 or 2026-07-20T00:00:00Z)"
        )

    now_dt = now if now is not None else datetime.now(timezone.utc)
    if (
        cutoff.tzinfo is not None
        and cutoff.tzinfo.utcoffset(cutoff) is not None
        and now_dt.tzinfo is not None
        and now_dt.tzinfo.utcoffset(now_dt) is not None
        and cutoff > now_dt
    ):
        errors.append("cutoff cannot be in the future")

    try:
        report_zone = ZoneInfo(report_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return errors + ["report timezone unavailable or invalid"]
    cutoff_date = (
        cutoff.astimezone(report_zone).date()
        if cutoff.utcoffset() is not None
        else cutoff.date()
    )
    if cutoff_date < period_start:
        errors.append("cutoff date cannot be earlier than period_start")

    expected_name = f"DHWB-{issue_date:%Y%m%d}.md"
    if not allow_custom_filename and file_path.name != expected_name:
        errors.append(f"filename must be {expected_name}")

    try:
        content = file_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return errors + [f"cannot read UTF-8 report: {exc}"]

    if "\ufffd" in content:
        errors.append("report contains Unicode replacement characters")
    if "<!--" in content or "-->" in content:
        errors.append("HTML comments are not supported in final reports")

    placeholders = sorted(set(PLACEHOLDER_RE.findall(content)))
    if placeholders:
        errors.append("report contains unresolved template placeholders")

    content = visible_content(content)
    first_heading = next(
        (
            line.strip()
            for line in content.splitlines()
            if line.strip().startswith("# ")
        ),
        "",
    )
    expected_title = canonical_title(period_start, period_end)
    if first_heading != expected_title:
        errors.append(f"first heading must be: {expected_title}")

    try:
        if (
            metadata(content, "报告周期")
            != f"{period_start.isoformat()} 至 {period_end.isoformat()}"
        ):
            errors.append("报告周期 does not match arguments")
        if parse_date(metadata(content, "出刊日期")) != issue_date:
            errors.append("出刊日期 does not match issue_date")
        body_cutoff = parse_cutoff(metadata(content, "生成时点"))
        if body_cutoff.utcoffset() is None or body_cutoff != cutoff:
            errors.append("生成时点 does not match aware cutoff")
        if metadata(content, "报告时区") != report_timezone:
            errors.append("报告时区 does not match report timezone")
    except ValueError as exc:
        errors.append(f"invalid report metadata: {exc}")

    is_partial_period = cutoff_date <= period_end
    if is_partial_period:
        preamble = report_header(content)
        if not ("截至" in preamble or "生成时点" in preamble):
            errors.append(
                "partial-week report must state its cutoff time in the preamble"
            )
        if "尚未结束" not in preamble:
            errors.append("partial-week report must state that the week has not ended")

    event_rows = 0
    in_events = False
    section_count = 0
    empty_markers = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if line.startswith("## "):
            in_events = line == "## 关键事件与来源"
            section_count += int(in_events)
        if not in_events:
            continue
        if line == EMPTY_EVENT_MARKER:
            empty_markers += 1
        if not line.startswith("|"):
            continue
        cells = table_cells(line)
        if cells[0] == "事件日期":
            if cells != EVENT_HEADER:
                errors.append(f"line {line_number}: event header must match the six-column template")
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            if len(cells) != 6:
                errors.append(f"line {line_number}: event separator must have six columns")
            continue
        event_rows += 1
        if len(cells) != 6 or not all(cells):
            errors.append(f"line {line_number}: event row must contain six nonempty columns")
        elif not has_source_url(cells[-1]):
            errors.append(f"line {line_number}: event row requires a direct HTTP(S) source URL")
        event_dates = event_dates_from_row(line, period_start, period_end)
        if not event_dates:
            errors.append(f"line {line_number}: malformed event date row")
            continue
        if (
            len(event_dates) == 2
            and event_dates[0] is not None
            and event_dates[1] is not None
            and event_dates[0] > event_dates[1]
        ):
            errors.append(f"line {line_number}: inverted event range")
        for event_date in event_dates:
            if event_date is None:
                errors.append(
                    f"line {line_number}: event date is invalid or outside the reporting period"
                )
            elif not period_start <= event_date <= period_end:
                errors.append(
                    f"line {line_number}: event date is outside the reporting period"
                )
            elif event_date > cutoff_date:
                errors.append(
                    f"line {line_number}: event date is later than the cutoff"
                )

    if section_count != 1:
        errors.append("exactly one ## 关键事件与来源 section required")
    if empty_markers > 1 or (event_rows and empty_markers):
        errors.append("empty-period marker contradicts event rows or is duplicated")
    if event_rows == 0 and empty_markers != 1:
        errors.append(
            "no dated event rows found; use the explicit empty-period marker when there are no qualifying events"
        )

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--period-start", required=True, type=parse_date)
    parser.add_argument("--period-end", required=True, type=parse_date)
    parser.add_argument("--issue-date", required=True, type=parse_date)
    parser.add_argument(
        "--cutoff",
        required=True,
        type=parse_cutoff,
        help="cutoff timestamp with explicit ISO-8601 offset (e.g. 2026-07-19T08:58:00+08:00 or 2026-07-19T00:58:00Z)",
    )
    parser.add_argument("--report-timezone", default="Asia/Shanghai")
    parser.add_argument("--allow-custom-filename", action="store_true")
    parser.add_argument("--allow-custom-period", action="store_true")
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
        allow_custom_period=args.allow_custom_period,
        report_timezone=args.report_timezone,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"OK: {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
