#!/usr/bin/env python3
"""对 TXT/Markdown 稿件执行确定性轻量检查。

退出码：无阻断项为 0；存在阻断项或输入错误为 2。
脚本只发现可机械识别的风险，不替代事实、隐私或引用核验。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.I)
NUMBER_RE = re.compile(r"(?<![\d.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?![\d.])")
PLACEHOLDER_RE = re.compile(
    r"\{\{[^{}\n]{1,100}\}\}|\$\{[^{}\n]{1,100}\}|"
    r"(?<![A-Za-z0-9])(?:TODO|FIXME|TBD|TBC|PLACEHOLDER|XXX)(?![A-Za-z0-9])|"
    r"(?:\[|【|<)\s*(?:待(?:补充|补写|填写|完善|替换|插入)|此处(?:补充|填写|插入|替换)|占位符)[^\]】>\n]{0,50}(?:\]|】|>)|"
    r"待(?:补充|补写|填写|完善|替换|插入)|内容暂缺",
    re.I,
)
PENDING_RE = re.compile(
    r"待(?:核实|核验|确认|查证|求证)|尚待(?:核实|核验|确认)|"
    r"有待(?:核实|核验|确认)|未经(?:核实|核验|确认)|未核实|无法核实|"
    r"(?:来源|证据)待补|数据待确认"
)
AI_CLICHE_PATTERNS = {
    "时代背景套话": re.compile(r"在当今.{0,20}(?:时代|背景下)"),
    "发展背景套话": re.compile(r"随着.{0,40}?(?:不断|快速|日益).{0,20}?(?:发展|推进|演进|深入)"),
    "泛化共识": re.compile(r"众所周知|不难(?:看出|发现)"),
    "空泛强调": re.compile(r"值得(?:注意|关注|强调|一提)的是"),
    "空泛结论": re.compile(r"综上所述|总而言之"),
    "文章自述": re.compile(r"本文将(?:深入|全面|系统)?(?:探讨|分析|阐述|介绍)"),
    "宏大表达": re.compile(r"赋能千行百业|开启新篇章|迈向新高度|颠覆式变革|历史性机遇"),
}
OVER_CERTAINTY_PATTERNS = {
    "必然性断言": re.compile(r"(?:必然|必定|一定)(?:会|能够|导致|实现|带来|成为)|必将"),
    "无疑断言": re.compile(r"毫无疑问|毋庸置疑"),
    "绝对保证": re.compile(r"(?:百分之百|100\s*[%％])\s*(?:保证|确保|能够|实现|准确)"),
    "彻底消除": re.compile(r"(?:彻底|根本)(?:解决|消除|杜绝|避免)"),
    "零风险承诺": re.compile(r"零风险|无任何风险|万无一失"),
    "排他性领先": re.compile(r"(?:全球|全国|全行业|业内)\s*(?:唯一|首个|第一|最先进|绝对领先)"),
}


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是非负整数") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 TXT/Markdown 稿件的机械质量风险。")
    parser.add_argument("file", type=Path)
    parser.add_argument("--mode", choices=("light", "research", "publish"), default="light")
    parser.add_argument("--min-chars", type=non_negative_int)
    parser.add_argument("--max-chars", type=non_negative_int)
    parser.add_argument("--require-links", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    if args.min_chars is not None and args.max_chars is not None and args.min_chars > args.max_chars:
        parser.error("--min-chars 不能大于 --max-chars")
    return args


def mask_code(text: str) -> str:
    """遮蔽围栏和行内代码，保留行号。"""
    output: list[str] = []
    in_fence = False
    marker = ""
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        opening = re.match(r"([\x60~]{3,})", stripped)
        if opening:
            token = opening.group(1)
            if not in_fence:
                in_fence = True
                marker = token[0]
            elif token[0] == marker:
                in_fence = False
                marker = ""
            output.append("".join(ch if ch in "\r\n" else " " for ch in line))
            continue
        if in_fence:
            output.append("".join(ch if ch in "\r\n" else " " for ch in line))
            continue
        output.append(re.sub(r"\x60+[^\x60\n]*\x60+", lambda m: " " * len(m.group(0)), line))
    return "".join(output)


def examples_for(pattern: re.Pattern[str], text: str, limit: int = 5) -> tuple[int, list[dict[str, object]]]:
    count = 0
    examples: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for match in pattern.finditer(line):
            count += 1
            if len(examples) < limit:
                examples.append({
                    "line": line_number,
                    "match": match.group(0),
                    "excerpt": re.sub(r"\s+", " ", line.strip())[:140],
                })
    return count, examples


def add_pattern_finding(
    findings: list[dict[str, object]],
    code: str,
    severity: str,
    message: str,
    pattern: re.Pattern[str],
    text: str,
) -> None:
    count, examples = examples_for(pattern, text)
    if count:
        findings.append({
            "code": code,
            "severity": severity,
            "message": message,
            "count": count,
            "examples": examples,
        })


def split_paragraphs(text: str) -> list[tuple[int, str]]:
    paragraphs: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 1
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or re.match(r"^\s{0,3}#{1,6}\s+", line):
            if buffer:
                paragraphs.append((start, "\n".join(buffer).strip()))
                buffer = []
            continue
        if not buffer:
            start = line_number
        buffer.append(line)
    if buffer:
        paragraphs.append((start, "\n".join(buffer).strip()))
    return paragraphs


def normalize_paragraph(text: str) -> str:
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)、])\s+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~>#\s]", "", text)
    return text.casefold()


def duplicate_finding(paragraphs: list[tuple[int, str]]) -> dict[str, object] | None:
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line, paragraph in paragraphs:
        normalized = normalize_paragraph(paragraph)
        if len(normalized) >= 100:
            groups[normalized].append((line, paragraph))
    duplicates = [group for group in groups.values() if len(group) > 1]
    if not duplicates:
        return None
    duplicates.sort(key=lambda group: group[0][0])
    return {
        "code": "DUPLICATE_LONG_PARAGRAPH",
        "severity": "warning",
        "message": "发现重复长段落，请检查复制粘贴或跨章节重复。",
        "count": sum(len(group) - 1 for group in duplicates),
        "examples": [
            {"lines": [item[0] for item in group], "excerpt": group[0][1][:140]}
            for group in duplicates[:5]
        ],
    }


def analyze(path: Path, text: str, args: argparse.Namespace) -> dict[str, object]:
    masked = mask_code(text)
    paragraphs = split_paragraphs(masked)
    urls = URL_RE.findall(masked)
    content_chars = sum(not char.isspace() for char in text)
    findings: list[dict[str, object]] = []

    def blocker(code: str, message: str) -> None:
        findings.append({"code": code, "severity": "blocker", "message": message, "count": 1})

    if not text.strip():
        blocker("EMPTY_DOCUMENT", "文档为空。")
    if args.min_chars is not None and content_chars < args.min_chars:
        blocker("BELOW_MIN_CHARS", f"非空白字符数 {content_chars} 低于要求 {args.min_chars}。")
    if args.max_chars is not None and content_chars > args.max_chars:
        blocker("ABOVE_MAX_CHARS", f"非空白字符数 {content_chars} 高于要求 {args.max_chars}。")
    if args.require_links and not urls:
        blocker("REQUIRED_LINKS_MISSING", "已要求链接，但正文没有 HTTP(S) 链接。")

    add_pattern_finding(findings, "UNRESOLVED_PLACEHOLDER", "blocker", "正文仍有未解决占位符。", PLACEHOLDER_RE, masked)
    add_pattern_finding(
        findings,
        "PENDING_VERIFICATION",
        "blocker" if args.mode == "publish" else "warning",
        "正文仍有待核实或待确认内容。" + ("发布模式下属于阻断项。" if args.mode == "publish" else ""),
        PENDING_RE,
        masked,
    )
    for label, pattern in AI_CLICHE_PATTERNS.items():
        add_pattern_finding(findings, "AI_CLICHE", "warning", f"发现可能的 AI 套话：{label}。", pattern, masked)
    for label, pattern in OVER_CERTAINTY_PATTERNS.items():
        add_pattern_finding(findings, "OVER_CERTAINTY", "warning", f"发现过度确定性表达：{label}。", pattern, masked)
    duplicate = duplicate_finding(paragraphs)
    if duplicate:
        findings.append(duplicate)

    blockers = [item for item in findings if item["severity"] == "blocker"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    return {
        "tool": "text_qa",
        "version": "1.0.0",
        "file": str(path.resolve()),
        "mode": args.mode,
        "status": "blocked" if blockers else "pass",
        "exit_code": 2 if blockers else 0,
        "stats": {
            "characters": len(text),
            "content_characters": content_chars,
            "lines": len(text.splitlines()),
            "paragraphs": len(paragraphs),
            "headings": sum(bool(re.match(r"^\s{0,3}#{1,6}\s+", line)) for line in masked.splitlines()),
            "links": len(urls),
            "unique_links": len(set(urls)),
            "numbers": len(NUMBER_RE.findall(masked)),
        },
        "summary": {
            "blocker_categories": len(blockers),
            "warning_categories": len(warnings),
            "blocker_occurrences": sum(int(item["count"]) for item in blockers),
            "warning_occurrences": sum(int(item["count"]) for item in warnings),
        },
        "findings": findings,
    }


def fatal(path: Path, mode: str, code: str, message: str) -> dict[str, object]:
    return {
        "tool": "text_qa",
        "version": "1.0.0",
        "file": str(path),
        "mode": mode,
        "status": "blocked",
        "exit_code": 2,
        "stats": None,
        "summary": {"blocker_categories": 1, "warning_categories": 0, "blocker_occurrences": 1, "warning_occurrences": 0},
        "findings": [{"code": code, "severity": "blocker", "message": message, "count": 1}],
    }


def render_human(report: dict[str, object]) -> str:
    summary = report["summary"]
    assert isinstance(summary, dict)
    lines = [
        "text_qa 1.0.0",
        f"文件：{report['file']}",
        f"模式：{report['mode']}",
        f"状态：{'阻塞' if report['status'] == 'blocked' else ('通过（有警告）' if summary['warning_categories'] else '通过')}",
    ]
    stats = report.get("stats")
    if isinstance(stats, dict):
        lines.extend([
            "",
            f"统计：非空白字符 {stats['content_characters']}；行 {stats['lines']}；段落 {stats['paragraphs']}；标题 {stats['headings']}；链接 {stats['links']}；数字 {stats['numbers']}",
        ])
    findings = report["findings"]
    assert isinstance(findings, list)
    for severity, title in (("blocker", "阻断项"), ("warning", "警告")):
        items = [item for item in findings if item["severity"] == severity]
        if items:
            lines.extend(["", f"{title}："])
            for item in items:
                examples = item.get("examples", [])
                locations: list[int] = []
                if isinstance(examples, list):
                    for example in examples:
                        if isinstance(example, dict) and isinstance(example.get("line"), int):
                            locations.append(example["line"])
                suffix = f"（行 {', '.join(map(str, sorted(set(locations))))}）" if locations else ""
                lines.append(f"- {item['code']} ×{item['count']}：{item['message']}{suffix}")
    lines.extend(["", f"结果：退出码 {report['exit_code']}。"])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    path: Path = args.file
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        report = fatal(path, args.mode, "UNSUPPORTED_FILE_TYPE", "仅支持 .txt、.md 和 .markdown 文件。")
    elif not path.exists():
        report = fatal(path, args.mode, "FILE_NOT_FOUND", "文件不存在。")
    elif not path.is_file():
        report = fatal(path, args.mode, "NOT_A_FILE", "输入路径不是普通文件。")
    else:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            report = fatal(path, args.mode, "INVALID_ENCODING", "无法按 UTF-8 解码文件。")
        except OSError as exc:
            report = fatal(path, args.mode, "READ_ERROR", f"读取文件失败：{exc}")
        else:
            report = analyze(path, text, args)

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
