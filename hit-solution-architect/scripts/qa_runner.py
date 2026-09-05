"""Run logic and style checks in one pass over one Markdown input file."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from buzzword_auditor import audit as audit_style
from logic_checker import (
    DEFAULT_MAX_WARNINGS,
    EXIT_CONTENT_FAILURE,
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    MAX_WARNING_LIMIT,
    MODULE_RULES,
    PROFILES,
    SCHEMA_VERSION,
    STAGES,
    SolutionLogicChecker,
    parse_required_modules,
    read_utf8_document,
    render_report,
    runtime_failure_report,
    status_from_findings,
    write_report,
)


def _tag(findings: Sequence[dict[str, Any]], component: str) -> list[dict[str, Any]]:
    return [{"component": component, **finding} for finding in findings]


def build_report(
    content: str,
    *,
    target_file: str,
    profile: str,
    stage: str,
    required_modules: Sequence[str],
    allow_placeholders: bool,
    review_complete: bool,
    max_warnings: int,
    bold_hint: int,
) -> dict[str, Any]:
    logic_report = SolutionLogicChecker(
        content,
        target_file=target_file,
        profile=profile,
        stage=stage,
        required_modules=required_modules,
        allow_placeholders=allow_placeholders,
        review_complete=review_complete,
        max_warnings=max_warnings,
    ).run()
    style_report = audit_style(content, bold_hint, target_file=target_file)

    errors = _tag(logic_report["errors"], "logic") + _tag(
        style_report["errors"], "style"
    )
    combined_warnings = _tag(logic_report["warnings"], "logic") + _tag(
        style_report["warnings"], "style"
    )
    warnings = combined_warnings[:max_warnings]
    review = _tag(logic_report["review"], "logic") + _tag(
        style_report["review"], "style"
    )
    status = status_from_findings(errors, warnings, review)
    human_review = logic_report["gate"]["human_review"]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "qa_runner",
        "target_file": target_file,
        "profile": profile,
        "stage": stage,
        "status": status,
        "automated_checks": "fail" if errors else "pass",
        "gate": {
            "human_review": human_review,
            "release_ready": not errors and review_complete
            if stage == "release"
            else None,
        },
        "errors": errors,
        "warnings": warnings,
        "review": review,
        "structure": logic_report["structure"],
        "components": {
            "logic": {
                "status": logic_report["status"],
                "summary": logic_report["summary"],
            },
            "style": {
                "status": style_report["status"],
                "summary": style_report["summary"],
            },
        },
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "warning_truncated_count": max(len(combined_warnings) - len(warnings), 0)
            + logic_report["summary"].get("warning_truncated_count", 0),
            "review_count": len(review),
            "section_count": logic_report["summary"]["section_count"],
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", type=Path)
    parser.add_argument(
        "--profile", default="proposal", metavar="{" + ",".join(PROFILES) + "}"
    )
    parser.add_argument(
        "--stage", default="review", metavar="{" + ",".join(STAGES) + "}"
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="MODULE[,MODULE]",
        help=f"Require one or more modules: {', '.join(MODULE_RULES)}.",
    )
    parser.add_argument("--allow-placeholders", action="store_true")
    parser.add_argument("--review-complete", action="store_true")
    parser.add_argument(
        "--require-release-ready",
        action="store_true",
        help="Require stage release and gate.release_ready=true for exit 0; does not perform human review.",
    )
    parser.add_argument("--bold-hint", type=int, default=20)
    parser.add_argument("--max-warnings", type=int, default=DEFAULT_MAX_WARNINGS)
    parser.add_argument(
        "--output", type=Path, help="Optional combined JSON report path."
    )
    return parser.parse_args(argv)


def _argument_failure(target: str, message: str) -> int:
    print(
        render_report(
            runtime_failure_report("qa_runner", target, "E_ARGUMENT", message)
        )
    )
    return EXIT_RUNTIME_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = str(args.file_path)
    if args.profile not in PROFILES:
        return _argument_failure(target, f"未知 profile：{args.profile}。")
    if args.stage not in STAGES:
        return _argument_failure(target, f"未知 stage：{args.stage}。")
    required_modules = parse_required_modules(args.require)
    unknown_modules = sorted(set(required_modules) - set(MODULE_RULES))
    if unknown_modules:
        return _argument_failure(
            target, f"未知 --require 模块：{', '.join(unknown_modules)}。"
        )
    if args.bold_hint < 0:
        return _argument_failure(target, "--bold-hint 必须大于或等于 0。")
    if not 0 <= args.max_warnings <= MAX_WARNING_LIMIT:
        return _argument_failure(
            target, f"--max-warnings 必须在 0 到 {MAX_WARNING_LIMIT} 之间。"
        )
    if args.stage == "release" and args.allow_placeholders:
        return _argument_failure(target, "release 阶段不能使用 --allow-placeholders。")
    if args.require_release_ready and args.stage != "release":
        return _argument_failure(
            target, "--require-release-ready 只适用于 release 阶段。"
        )
    if args.review_complete and args.stage != "release":
        return _argument_failure(target, "--review-complete 只适用于 release 阶段。")
    if args.output and args.output.resolve(strict=False) == args.file_path.resolve(
        strict=False
    ):
        return _argument_failure(target, "输出报告不能覆盖被检查的输入文档。")

    try:
        # This is the only read of the source document. Both checkers receive
        # the same immutable string so the combined report is internally consistent.
        content = read_utf8_document(args.file_path)
    except (OSError, UnicodeError) as exc:
        report = runtime_failure_report("qa_runner", target, "E_FILE_READ", str(exc))
        print(render_report(report))
        return EXIT_RUNTIME_FAILURE

    report = build_report(
        content,
        target_file=target,
        profile=args.profile,
        stage=args.stage,
        required_modules=required_modules,
        allow_placeholders=args.allow_placeholders,
        review_complete=args.review_complete,
        max_warnings=args.max_warnings,
        bold_hint=args.bold_hint,
    )
    if args.output:
        try:
            write_report(report, args.output)
        except (OSError, UnicodeError) as exc:
            report = runtime_failure_report(
                "qa_runner", target, "E_FILE_WRITE", str(exc)
            )
            report["output_file"] = str(args.output)
            print(render_report(report))
            return EXIT_RUNTIME_FAILURE
    print(render_report(report))
    if args.require_release_ready and report["gate"]["release_ready"] is not True:
        return EXIT_CONTENT_FAILURE
    return EXIT_CONTENT_FAILURE if report["errors"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
