"""Synthetic unittest fixtures only; no network, archive calls or production writes."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any

from validate_industry_radar import (
    BLOCKED_EMPTY,
    COVERAGE_HEADER,
    EMPTY,
    EVENT_HEADER,
    PARTIAL_EMPTY,
    SOURCE_HEADER,
    canonical_title,
    metadata,
    original_link,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-09-11T00:00:00+08:00")


def table(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join(
        "| " + " | ".join(row) + " |" for row in [header, ["---"] * len(header), *rows]
    )


def fixture(
    start="2026-09-04",
    end="2026-09-10",
    cutoff="2026-09-10T09:00:00+08:00",
    mode="rolling7",
    status="complete",
    events=True,
    zone="Asia/Shanghai",
):
    # Tests deliberately mutate typed API arguments, including invalid values.
    args: dict[str, Any] = {
        "period_start": date.fromisoformat(start),
        "period_end": date.fromisoformat(end),
        "issue_date": date.fromisoformat(end),
        "cutoff": datetime.fromisoformat(cutoff),
        "window_mode": mode,
        "report_timezone": zone,
        "now": NOW,
    }
    rows = (
        [
            [
                "E1",
                end,
                end,
                "合成医院",
                "公布采购结果",
                "合成医院/A/包1/中标",
                "E1",
                "S1",
                "可能签约",
                "合同未披露",
            ]
        ]
        if events
        else []
    )
    source_rows = (
        [["S1", "https://example.org/award", "L1", "primary", "accessed"]]
        if events
        else []
    )
    marker = (
        ""
        if events
        else "\n"
        + {"complete": EMPTY, "partial": PARTIAL_EMPTY, "blocked": BLOCKED_EMPTY}[
            status
        ]
    )
    content = f"""{canonical_title(args["period_start"], args["period_end"])}
报告周期：{start} 至 {end}
出刊日期：{end}
生成时点：{cutoff}
报告时区：{zone}
窗口模式：{mode}
报告范围：中国医疗 IT；合成采购
检索状态：{status}
截至生成时点，当天尚未结束。

## 结论摘要
合成夹具，非真实新闻。

## 关键事件
{table(EVENT_HEADER, rows)}{marker}

## 检索覆盖
{table(COVERAGE_HEADER, [["采购", status, "合成查询：采购公告；按窗口筛选；失败或缺口按状态记录"]])}

## 来源
{table(SOURCE_HEADER, source_rows)}

