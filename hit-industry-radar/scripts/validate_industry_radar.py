#!/usr/bin/env python3
"""Read-only structural radar gate; does not verify facts, lineage or URL access."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EMPTY = "本周期未发现符合纳入标准的公开事件"
PARTIAL_EMPTY = "覆盖不完整，暂无可纳入的已核实事件"
BLOCKED_EMPTY = "检索阻塞，不能判定本期事件"
EVENT_HEADER = [
    "事件ID",
    "事件日期",
    "发布日期",
    "主体",
    "已核实动作",
    "事件键",
    "证据强度",
    "来源编号",
    "影响（推断）",
    "限制",
]
SOURCE_HEADER = ["来源编号", "原始链接", "血缘", "类型", "访问状态"]
COVERAGE_HEADER = ["检索面", "状态", "查询/来源及结果说明"]
HEADERS = {
    "## 关键事件": EVENT_HEADER,
    "## 来源": SOURCE_HEADER,
    "## 检索覆盖": COVERAGE_HEADER,
}
PLACEHOLDER_RE = re.compile(
    r"\[(?:PERIOD_START|PERIOD_END|ISSUE_DATE|CUTOFF_TIME[^\]]*|REPORT_TIMEZONE|WINDOW_MODE|待填写[^\]]*|YYYY-MM-DD[^\]]*)\]"
)


def metadata(content: str, label: str) -> str:
    preamble = content.split("\n## ", 1)[0]
    values = re.findall(rf"^{re.escape(label)}：([^\r\n]*)\r?$", preamble, re.M)
    if len(values) != 1:
        raise ValueError(f"{label} must occur exactly once in header")
    value = values[0].strip()
    if not value:
        raise ValueError(f"{label} must not be blank")
    return value


def visible_lines(content: str, errors: list[str]) -> list[str]:
    """New reports only: top-level Markdown; code keeps blank physical lines.

    Legacy metadata/identity parsing deliberately does not use this filter.
    Raw HTML and multiline inline code are outside the supported subset.
    """
    if "<!--" in content or "-->" in content:
        errors.append("HTML comments are not allowed in final reports")
    result: list[str] = []
    fence = ""
    preamble = True
    html_tag = False
    html_block = ""
    for number, raw in enumerate(content.splitlines(), 1):
        if fence:
            if re.fullmatch(
                r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*",
                raw,
            ):
                fence = ""
            result.append("")
            continue
        if raw.startswith("    ") or re.match(r" {0,3}\t", raw):
            result.append("")
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", raw)
        if opening and (opening[1][0] == "~" or "`" not in opening[2]):
            fence = opening[1]
            result.append("")
            continue

        line = raw.lstrip(" ").rstrip()

        if html_block:
            if re.search(html_block, line, re.IGNORECASE):
                html_block = ""
            result.append("")
            continue

        if html_tag:
            if ">" in line:
                html_tag = False
            result.append("")
            continue

        # A span may contain different-length backtick runs, but cannot cross lines.
        ticks = ""
        stripped_parts: list[str] = []
        last_idx = 0
        for match in re.finditer(r"`+", line):
            if not ticks:
                prefix = line[: match.start()]
                escaped = (len(prefix) - len(prefix.rstrip("\\"))) % 2
                t = match[0][escaped:]
                if t:
                    ticks = t
                    stripped_parts.append(line[last_idx : match.start() + escaped])
            elif match[0] == ticks:
                ticks = ""
                last_idx = match.end()
        if not ticks:
            stripped_parts.append(line[last_idx:])
        else:
            errors.append(f"line {number}: inline code must close on the same line")

        text_outside_code = "".join(stripped_parts)

        # Check for HTML blocks like <script, <style, <pre, <textarea
        block_match = re.search(
            r"<(script|style|pre|textarea)(?:\s|>|$)", text_outside_code, re.IGNORECASE
        )
        if block_match:
            errors.append(f"line {number}: raw HTML is not supported")
            tag = block_match.group(1).lower()
            if not re.search(rf"</{tag}>", text_outside_code, re.IGNORECASE):
                html_block = rf"</{tag}>"
            result.append("")
            continue

        # Check for single-line raw HTML tag
        if re.search(
            r"<(?:/?[A-Za-z][A-Za-z0-9-]*(?:\s[^>]*|/?)|![A-Z][^>]*|\?.*)>",
            text_outside_code,
        ):
            errors.append(f"line {number}: raw HTML is not supported")
            result.append("")
            continue

        # Check for multiline tag opening: < followed by tag name or !/?, not closed with >
        if re.search(
            r"<(?:/?[A-Za-z][A-Za-z0-9-]*|![A-Z]|\?)[^>]*$",
            text_outside_code,
        ):
            errors.append(f"line {number}: raw HTML is not supported")
            html_tag = True
            result.append("")
            continue

        if line.startswith("## "):
            preamble = False
        if preamble and re.match(r"(?:>|[-+*]\s|\d+[.)]\s)", line):
            errors.append(f"line {number}: header must not use quote/list containers")
        # Preserve column-zero metadata rules; normalize only section/table indent.
        result.append(line if line.startswith(("## ", "|")) else raw)
    if fence:
        errors.append("unclosed fenced code block")
    if html_block:
        errors.append(f"unclosed {html_block[2:-1]} block")
    if html_tag:
        errors.append("unclosed raw HTML tag")
    return result


def parse_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    return date.fromisoformat(value)


def original_link(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        # urlsplit validates the bracketed address; require a bare host/port authority.
        if ("[" in parsed.netloc or "]" in parsed.netloc) and not re.fullmatch(
            r"\[[^\[\]]+\](?::[0-9]+)?", parsed.netloc
        ):
            return False
        return (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not re.search(r"\s|[<>\\]|[\x00-\x1f\x7f]", value)
            and not re.search(r"[\[\]]", parsed.path + parsed.query + parsed.fragment)
        )
    except ValueError:
        return False


def canonical_title(period_start: date, period_end: date) -> str:
    return f"# 医疗行业雷达｜{period_start} 至 {period_end}"


def validate_report(
    file_path: Path,
    period_start: date,
    period_end: date,
    issue_date: date,
    cutoff: datetime,
    window_mode: str = "rolling7",
    report_timezone: str = "Asia/Shanghai",
    allow_custom_filename: bool = False,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return [f"source IO: {exc}"]
    if not content.strip() or "\ufffd" in content or content.startswith("\ufeff"):
        errors.append("empty report, BOM or replacement character")
    if PLACEHOLDER_RE.search(content):
        errors.append("unresolved template placeholder")
    try:
        zone = ZoneInfo(report_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return errors + ["report timezone unavailable or invalid"]
    now_dt = now if now is not None else datetime.now(timezone.utc)
    if cutoff.utcoffset() is None or now_dt.utcoffset() is None:
        return errors + ["cutoff and now must include timezone"]
    cutoff_date = cutoff.astimezone(zone).date()
    if cutoff > now_dt:
        errors.append("future cutoff")
    if period_start > period_end or period_end > cutoff_date:
        errors.append("invalid period or future period end")
    if issue_date != period_end:
        errors.append("issue date must equal period end")
    if window_mode == "rolling7":
        if period_end != cutoff_date or period_start != cutoff_date - timedelta(days=6):
            errors.append("rolling7 must include today and the previous six dates")
    elif window_mode == "natural_week":
        if period_end != cutoff_date or period_start != cutoff_date - timedelta(
            days=cutoff_date.weekday()
        ):
            errors.append("natural_week must run Monday through cutoff date")
    elif window_mode != "explicit":
        errors.append("unknown window mode")
    if (
        not allow_custom_filename
        and file_path.name != f"DHWB-Radar-{issue_date:%Y%m%d}.md"
    ):
        errors.append("issue filename mismatch")
    lines = visible_lines(content, errors)
    visible = "\n".join(lines)
    if not lines or lines[0] != canonical_title(period_start, period_end):
        errors.append("canonical title mismatch")
    try:
        expected = {
            "报告周期": f"{period_start} 至 {period_end}",
            "出刊日期": str(issue_date),
            "报告时区": report_timezone,
            "窗口模式": window_mode,
        }
        for label, value in expected.items():
            if metadata(visible, label) != value:
                errors.append(f"{label} mismatch")
        body_cutoff = datetime.fromisoformat(metadata(visible, "生成时点"))
        if body_cutoff.utcoffset() is None or body_cutoff != cutoff:
            errors.append("生成时点 mismatch")
        metadata(visible, "报告范围")
        status = metadata(visible, "检索状态")
        if status not in {"complete", "partial", "blocked"}:
            errors.append("invalid search status")
    except ValueError as exc:
        return errors + [f"invalid metadata: {exc}"]

    section = ""
    sections: dict[str, list[str]] = {}
    tables: dict[str, list[list[str]]] = {key: [] for key in HEADERS}
    header_counts = dict.fromkeys(HEADERS, 0)
    header_lines = dict.fromkeys(HEADERS, 0)
    table_ends = dict.fromkeys(HEADERS, 0)
    markers: list[str] = []
    for number, raw in enumerate(lines, 1):
        line = raw.strip(" \t")
        if line.startswith("## "):
            section = line
            if section in sections:
                errors.append(f"duplicate section: {section}")
            sections.setdefault(section, [])
            continue
        if section:
            sections[section].append(line)
        if section not in HEADERS or not line:
            continue
        if section == "## 关键事件" and line in {EMPTY, PARTIAL_EMPTY, BLOCKED_EMPTY}:
            markers.append(line)
            continue
        if not line.startswith("|") or not line.endswith("|"):
            errors.append(f"line {number}: structured section requires table rows")
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells == HEADERS[section]:
            header_counts[section] += 1
            header_lines[section] = number
            next_line = lines[number].strip() if number < len(lines) else ""
            separator = [cell.strip() for cell in next_line[1:-1].split("|")]
            if (
                not next_line.startswith("|")
                or not next_line.endswith("|")
                or len(separator) != len(cells)
                or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
            ):
                errors.append(
                    f"line {number}: table header requires adjacent separator"
                )
            continue
        if len(cells) == len(HEADERS[section]) and all(
            re.fullmatch(r":?-{3,}:?", c) for c in cells
        ):
            if header_lines[section] != number - 1:
                errors.append(
                    f"line {number}: separator must immediately follow table header"
                )
            table_ends[section] = number
            continue
        if not table_ends[section] or table_ends[section] != number - 1:
            errors.append(
                f"line {number}: table row must follow separator or contiguous row"
            )
        table_ends[section] = number
        if len(cells) != len(HEADERS[section]) or not all(cells):
            errors.append(f"line {number}: malformed or empty table cell")
            continue
        tables[section].append(cells)
    for name in (*HEADERS, "## 结论摘要", "## 信息缺口"):
        if name not in sections:
            errors.append(f"missing section: {name}")
        elif name not in HEADERS and not any(sections[name]):
            errors.append(f"empty section: {name}")
    for name, count in header_counts.items():
        if count != 1:
            errors.append(f"exactly one table header required: {name}")

    sources: dict[str, list[str]] = {}
    urls: set[tuple[str, str, str, str]] = set()
    for sid, url, lineage, kind, access in tables["## 来源"]:
        if not re.fullmatch(r"S\d+", sid) or sid in sources:
            errors.append("invalid/duplicate source ID")
        if not original_link(url):
            errors.append("invalid original HTTP(S) URL")
        else:
            parsed = urlsplit(url)
            # Valid authorities contain no credentials; fold host case, not path/query.
            url_key = (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.query,
            )
            if url_key in urls:
                errors.append("duplicate source URL")
            urls.add(url_key)
        if not re.fullmatch(r"L\d+", lineage):
            errors.append("invalid source lineage ID")
        if kind not in {
            "primary",
            "secondary",
            "marketing",
            "unverified",
        } or access not in {"accessed", "unavailable"}:
            errors.append("invalid source type/access")
        sources[sid] = [url, lineage, kind, access]

    ids: set[str] = set()
    keys: set[str] = set()
    events = tables["## 关键事件"]
    for (
        rid,
        happened,
        published,
        _subject,
        _action,
        key,
        evidence,
        refs,
        _impact,
        _limits,
    ) in events:
        if not re.fullmatch(r"E\d+", rid) or rid in ids:
            errors.append("invalid/duplicate event ID")
        ids.add(rid)
        key = re.sub(r"\s+", "", key).casefold()
        if key in keys:
            errors.append("duplicate event key")
        keys.add(key)
        try:
            day = parse_date(happened)
            if not period_start <= day <= min(period_end, cutoff_date):
                errors.append("event outside period/cutoff")
            if published != "未知" and parse_date(published) > cutoff_date:
                errors.append("publication after cutoff")
        except ValueError:
            errors.append(
                "invalid event/publication date; unknown event belongs in leads"
            )
        if evidence not in {"E1", "E2"}:
            errors.append("event evidence must be E1 or E2")
        ref_ids = refs.split(",")
        if not re.fullmatch(r"S\d+(?:,S\d+)*", refs) or len(set(ref_ids)) != len(
            ref_ids
        ):
            errors.append("invalid/duplicate source references")
        if any(sid not in sources for sid in ref_ids):
            errors.append("unknown source reference ID")
        usable = [
            sources[sid]
            for sid in ref_ids
            if sid in sources
            and sources[sid][3] == "accessed"
            and sources[sid][2] != "unverified"
        ]
        if not any(source[2] in {"primary", "marketing"} for source in usable):
            errors.append("event needs an accessed direct source")
        if evidence == "E2" and (
            len({source[1] for source in usable}) < 2
            or not any(source[2] != "marketing" for source in usable)
        ):
            errors.append("E2 needs independent usable lineages, not marketing alone")
    expected_marker = {
        "complete": EMPTY,
        "partial": PARTIAL_EMPTY,
        "blocked": BLOCKED_EMPTY,
    }.get(status)
    if (events and markers) or (not events and markers != [expected_marker]):
        errors.append("empty/event marker missing or contradictory")
    if status == "blocked" and (
        events or any(s[3] == "accessed" for s in sources.values())
    ):
        errors.append("blocked cannot contain verified events or accessed sources")

    coverage = tables["## 检索覆盖"]
    names: set[str] = set()
    states = []
    for name, state, _note in coverage:
        if name in names:
            errors.append("duplicate coverage scope")
        names.add(name)
        states.append(state)
        if state not in {"complete", "partial", "blocked"}:
            errors.append("invalid coverage status")
    if not coverage:
        errors.append("coverage evidence required")
    if status == "complete" and any(state != "complete" for state in states):
        errors.append("complete contradicts coverage gaps")
    if status == "partial" and (
        not any(state in {"complete", "partial"} for state in states)
        or all(state == "complete" for state in states)
    ):
        errors.append("partial requires usable coverage and a disclosed gap")
    if status == "blocked" and any(state != "blocked" for state in states):
        errors.append("blocked contradicts usable coverage")
    if any(ref not in sources for ref in re.findall(r"\[(S\d+)\]", visible)):
        errors.append("unknown narrative source reference ID")
    if any(ref not in ids for ref in re.findall(r"\[(E\d+)\]", visible)):
        errors.append("unknown narrative event reference ID")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    for flag in ("period-start", "period-end", "issue-date"):
        parser.add_argument("--" + flag, required=True, type=parse_date)
    parser.add_argument("--cutoff", required=True, type=datetime.fromisoformat)
    parser.add_argument(
        "--window-mode",
        choices=("rolling7", "natural_week", "explicit"),
        default="rolling7",
    )
    parser.add_argument("--report-timezone", default="Asia/Shanghai")
    parser.add_argument("--allow-custom-filename", action="store_true")
    args = vars(parser.parse_args(argv))
    args["file_path"] = args.pop("file")
    errors = validate_report(**args)
    for error in errors:
        print("FAIL:", error)
    if not errors:
        print(
            "OK: structural checks only; facts, lineage, source access and archive safety not verified"
        )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
