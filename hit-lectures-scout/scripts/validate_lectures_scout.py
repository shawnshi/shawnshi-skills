#!/usr/bin/env python3
"""Structural gate only: does not verify DOI identity, clinical evidence, or source access."""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EMPTY = "本周期未发现符合纳入标准的研究"
STATUSES = {"同行评审", "会议评审", "预印本", "未同行评审", "评审状态未知"}
RESEARCH_HEADER = ["研究ID", "日期", "标题", "评审状态", "版本", "永久链接", "来源编号"]
SOURCE_HEADER = ["来源编号", "原始链接"]
# Known template tokens only: scientific intervals and Markdown are not holes.
PLACEHOLDER_RE = re.compile(
    r"\[(?:PERIOD_START|PERIOD_END|ISSUE_DATE|CUTOFF_TIME[^\]]*|"
    r"WINDOW_MODE|REPORT_TIMEZONE|YYYY-MM-DD[^\]]*|待填写[^\]]*|"
    r"标题|论文标题|期刊论文/会议论文/预印本/方法论文|"
    r"DOI/注册号/原始链接|原始HTTPS链接|永久HTTPS链接)\]"
)


def structural_lines(content: str) -> list[str]:
    """Top-level Markdown subset; preserve line numbers, hide code and comments.

    Fences use >=3 backticks/tildes with <=3 spaces indentation; only the same
    character and at least the opening length closes them. Indented code is not
    structural. This is deliberately not a general Markdown renderer.
    """
    lines = []
    fence = ""
    in_comment = False
    for line in content.splitlines():
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*", line):
                fence = ""
            lines.append("")
            continue
        # Fence info is literal, but an existing comment masks fake openers.
        opening = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if not in_comment and opening and (opening[1][0] == "~" or "`" not in opening[2]):
            fence = opening[1]
            lines.append("")
            continue
        # Hide whole comment-bearing lines, not just the comment delimiters:
        # inline fragments must never be promoted into standalone metadata.
        if in_comment or "<!--" in line:
            for delimiter in re.findall(r"<!--|-->", line):
                in_comment = delimiter == "<!--"
            lines.append("")
            continue
        indent = 0
        for char in line:
            if char == " ":
                indent += 1
            elif char == "\t":
                indent += 4 - indent % 4
            else:
                break
            if indent >= 4:
                break
        lines.append("" if indent >= 4 else line)
    return lines


def markdown_heading(line: str) -> str:
    match = re.fullmatch(r" {0,3}(#{1,6})[ \t]+(.+?)[ \t]*", line)
    if not match:
        return ""
    return match[1] + " " + re.sub(r"[ \t]+#+$", "", match[2])


def table_cells(line: str) -> list[str]:
    """Split outer-pipe rows on unescaped pipes; retain cell Markdown verbatim."""
    cells = []
    start = 0
    escaped = False
    for index, char in enumerate(line):
        if char == "|" and not escaped:
            cells.append(line[start:index].strip())
            start = index + 1
        escaped = char == "\\" and not escaped
    cells.append(line[start:].strip())
    # Do not strip arbitrary pipes: extra empty columns must stay observable.
    if len(cells) < 3 or cells[0] or cells[-1]:
        return []
    return cells[1:-1]


def metadata(content: str, label: str) -> str:
    preamble = []
    for line in structural_lines(content):
        if markdown_heading(line).startswith(("## ", "### ", "#### ", "##### ", "###### ")):
            break
        preamble.append(line)
    values = re.findall(rf"^{re.escape(label)}：([^\n]*)$", "\n".join(preamble), re.M)
    if len(values) != 1 or not values[0].strip():
        raise ValueError(f"{label} must occur exactly once in header")
    return values[0].strip()


def original_link(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Access validates numeric syntax and the legal port range.
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not re.search(r"\s|[\[\]<>]", value))
    except ValueError:
        return False