## 信息缺口
合成夹具不证明合同或交付。
"""
    return content, args


class ValidateIndustryRadarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radar-validator-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content, self.args = fixture()

    def check(self, content=None, args=None, name=None):
        args = self.args if args is None else args
        content = self.content if content is None else content
        file = self.root / (name or f"DHWB-Radar-{args['issue_date']:%Y%m%d}.md")
        file.write_bytes(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )
        before = hashlib.sha256(file.read_bytes()).hexdigest()
        errors = validate_report(file, **args)
        self.assertEqual(before, hashlib.sha256(file.read_bytes()).hexdigest())
        self.assertEqual([file], list(self.root.iterdir()))
        file.unlink()
        return errors

    def reject(self, content=None, args=None, contains=None, name=None):
        errors = self.check(content, args, name)
        self.assertTrue(errors)
        if contains:
            self.assertTrue(any(contains in error for error in errors), errors)

    def test_valid_default_includes_today(self):
        self.assertEqual([], self.check())
        self.assertEqual(
            [],
            self.check(
                self.content.replace(
                    "| 2026-09-10 | 2026-09-10 |", "| 2026-09-04 | 2026-09-10 |"
                )
            ),
        )

    def test_leap_cross_month_and_cross_year_windows(self):
        for start, end in [("2024-02-24", "2024-03-01"), ("2025-12-29", "2026-01-04")]:
            with self.subTest(start=start):
                content, args = fixture(start, end, end + "T09:00:00+08:00")
                self.assertEqual([], self.check(content, args))

    def test_natural_week_and_monday_single_day(self):
        for start, end in [("2026-09-07", "2026-09-10"), ("2026-09-07", "2026-09-07")]:
            content, args = fixture(
                start, end, end + "T09:00:00+08:00", mode="natural_week"
            )
            self.assertEqual([], self.check(content, args))

    def test_explicit_historical_window(self):
        content, args = fixture("2026-08-01", "2026-08-31", mode="explicit")
        self.assertEqual([], self.check(content, args))

    def test_wrong_window_mode_boundaries(self):
        for mode in ("rolling7", "natural_week", "unknown"):
            content, args = fixture("2026-09-05", mode=mode)
            self.reject(content, args)

    def test_future_and_inverted_periods(self):
        for start, end in [("2026-09-11", "2026-09-10"), ("2026-09-04", "2026-09-12")]:
            content, args = fixture(start, end, mode="explicit")
            self.reject(content, args, "period")

    def test_aware_cutoff_now_and_future(self):
        for change in (
            {"cutoff": datetime(2026, 9, 10, 9)},
            {"now": datetime(2026, 9, 11)},
            {"now": datetime.fromisoformat("2026-09-10T08:59:00+08:00")},
        ):
            self.reject(args={**self.args, **change})

    def test_timezone_conversion_not_timestamp_date(self):
        content, args = fixture(cutoff="2026-09-09T17:00:00Z")
        self.assertEqual([], self.check(content, args))
        self.reject(
            args={**self.args, "report_timezone": "Not/AZone"}, contains="timezone"
        )

    def test_event_date_invalid_unknown_outside(self):
        for day in (
            "2026-02-30",
            "2026-09-03",
            "2026-09-11",
            "未知",
            "20260910",
            "2026-9-10",
        ):
            with self.subTest(day=day):
                self.reject(
                    self.content.replace(
                        "| 2026-09-10 | 2026-09-10 |", f"| {day} | 2026-09-10 |"
                    )
                )

    def test_publication_can_precede_event_or_be_unknown(self):
        for published in ("2026-08-01", "未知"):
            self.assertEqual(
                [],
                self.check(
                    self.content.replace(
                        "| 2026-09-10 | 2026-09-10 |", f"| 2026-09-10 | {published} |"
                    )
                ),
            )

    def test_publication_invalid_or_future(self):
        for published in ("2026-09-11", "2026-02-30", "20260910"):
            self.reject(
                self.content.replace(
                    "| 2026-09-10 | 2026-09-10 |", f"| 2026-09-10 | {published} |"
                )
            )

    def test_unknown_event_lead_outside_event_table(self):
        content, args = fixture(events=False)
        content += (
            "\n## 背景与待核线索\n事件日未知，旧政策未来生效，未计本期；待核原文。\n"
        )
        self.assertEqual([], self.check(content, args))

    def test_strict_utf8_bom_replacement_and_empty(self):
        for data in (
            b"\xff",
            b"",
            ("\ufeff" + self.content).encode(),
            (self.content + "\ufffd").encode(),
        ):
            self.reject(data)

    def test_missing_file_returns_io_error(self):
        errors = validate_report(self.root / "missing.md", **self.args)
        self.assertTrue(any("source IO" in e for e in errors))
        self.assertEqual([], list(self.root.iterdir()))

    def test_header_uniqueness_missing_mismatch(self):
        for line in self.content.splitlines()[1:8]:
            with self.subTest(line=line):
                self.reject(self.content.replace(line + "\n", "", 1))
                self.reject(self.content.replace(line, line + "\n" + line, 1))
        self.reject(self.content.replace("窗口模式：rolling7", "窗口模式：explicit"))
        self.reject(
            self.content.replace(
                "生成时点：2026-09-10T09:00:00+08:00",
                "生成时点：2026-09-10T09:01:00+08:00",
            )
        )
        self.reject(self.content.replace("报告时区：Asia/Shanghai", "报告时区：UTC"))
        self.reject(self.content.replace("检索状态：complete", "检索状态：success"))

    def test_required_metadata_rejects_blank_values(self):
        for line in self.content.splitlines()[1:8]:
            label = line.split("：", 1)[0]
            for blank in ("", "   ", "\t\t", "\u3000\u3000"):
                for newline in ("\n", "\r\n"):
                    with self.subTest(
                        label=label, blank=repr(blank), newline=repr(newline)
                    ):
                        content = self.content.replace(
                            line, label + "：" + blank, 1
                        ).replace("\n", newline)
                        with self.assertRaisesRegex(
                            ValueError, label + " must not be blank"
                        ):
                            metadata(content, label)
                        self.reject(content, contains="invalid metadata")

    def test_required_metadata_rejects_empty_duplicates_before_and_after(self):
        for line in self.content.splitlines()[1:8]:
            label = line.split("：", 1)[0]
            for blank in ("", " \t\u3000"):
                duplicate = label + "：" + blank
                for first in (True, False):
                    replacement = (
                        duplicate + "\n" + line if first else line + "\n" + duplicate
                    )
                    for newline in ("\n", "\r\n"):
                        with self.subTest(
                            label=label,
                            blank=repr(blank),
                            first=first,
                            newline=repr(newline),
                        ):
                            content = self.content.replace(
                                line, replacement, 1
                            ).replace("\n", newline)
                            with self.assertRaisesRegex(
                                ValueError, label + " must occur exactly once"
                            ):
                                metadata(content, label)
                            self.reject(
                                content, contains=label + " must occur exactly once"
                            )

    def test_required_metadata_accepts_unique_values_with_crlf(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                content = self.content.replace("\n", newline)
                for line in self.content.splitlines()[1:8]:
                    label, value = line.split("：", 1)
                    self.assertEqual(value, metadata(content, label))
                self.assertEqual([], self.check(content))

    def test_required_metadata_strips_surrounding_whitespace(self):
        content = self.content
        for line in self.content.splitlines()[1:8]:
            label, value = line.split("：", 1)
            content = content.replace(
                line, label + "： \t\u3000" + value + "\u3000\t ", 1
            )
        self.assertEqual([], self.check(content))

    def test_body_metadata_does_not_replace_header(self):
        line = "报告范围：中国医疗 IT；合成采购\n"
        self.reject(self.content.replace(line, "") + line)

    def test_filename_issue_title_and_custom_filename(self):
        self.reject(name="DHWB-Radar-20260909.md", contains="filename")
        self.assertEqual(
            [],
            self.check(
                args={**self.args, "allow_custom_filename": True}, name="custom.md"
            ),
        )
        self.reject(
            args={**self.args, "issue_date": date(2026, 9, 9)}, contains="issue date"
        )
        self.reject(
            self.content.replace("# 医疗行业雷达", "# 数字健康周报", 1),
            contains="title",
        )

    def test_placeholders_but_not_legitimate_intervals(self):
        self.reject(self.content + "[PERIOD_START]", contains="placeholder")
        self.assertEqual(
            [], self.check(self.content + "\n分析区间 [0,1]，未披露金额不估算。")
        )

    def test_url_syntax(self):
        for url in ("https://example.org/x?a=b", "http://example.org/x"):
            self.assertTrue(original_link(url))
        for url in (
            "file:///x",
            "javascript:alert(1)",
            "https://",
            "https://a:99999/x",
            "https://a:no/x",
            "https://user:pass@example.org/x",
            "https://example.org/ 注释",
            "[x](https://example.org)",
            "https://[broken",
            "https://example.org/\n",
            "https://example.org/\\x",
        ):
            with self.subTest(url=url):
                self.assertFalse(original_link(url))
                self.reject(self.content.replace("https://example.org/award", url))

    def test_duplicate_event_ids_and_keys(self):
        row = next(
            line for line in self.content.splitlines() if line.startswith("| E1 |")
        )
        duplicate_id = row.replace("/包1/", "/包2/").replace("公布采购结果", "公布合同")
        self.reject(
            self.content.replace(row, row + "\n" + duplicate_id),
            contains="duplicate event ID",
        )
        for duplicate in (
            row.replace("| E1 |", "| E2 |", 1),
            row.replace("| E1 |", "| E2 |", 1)
            .replace("公布采购结果", "结果公布")
            .replace("合成医院/A/包1/中标", " 合成医院/ a /包1/中标 "),
        ):
            self.reject(
                self.content.replace(row, row + "\n" + duplicate),
                contains="duplicate event key",
            )

    def test_distinct_procurement_projects_and_lots_same_action_allowed(self):
        row = next(
            line for line in self.content.splitlines() if line.startswith("| E1 |")
        )
        for key in ("合成医院/A/包2/中标", "合成医院/B/包1/中标"):
            with self.subTest(key=key):
                extra = row.replace("| E1 |", "| E2 |", 1).replace(
                    "合成医院/A/包1/中标", key
                )
                self.assertEqual(
                    [], self.check(self.content.replace(row, row + "\n" + extra))
                )

    def test_distinct_procurement_stage_allowed(self):
        row = next(
            line for line in self.content.splitlines() if line.startswith("| E1 |")
        )
        contract = (
            row.replace("| E1 |", "| E2 |", 1)
            .replace("公布采购结果", "公布合同")
            .replace("/中标", "/合同")
        )
        self.assertEqual(
            [], self.check(self.content.replace(row, row + "\n" + contract))
        )

    def test_source_references_and_duplicate_sources(self):
        self.reject(
            self.content.replace("| E1 | S1 |", "| E1 | S9 |"),
            contains="unknown source",
        )
        self.reject(
            self.content.replace("| E1 | S1 |", "| E1 | S1,S1 |"),
            contains="duplicate source references",
        )
        row = "| S1 | https://example.org/award | L1 | primary | accessed |"
        self.reject(
            self.content.replace(row, row + "\n" + row), contains="duplicate source"
        )
        self.reject(
            self.content.replace(
                row,
                row + "\n" + row.replace("S1", "S2").replace("/award", "/award#copy"),
            ),
            contains="duplicate source URL",
        )
        self.reject(self.content + "\n[S9] [E9]", contains="unknown narrative")

    def test_source_url_case_and_fragment_duplicates_rejected(self):
        row = "| S1 | https://example.org/award | L1 | primary | accessed |"
        strong = self.content.replace("| E1 | S1 |", "| E2 | S1,S2 |")
        for url in (
            "https://EXAMPLE.ORG/award",
            "HTTPS://example.org/award",
            "HTTPS://EXAMPLE.ORG/award#copy",
        ):
            with self.subTest(url=url):
                extra = f"| S2 | {url} | L2 | primary | accessed |"
                self.reject(
                    strong.replace(row, row + "\n" + extra),
                    contains="duplicate source URL",
                )

    def test_source_url_path_query_and_port_distinctions_preserved(self):
        row = "| S1 | https://example.org/award | L1 | primary | accessed |"
        for first, second in (
            ("/award?id=A/", "/award?id=A"),
            ("/award/", "/award"),
            ("/Award", "/award"),
            ("/award?id=A", "/award?id=a"),
            ("/award?id=A", "/award?id=B"),
            (":8443/award", "/award"),
        ):
            with self.subTest(first=first, second=second):
                sources = (
                    f"| S1 | https://example.org{first} | L1 | primary | accessed |\n"
                    f"| S2 | https://example.org{second} | L2 | primary | accessed |"
                )
                self.assertEqual([], self.check(self.content.replace(row, sources)))

    def test_legal_bracketed_ipv6_sources_allowed(self):
        for url in ("https://[2001:db8::1]/notice", "http://[::1]:8080/notice"):
            with self.subTest(url=url):
                self.assertTrue(original_link(url))
                self.assertEqual(
                    [],
                    self.check(self.content.replace("https://example.org/award", url)),
                )

    def test_malformed_bracketed_hosts_and_markdown_rejected(self):
        for url in (
            "https://[not-ipv6]/notice",
            "https://[2001:db8::1/notice",
            "https://[2001:db8::1]extra/notice",
            "https://[::1]:bad/notice",
            "[notice](https://[2001:db8::1]/notice)",
            "https://example.org/[notice]",
        ):
            with self.subTest(url=url):
                self.assertFalse(original_link(url))
                self.reject(
                    self.content.replace("https://example.org/award", url),
                    contains="invalid original",
                )

    def test_evidence_lineage_constraints(self):
        strong = self.content.replace("| E1 | S1 |", "| E2 | S1,S2 |")
        row = "| S1 | https://example.org/award | L1 | primary | accessed |"
        for lineage, kind, access, valid in [
            ("L1", "secondary", "accessed", False),
            ("L2", "secondary", "unavailable", False),
            ("L2", "unverified", "accessed", False),
            ("L2", "secondary", "accessed", True),
        ]:
            extra = (
                f"| S2 | https://example.net/report | {lineage} | {kind} | {access} |"
            )
            errors = self.check(strong.replace(row, row + "\n" + extra))
            self.assertEqual(valid, not errors, errors)
        self.reject(
            self.content.replace("primary | accessed", "primary | unavailable"),
            contains="direct source",
        )
        self.reject(
            self.content.replace("primary | accessed", "secondary | accessed"),
            contains="direct source",
        )
        self.reject(
            self.content.replace("| E1 | S1 |", "| lead | S1 |"), contains="evidence"
        )
        self.assertEqual(
            [],
            self.check(
                self.content.replace("primary | accessed", "marketing | accessed")
            ),
        )
        all_marketing = strong.replace(
            row,
            row + "\n| S2 | https://example.net/report | L2 | marketing | accessed |",
        )
        self.reject(
            all_marketing.replace("primary | accessed", "marketing | accessed"),
            contains="E2 needs",
        )

    def test_successful_empty_partial_and_blocked_distinct(self):
        for status in ("complete", "partial", "blocked"):
            with self.subTest(status=status):
                content, args = fixture(status=status, events=False)
                self.assertEqual([], self.check(content, args))
                for marker in (EMPTY, PARTIAL_EMPTY, BLOCKED_EMPTY):
                    expected = {
                        "complete": EMPTY,
                        "partial": PARTIAL_EMPTY,
                        "blocked": BLOCKED_EMPTY,
                    }[status]
                    if marker != expected:
                        self.reject(content.replace(expected, marker), args, "marker")
                self.reject(content.replace(expected, ""), args, "marker")

    def test_empty_marker_cannot_coexist_with_events_or_repeat(self):
        self.reject(
            self.content.replace("## 关键事件", "## 关键事件\n" + EMPTY),
            contains="marker",
        )
        content, args = fixture(events=False)
        self.reject(content.replace(EMPTY, EMPTY + "\n" + EMPTY), args, "marker")

    def test_coverage_status_consistency(self):
        self.reject(
            self.content.replace("| 采购 | complete |", "| 采购 | blocked |"),
            contains="coverage",
        )
        self.reject(
            self.content.replace("检索状态：complete", "检索状态：partial"),
            contains="partial requires",
        )
        self.reject(
            self.content.replace("检索状态：complete", "检索状态：blocked"),
            contains="blocked",
        )
        content, args = fixture(status="partial")
        self.assertEqual([], self.check(content, args))
        self.reject(
            content.replace("| 采购 | partial |", "| 采购 | blocked |"),
            args,
            "partial requires",
        )

    def test_required_sections_tables_cells_and_coverage(self):
        for title in ("关键事件", "来源", "检索覆盖", "结论摘要", "信息缺口"):
            self.reject(self.content.replace("## " + title, "## " + title + "改名"))
            self.reject(self.content + "\n## " + title + "\n重复")
        self.reject(
            self.content.replace("| 可能签约 |", "| |"), contains="empty table cell"
        )
        self.reject(self.content.replace("| 事件ID |", "| ID |"), contains="header")
        self.reject(
            self.content.replace("## 关键事件", "## 关键事件\n绕过日期的自由事件"),
            contains="table rows",
        )
        row = next(
            line for line in self.content.splitlines() if line.startswith("| 采购 |")
        )
        self.reject(self.content.replace(row, ""), contains="coverage evidence")

    def test_rw001_hidden_and_code_structure_rejected(self):
        variants = {
            "comment_body": self.content.replace("## 结论摘要", "<!--\n## 结论摘要")
            + "\n-->",
            "comment_metadata": self.content.replace(
                "报告范围：中国医疗 IT；合成采购",
                "<!--\n报告范围：中国医疗 IT；合成采购\n-->",
            ),
            "indented_tables": "\n".join(
                "    " + line if line.startswith("|") else line
                for line in self.content.splitlines()
            ),
            "tab_tables": "\n".join(
                "\t" + line if line.startswith("|") else line
                for line in self.content.splitlines()
            ),
            "fenced_body": self.content.replace(
                "## 结论摘要", "```markdown\n## 结论摘要"
            )
            + "\n```",
            "fenced_metadata": self.content.replace(
                "报告范围：中国医疗 IT；合成采购",
                "~~~text\n报告范围：中国医疗 IT；合成采购\n~~~",
            ),
            "indented_metadata": self.content.replace("报告范围：", "    报告范围："),
            "multiline_inline_code": self.content.replace(
                "报告范围：中国医疗 IT；合成采购",
                "`\n报告范围：中国医疗 IT；合成采购\n`",
            ),
            "html_body": self.content.replace(
                "## 结论摘要", "<div hidden>\n## 结论摘要"
            )
            + "\n</div>",
            "multiline_script": self.content.replace(
                "## 结论摘要\n", "## 结论摘要\n<script\nhidden>\n"
            ),
            "multiline_style": self.content.replace(
                "## 结论摘要\n", "## 结论摘要\n<style\nhidden>\n"
            ),
            "multiline_tag": self.content.replace(
                "## 结论摘要\n", "## 结论摘要\n<div\nclass=\"x\">\n"
            ),
            "quoted_metadata": self.content.replace(
                "报告周期：", "> quoted header\n报告周期："
            ),
        }
        for name, content in variants.items():
            with self.subTest(variant=name):
                self.reject(content)

    def test_rw001_inline_code_escape_parity(self):
        line = "报告范围：中国医疗 IT；合成采购"
        for slashes in (2, 4):
            delimiter = chr(92) * slashes + "`"
            self.reject(
                self.content.replace(line, delimiter + "\n" + line + "\n" + delimiter),
                contains="inline code",
            )
        self.assertEqual([], self.check(self.content + "\n转义字符 " + chr(92) + "`"))
        self.assertEqual(
            [], self.check(self.content + "\n代码 `literal " + chr(92) + "`")
        )

    def test_rw001_each_table_requires_adjacent_separator(self):
        for header in (EVENT_HEADER, SOURCE_HEADER, COVERAGE_HEADER):
            head, separator = table(header, []).splitlines()
            for replacement in (
                head,
                head + "\n\n" + separator,
                head + "\n    " + separator,
                head + "\n" + separator.replace("---", "--", 1),
                separator,
                head + "\n" + separator + "\n" + separator,
            ):
                with self.subTest(header=header[0], replacement=replacement):
                    self.reject(
                        self.content.replace(head + "\n" + separator, replacement)
                    )
        self.reject(
            "\n".join(
                line
                for line in self.content.splitlines()
                if not line.startswith("| ---")
            )
        )

    def test_rw001_table_rows_cannot_restart_after_blank_or_code(self):
        row = next(
            line for line in self.content.splitlines() if line.startswith("| E1 |")
        )
        for gap in ("\n", "```text\nbackground\n```\n", "    background\n"):
            with self.subTest(gap=gap):
                self.reject(self.content.replace(row, gap + row))

    def test_rw001_code_cannot_supply_required_prose(self):
        for text in ("合成夹具，非真实新闻。", "合成夹具不证明合同或交付。"):
            for replacement in ("    " + text, "~~~\n" + text + "\n~~~"):
                with self.subTest(text=text, replacement=replacement):
                    self.reject(self.content.replace(text, replacement))

    def test_rw001_supported_visible_markdown(self):
        for newline in ("\n", "\r\n"):
            for indent in ("", " ", "   "):
                content = "\n".join(
                    indent + line if line.startswith(("## ", "|")) else line
                    for line in self.content.splitlines()
                )
                self.assertEqual([], self.check(content.replace("\n", newline)))
        for fence, closing in (
            ("```python", "```"),
            ("~~~~text", "~~~~~"),
            ("````", "````"),
        ):
            inner = "```" if fence == "````" else "code background"
            background = (
                "\n## 背景与待核线索\n可见背景与 `单行代码`。\n"
                + fence
                + "\n## 关键事件\n报告范围：fake\n| fake |\n"
                + inner
                + "\n"
                + closing
                + "\n"
            )
            # A shorter fence inside a longer one must not end the block.
            self.assertEqual([], self.check(self.content + background))
        self.assertEqual(
            [],
            self.check(
                self.content
                + "\n## 背景与待核线索\n可见背景。\n\n    ## 关键事件\n    报告范围：fake\n"
            ),
        )
        self.assertEqual(
            [],
            self.check(
                self.content.replace(
                    "合成夹具，非真实新闻。", "说明 `<div>` 与 `<span class=\"x\">` 且 p < 0.05 a < b。"
                )
            ),
        )

    def test_rw001_shared_identity_source_gate_not_legacy_body_migration(self):
        import importlib.util

        script = ROOT.parent / "shared/scripts/report_archive.py"
        spec = importlib.util.spec_from_file_location("radar_archive_test", script)
        assert spec is not None and spec.loader is not None
        archive = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(archive)
        path = self.root / "DHWB-Radar-20260910.md"
        options = {
            "skill": "hit-industry-radar",
            "custom_filename": False,
            "custom_period": False,
            "target_name": path.name,
        }
        path.write_text(self.content, encoding="utf-8")
        expected = archive.identity(path, validate=True, **options)
        variants = [
            self.content.replace("## 结论摘要", "<!--\n## 结论摘要") + "\n-->",
            "\n".join(
                "    " + line if line.startswith("|") else line
                for line in self.content.splitlines()
            ),
            "\n".join(
                line
                for line in self.content.splitlines()
                if not line.startswith("| ---")
            ),
        ]
        for content in variants:
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(archive.Blocked) as caught:
                    archive.identity(path, validate=True, **options)
                self.assertEqual("INPUT", caught.exception.code)
                self.assertEqual(
                    expected, archive.identity(path, validate=False, **options)
                )
                self.assertEqual(before, path.read_bytes())

    @unittest.skipUnless(sys.platform == "win32", "Windows ACL readback only")
    def test_rw001_windows_archive_rejection_preserves_bytes_and_acl(self):
        import importlib.util

        script = ROOT.parent / "shared/scripts/report_archive.py"
        spec = importlib.util.spec_from_file_location("radar_archive_acl_test", script)
        assert spec is not None and spec.loader is not None
        archive = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(archive)
        # The installed backend is read only here; no commit or ACL setter calls.
        sys.path.insert(0, str(script.parent))
        try:
            security = archive.backend()
        finally:
            sys.path.pop(0)
        source = self.root / "draft.md"
        target = self.root / "DHWB-Radar-20260910.md"
        target.write_text(self.content, encoding="utf-8")
        variants = [
            self.content.replace("## 结论摘要", "<!--\n## 结论摘要") + "\n-->",
            "\n".join(
                "    " + line if line.startswith("|") else line
                for line in self.content.splitlines()
            ),
            "\n".join(
                line
                for line in self.content.splitlines()
                if not line.startswith("| ---")
            ),
        ]
        for content in variants:
            with self.subTest(content=content):
                source.write_text(content, encoding="utf-8")
                before = [
                    (p.read_bytes(), security.descriptor(p)) for p in (source, target)
                ]
                parent_acl = security.descriptor(self.root)
                with self.assertRaises(archive.Blocked) as caught:
                    archive.validate(source, target, target, "hit-industry-radar")
                self.assertEqual("INPUT", caught.exception.code)
                self.assertEqual(
                    before,
                    [
                        (p.read_bytes(), security.descriptor(p))
                        for p in (source, target)
                    ],
                )
                self.assertEqual(parent_acl, security.descriptor(self.root))
                self.assertEqual({source, target}, set(self.root.iterdir()))

    def test_documented_synthetic_example_matches_validator(self):
        schema = (ROOT / "references/report_schema.md").read_text(encoding="utf-8")
        sample = schema.split("```markdown\n", 1)[1].split("```", 1)[0]
        self.assertEqual([], self.check(sample))

    def test_assets_and_manual_eval_contracts(self):
        targets = json.loads(
            (ROOT / "assets/intelligence_targets.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {"global_hit", "china_hit", "winning_baseline"}, set(targets["targets"])
        )
        for urls in targets["targets"].values():
            self.assertTrue(all(original_link(url) for url in urls))
        for filename, case_key in (
            ("benchmark.json", "test_cases"),
            ("evals.json", "evals"),
        ):
            data = json.loads((ROOT / "evals" / filename).read_text(encoding="utf-8"))
            ids = [case["id"] for case in data[case_key]]
            self.assertEqual(len(ids), len(set(ids)))
            for case in data[case_key]:
                self.assertNotIn("expected_output_patterns", case)
                self.assertNotIn("banned_output_patterns", case)
                self.assertTrue(case.get("assertions", case.get("expectations")))

    def test_cli_positive_negative_and_no_writes(self):
        content, args = fixture("2024-02-24", "2024-03-01", "2024-03-01T09:00:00+08:00")
        file = self.root / "DHWB-Radar-20240301.md"
        file.write_text(content, encoding="utf-8")
        cmd = [
            sys.executable,
            "-B",
            str(ROOT / "scripts/validate_industry_radar.py"),
            "--file",
            str(file),
            "--period-start",
            str(args["period_start"]),
            "--period-end",
            str(args["period_end"]),
            "--issue-date",
            str(args["issue_date"]),
            "--cutoff",
            args["cutoff"].isoformat(),
        ]
        for expected, data in [
            (0, content),
            (
                1,
                content.replace(
                    "| 2024-03-01 | 2024-03-01 |", "| 2024-03-02 | 2024-03-01 |"
                ),
            ),
        ]:
            file.write_text(data, encoding="utf-8")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
            self.assertIn("OK:" if expected == 0 else "FAIL:", result.stdout)
            self.assertEqual(data, file.read_text(encoding="utf-8"))
            self.assertEqual([file], list(self.root.iterdir()))
        bad = copy.copy(cmd)
        bad[bad.index("--period-start") + 1] = "2024-02-30"
        result = subprocess.run(bad, capture_output=True, text=True, timeout=15)
        self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
