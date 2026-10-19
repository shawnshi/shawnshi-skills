#!/usr/bin/env python3
"""Read only three prior canonical weekly report headers; never emit body text."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import date
from pathlib import Path

MAX_LINE_BYTES = 4096
MAX_HEADER_LINES = 64


def read_header(path: Path, directory: Path) -> dict:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            or path.resolve(strict=True).parent != directory):
        raise ValueError(f"noncanonical report path: {path.name}")
    title = ""
    fields = {}
    fence = ""
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError(f"report changed before header read: {path.name}")
        for _ in range(MAX_HEADER_LINES):
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"header line exceeds byte limit: {path.name}")
            line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
            if line.startswith("\ufeff"):
                raise ValueError(f"UTF-8 BOM is unsupported: {path.name}")
            if "<!--" in line or "-->" in line:
                raise ValueError(f"HTML comments are unsupported in header: {path.name}")
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fence:
                if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                    fence = ""
                continue
            if marker and (marker[1][0] != "`" or "`" not in marker[2]):
                fence = marker[1]
                continue
            if re.match(r"^ {0,3}##(?:[ \t]+|$)", line):
                if not title:
                    raise ValueError(f"missing report title: {path.name}")
                return {"filename": path.name, "title": title, **fields}
            heading = re.fullmatch(r" {0,3}#[ \t]+(.+?)[ \t]*", line)
            if heading:
                if title:
                    raise ValueError(f"duplicate report title: {path.name}")
                title = "# " + heading[1]
            field = re.fullmatch(r"(地区|报告时区)：(.*)", line)
            if field:
                if field[1] in fields:
                    raise ValueError(f"duplicate header field {field[1]}: {path.name}")
                fields[field[1]] = field[2].strip()
    raise ValueError(f"no H2 boundary within header limit: {path.name}")


def inspect_headers(directory: Path, before: date) -> dict:
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("archive directory must already exist")
    candidates = []
    for path in directory.iterdir():
        match = re.fullmatch(r"DHWB-(\d{4})(\d{2})(\d{2})\.md", path.name)
        if match:
            day = date(*(int(part) for part in match.groups()))
            if day < before:
                candidates.append(path)
    selected = sorted(candidates, key=lambda path: path.name, reverse=True)[:3]
    records = [read_header(path, directory) for path in selected]
    regions = {record.get("地区", "") for record in records}
    zones = {record.get("报告时区", "") for record in records}
    if not records:
        status = "no_history"
    elif len(regions - {""}) > 1 or len(zones - {""}) > 1:
        status = "conflict"
    elif len(records) != 3 or "" in regions or "" in zones:
        status = "insufficient"
    else:
        status = "stable"
    return {"schema_version": 1, "status": status, "before": before.isoformat(),
            "records": records, "limits": "header conventions only; not current facts or write authorization"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--before", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        result = inspect_headers(args.directory, args.before)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