def validate_report(file_path: Path, period_start: date, period_end: date,
                    issue_date: date, cutoff: datetime, window_mode: str = "explicit",
                    report_timezone: str = "Asia/Shanghai", allow_custom_filename: bool = False,
                    now: datetime | None = None) -> list[str]:
    errors = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return [f"source IO: {exc}"]
    try:
        zone = ZoneInfo(report_timezone)
        if cutoff.utcoffset() is None:
            return ["cutoff must include timezone"]
        cutoff_date = cutoff.astimezone(zone).date()
        if cutoff > (now or datetime.now(timezone.utc)):
            errors.append("future cutoff")
        if period_start > period_end or cutoff_date < period_start:
            errors.append("invalid period/cutoff")
        if window_mode not in {"explicit", "generated"}:
            errors.append("unknown window mode")
        expected_issue = period_end if window_mode == "explicit" else cutoff_date
        if issue_date != expected_issue:
            errors.append("issue date must use explicit window end, otherwise generation date")
        expected = {"报告周期": f"{period_start} 至 {period_end}", "出刊日期": str(issue_date),
                    "报告时区": report_timezone, "命名依据": window_mode}
        for key, value in expected.items():
            if metadata(content, key) != value:
                errors.append(f"{key} mismatch")
        body_cutoff = datetime.fromisoformat(metadata(content, "生成时点"))
        if body_cutoff.utcoffset() is None or body_cutoff != cutoff:
            errors.append("生成时点 mismatch")
    except (ValueError, ZoneInfoNotFoundError) as exc:
        return errors + [f"invalid metadata: {exc}"]
    if not allow_custom_filename and file_path.name != f"DHLS-{issue_date:%Y%m%d}.md":
        errors.append("issue filename mismatch")
    lines = structural_lines(content)
    heading = next((s for s in lines if s.startswith("# ")), "")
    if heading != f"# 医疗数字化文献侦察报告 - {issue_date}":
        errors.append("title issue date mismatch")
    if "\ufffd" in content or PLACEHOLDER_RE.search(content):
        errors.append("unresolved placeholder or replacement character")

    section = ""
    sections = []
    ids = set()
    sources = set()
    references = []
    current_rows = 0
    empty_count = 0
    tables = {name: [] for name in ("## 本期研究", "## 背景研究", "## 来源")}
    in_table = False
    for number, raw_line in enumerate(lines, 1):
        heading = markdown_heading(raw_line)
        line = raw_line.strip()
        if heading:
            section = heading
            sections.append(section)
        if section == "## 本期研究" and line == EMPTY:
            empty_count += 1
        if not line.startswith("|") or section not in tables:
            in_table = False
            continue
        cells = table_cells(line)
        if not in_table:
            tables[section].append([])
        tables[section][-1].append((number, cells))
        in_table = True
        if cells and all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        if section == "## 来源":
            if cells == SOURCE_HEADER:
                continue
            if len(cells) != 2 or not re.fullmatch(r"S\d+", cells[0]) or not original_link(cells[1]):
                errors.append(f"line {number}: invalid source row/original HTTPS link")
                continue
            if cells[0] in sources:
                errors.append("duplicate source ID")
            sources.add(cells[0])
            continue
        if cells == RESEARCH_HEADER:
            continue
        if len(cells) != 7:
            errors.append(f"line {number}: malformed research row")
            continue
        rid, published, title, status, version, link, refs = cells
        if section == "## 本期研究":
            current_rows += 1
        if not re.fullmatch(r"R\d+", rid) or rid in ids:
            errors.append(f"line {number}: invalid/duplicate research ID")
        ids.add(rid)
        try:
            day = date.fromisoformat(published)
            if day > cutoff_date:
                errors.append("research date after cutoff")
            if section == "## 本期研究" and not period_start <= day <= min(period_end, cutoff_date):
                errors.append("current research outside period/cutoff")
        except ValueError:
            errors.append("invalid research date")
        if not title or status not in STATUSES:
            errors.append("missing title or unknown review status")
        if not version or version in {"未知", "未核实", "不适用", "-"}:
            errors.append("explicit version required")
        if not original_link(link):
            errors.append("permanent/original HTTPS link required")
        if not re.fullmatch(r"S\d+(?:,S\d+)*", refs):
            errors.append("invalid source reference IDs")
        references.extend(refs.split(","))
    if sections.count("## 本期研究") != 1 or sections.count("## 来源") != 1 or sections.count("## 背景研究") > 1:
        errors.append("required/duplicate research or source section")
    if (current_rows == 0 and empty_count != 1) or (current_rows and empty_count) or empty_count > 1:
        errors.append("empty research marker missing or contradictory")
    visible = "\n".join(lines)
    references.extend(re.findall(r"\[(S\d+)\]", visible))
    for name, blocks in tables.items():
        header = SOURCE_HEADER if name == "## 来源" else RESEARCH_HEADER
        # Legacy genuine zero-result reports may omit both tables. Any table
        # present, even an empty one, must have the exact header and delimiter.
        required = (name == "## 本期研究" and (current_rows or empty_count != 1)
                    or name == "## 来源" and (ids or sources or references))
        if len(blocks) > 1 or (required and not blocks):
            errors.append(f"{name}: required/duplicate table")
        for block in blocks:
            number = block[0][0]
            rows = [cells for _, cells in block]
            if rows[0] != header or sum(cells == header for cells in rows) != 1:
                errors.append(f"line {number}: correct unique table header required")
            separators = [i for i, cells in enumerate(rows) if cells and
                          all(re.fullmatch(r":?-{3,}:?", c) for c in cells)]
            if separators != [1] or len(rows[1]) != len(header):
                errors.append(f"line {number}: adjacent table separator with {len(header)} columns required")
    if any(ref not in sources for ref in references):
        errors.append("unknown source reference ID")
    if any(ref not in ids for ref in re.findall(r"\[(R\d+)\]", visible)):
        errors.append("unknown research reference ID")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    for flag in ("period-start", "period-end", "issue-date"):
        parser.add_argument("--" + flag, required=True, type=date.fromisoformat)
    parser.add_argument("--cutoff", required=True, type=datetime.fromisoformat)
    parser.add_argument("--window-mode", choices=("explicit", "generated"), default="explicit")
    parser.add_argument("--report-timezone", default="Asia/Shanghai")
    parser.add_argument("--allow-custom-filename", action="store_true")
    args = vars(parser.parse_args(argv))
    args["file_path"] = args.pop("file")
    errors = validate_report(**args)
    for error in errors:
        print("FAIL:", error)
    if not errors:
        print("OK: structural checks only; DOI identity, clinical strength and source access not verified")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
