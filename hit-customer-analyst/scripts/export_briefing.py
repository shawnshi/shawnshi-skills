#!/usr/bin/env python3
"""Read-only export of the reviewed briefing section; never send or approve."""

from __future__ import annotations

import argparse
import html
import io
import sys
from pathlib import Path

import validate_outputs as validator
from runtime_tx import TxError, output_root_lock, workspace_lock


def export(workspace: Path, output_format: str = "markdown") -> str:
    with output_root_lock(workspace.parent), workspace_lock(workspace):
        issues, documents, _, _ = validator.validate(workspace, True, False)
        errors = [issue.code for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("速览尚不可交付：" + ", ".join(errors))
        total = next(
            doc
            for doc in documents
            if doc.frontmatter.get("artifact_type") == "comprehensive_report"
        )
        if total.frontmatter.get("business_mode") != "briefing":
            raise ValueError("只允许导出会前速览。")
        body = validator.briefing_body(total)
        lines = validator.briefing_lines(body)
        if output_format == "markdown":
            return body + "\n"
        if output_format != "html":
            raise ValueError("格式必须为markdown或html。")
        # Plain text, not executable Markdown/HTML; no scripts, fonts or remote resources.
        text = html.escape("\n".join(lines))
        return (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<title>会前速览（内部）</title><style>"
            "@page{size:A4;margin:15mm}*{box-sizing:border-box}"
            "body{margin:0;color:#1A232C;background:white}"
            "main{width:180mm;min-height:267mm;padding:0}"
            'pre{margin:0;white-space:pre;font:10pt/18px "Microsoft YaHei",monospace}'
            "@media screen{body{padding:15mm}}"
            "</style><main><pre>" + text + "</pre></main></html>\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导出已审核速览；stdout输出，不发送、不修改工作区。"
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--format", choices=("markdown", "html"), default="markdown")
    args = parser.parse_args()
    try:
        rendered = export(args.workspace.resolve(), args.format)
    except (OSError, UnicodeError, ValueError, RuntimeError, TxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
