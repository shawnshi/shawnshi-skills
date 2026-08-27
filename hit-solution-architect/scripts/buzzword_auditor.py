"""Report non-blocking style signals in a healthcare solution draft.

Fenced code, block quotes, and inline code are excluded because they are
usually source material or technical notation rather than authored prose.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "2.0"
EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 2
MAX_INPUT_BYTES = 10 * 1024 * 1024
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")

BUZZWORD_MAP = {
    "赋能": ["支撑", "说明具体能力"],
    "抓手": ["切入点", "治理工具"],
    "闭环": ["说明起点、终点和责任人"],
    "生态位": ["战略定位", "功能边界"],
    "打法": ["策略组合", "实施路径"],
    "颗粒度": ["精细度", "层级"],
    "底层逻辑": ["核心机制", "基本原理"],
    "拉通": ["说明需贯通的数据或流程"],
    "打通": ["说明需建设的接口或集成"],
    "沉淀": ["归档", "结构化存储"],
    "落地": ["实施", "部署", "交付"],
    "全链路": ["全流程", "端到端"],
    "降本增效": ["分别说明成本与效率指标"],
    "新质生产力": ["说明具体技术或业务能力"],
}

VAGUE_PATTERNS = (
    (
        r"(?:明显|显著|大幅|极大地?|有效地?)\s*(?:提升|提高|改善|优化|增强|降低|减少)",
        "补充测量口径，或明确标记为待测算。",
    ),
    (r"(?:一定程度上|在某种程度上)", "说明具体条件，或删除无法验证的限定词。"),
)


def prose_for_audit(content: str) -> str:
    """Remove Markdown regions that should not be style-audited."""

    retained: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in content.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None or line.lstrip().startswith(">"):
            continue
        retained.append(INLINE_CODE_RE.sub("", line))
    return "\n".join(retained)


def status_from_findings(
    errors: Sequence[dict[str, Any]],
    warnings: Sequence[dict[str, Any]],
    review: Sequence[dict[str, Any]],
) -> str:
    if errors:
        return "fail"
    if review:
        return "review_required"
    if warnings:
        return "warning"
    return "pass"


def audit(content: str, bold_hint: int, *, target_file: str = "<memory>") -> dict[str, Any]:
    if bold_hint < 0:
        raise ValueError("bold_hint must be non-negative")
    prose = prose_for_audit(content)
    warnings: list[dict[str, Any]] = []
    bold_matches = re.findall(r"\*\*[^*\n]+\*\*", prose)
    if len(bold_matches) > bold_hint:
        warnings.append(
            {
                "code": "W_BOLD_DENSITY",
                "message": f"可审计正文中有 {len(bold_matches)} 处加粗，可能影响阅读层级。",
                "instances": bold_matches[:10],
            }
        )

    for word, replacements in BUZZWORD_MAP.items():
        count = prose.count(word)
        if count:
            warnings.append(
                {
                    "code": "W_BUZZWORD",
                    "term": word,
                    "count": count,
                    "message": "该词可能过于抽象；请结合上下文人工判断。",
                    "alternatives": replacements,
                }
            )

    for pattern, suggestion in VAGUE_PATTERNS:
        matches = [match.group(0) for match in re.finditer(pattern, prose)]
        if matches:
            warnings.append(
                {
                    "code": "W_VAGUE_QUANTIFICATION",
                    "count": len(matches),
                    "instances": matches[:10],
                    "message": suggestion,
                }
            )

    errors: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "buzzword_auditor",
        "target_file": target_file,
        "status": status_from_findings(errors, warnings, review),
        "automated_checks": "pass",
        "errors": errors,
        "warnings": warnings,
        "review": review,
        "summary": {
            "error_count": 0,
            "warning_count": len(warnings),
            "review_count": 0,
            "bold_count": len(bold_matches),
            "bold_hint": bold_hint,
        },
    }


def runtime_failure_report(target_file: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "buzzword_auditor",
        "target_file": target_file,
        "status": "fail",
        "automated_checks": "not_run",
        "errors": [{"code": code, "message": message}],
        "warnings": [],
        "review": [],
        "summary": {"error_count": 1, "warning_count": 0, "review_count": 0},
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def read_utf8_document(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise OSError(f"输入文件超过 {MAX_INPUT_BYTES} 字节上限：{size}。")
    return path.read_text(encoding="utf-8-sig")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_md", type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    parser.add_argument(
        "--bold-hint",
        type=int,
        default=20,
        help="Non-negative soft threshold; it never makes style warnings blocking.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = str(args.file_md)
    if args.bold_hint < 0:
        report = runtime_failure_report(target, "E_ARGUMENT", "--bold-hint 必须大于或等于 0。")
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE
    if args.output and args.output.resolve(strict=False) == args.file_md.resolve(strict=False):
        report = runtime_failure_report(target, "E_ARGUMENT", "输出报告不能覆盖被检查的输入文档。")
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE

    try:
        content = read_utf8_document(args.file_md)
    except (OSError, UnicodeError) as exc:
        report = runtime_failure_report(target, "E_FILE_READ", str(exc))
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE

    report = audit(content, args.bold_hint, target_file=target)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_report(report) + "\n", encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            report = runtime_failure_report(target, "E_FILE_WRITE", str(exc))
            report["output_file"] = str(args.output)
            print(render_report(report))
            return EXIT_RUNTIME_FAILURE
    print(render_report(report))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
