from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone, tzinfo
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_weekly_brief import main, validate_report


class MockDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        fixed = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
        if tz is not None:
            return fixed.astimezone(tz)
        return fixed


VALID_CONTENT = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-07-19T08:58:00+08:00
报告时区：Asia/Shanghai

> 截至当前时点，本周尚未结束。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 7月13日 | 机构 | 动作 | 判断 |
| 7月15—16日 | 机构 | 动作 | 判断 |
"""

HISTORICAL_2000_CONTENT = """# 数字健康周报｜2000年1月3日—9日

报告周期：2000-01-03 至 2000-01-09
出刊日期：2000-01-09
生成时点：2000-01-09T08:58:00+08:00
报告时区：Asia/Shanghai

> 截至当前时点，本周尚未结束。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 1月3日 | 机构 | 动作 | 判断 |
| 1月5—6日 | 机构 | 动作 | 判断 |
"""

COMPLETED_WEEK_CONTENT = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-07-20T00:00:00+08:00
报告时区：Asia/Shanghai

> 覆盖范围：2026年7月13日至2026年7月19日完整自然周。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 7月13日 | 机构 | 动作 | 判断 |
| 7月15—16日 | 机构 | 动作 | 判断 |
"""


class WeeklyBriefValidationTests(unittest.TestCase):
    def write_report(
        self, directory: str, name: str, content: str = VALID_CONTENT
    ) -> Path:
        # Date-focused legacy fixtures use four columns. Expand only their exact
        # synthetic rows to the current source schema; production never migrates
        # reports here. Shape/URL negative cases live in test_audit_regressions.py.
        content = content.replace(
            "| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |\n|---|---|---|---|",
            "| 事件日期 | 主体与已核实动作 | 事实或来源主张 | 分析判断 | 证据强度 | 直接来源 |\n|---|---|---|---|---|---|",
        ).replace(
            "| 机构 | 动作 | 判断 |", "| 机构 | 动作 | 判断 | 中 | https://example.org/source |"
        )
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8")
        return path

    def validate(self, path: Path, **overrides: object) -> list[str]:
        arguments = {
            "file_path": path,
            "period_start": date(2026, 7, 13),
            "period_end": date(2026, 7, 19),
            "issue_date": date(2026, 7, 19),
            "cutoff": datetime.fromisoformat("2026-07-19T08:58:00+08:00"),
            "now": datetime.fromisoformat("2026-07-20T12:00:00+08:00"),
        }
        arguments.update(overrides)
        return validate_report(**arguments)

    def test_accepts_canonical_partial_week_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            self.assertEqual([], self.validate(path))

    def test_accepts_canonical_completed_natural_week_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory, "DHWB-20260719.md", COMPLETED_WEEK_CONTENT
            )
            errors = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-20T00:00:00+08:00"),
                now=datetime.fromisoformat("2026-07-20T12:00:00+08:00"),
            )
            self.assertEqual([], errors)

    def test_rejects_wrong_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260712.md")
            errors = self.validate(path)
            self.assertTrue(any("filename" in error for error in errors))

    def test_rejects_non_monday_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(path, period_start=date(2026, 7, 14))
            self.assertTrue(any("Monday" in error for error in errors))

    def test_rejects_issue_date_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(path, issue_date=date(2026, 7, 12))
            self.assertTrue(any("issue_date" in error for error in errors))

    def test_rejects_event_outside_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace("7月13日 | 机构", "7月12日 | 机构")
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("outside" in error for error in errors))

    def test_rejects_event_after_period_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace("7月13日 | 机构", "7月20日 | 机构")
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(
                any("outside the reporting period" in error for error in errors)
            )

    def test_rejects_event_after_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-07-15T12:00:00+08:00
报告时区：Asia/Shanghai

> 截至当前时点，本周尚未结束。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 2026-07-14 | 机构 | 动作 | 判断 |
| 2026-07-16 | 机构 | 动作 | 判断 |
"""
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-15T12:00:00+08:00"),
            )
            self.assertTrue(any("later than the cutoff" in error for error in errors))

    def test_rejects_missing_partial_week_notice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace("> 截至当前时点，本周尚未结束。\n", "")
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("has not ended" in error for error in errors))

    def test_accepts_iso_event_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace("| 7月13日 |", "| 2026-07-13 |").replace(
                "| 7月15—16日 |", "| 2026-07-15 至 2026-07-16 |"
            )
            path = self.write_report(directory, "DHWB-20260719.md", content)
            self.assertEqual([], self.validate(path))

    def test_accepts_explicit_empty_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-07-19T08:58:00+08:00
报告时区：Asia/Shanghai

> 截至当前时点，本周尚未结束。

## 关键事件与来源

本周期未发现符合纳入标准的事件
"""
            path = self.write_report(directory, "DHWB-20260719.md", content)
            self.assertEqual([], self.validate(path))

    def test_rejects_missing_empty_marker_when_no_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-07-19T08:58:00+08:00
报告时区：Asia/Shanghai

> 截至当前时点，本周尚未结束。

## 关键事件与来源

本周无重大新闻。
"""
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(
                any("explicit empty-period marker" in error for error in errors)
            )

    def test_rejects_unresolved_template_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT + "\n地区：[REGION]\n"
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("placeholder" in error for error in errors))

    def test_accepts_custom_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月1日—10日

报告周期：2026-07-01 至 2026-07-10
出刊日期：2026-07-10
生成时点：2026-07-11T00:00:00+08:00
报告时区：Asia/Shanghai

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 2026-07-02 | 机构 | 动作 | 判断 |
| 2026-07-08 | 机构 | 动作 | 判断 |
"""
            path = self.write_report(directory, "DHWB-20260710.md", content)
            errors = self.validate(
                path,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 10),
                issue_date=date(2026, 7, 10),
                cutoff=datetime.fromisoformat("2026-07-11T00:00:00+08:00"),
                now=datetime.fromisoformat("2026-07-11T12:00:00+08:00"),
                allow_custom_period=True,
            )
            self.assertEqual([], errors)

    def test_rejects_custom_period_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月1日—10日

报告周期：2026-07-01 至 2026-07-10
出刊日期：2026-07-10
生成时点：2026-07-11T00:00:00+08:00
报告时区：Asia/Shanghai

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 2026-07-02 | 机构 | 动作 | 判断 |
"""
            path = self.write_report(directory, "DHWB-20260710.md", content)
            errors = self.validate(
                path,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 10),
                issue_date=date(2026, 7, 10),
                cutoff=datetime.fromisoformat("2026-07-11T00:00:00+08:00"),
                now=datetime.fromisoformat("2026-07-11T12:00:00+08:00"),
                allow_custom_period=False,
            )
            self.assertTrue(
                any("natural week" in error or "Monday" in error for error in errors)
            )

    def test_rejects_inverted_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260710.md")
            errors = self.validate(
                path,
                period_start=date(2026, 7, 19),
                period_end=date(2026, 7, 10),
                issue_date=date(2026, 7, 10),
                allow_custom_period=True,
            )
            self.assertTrue(any("on or before period_end" in error for error in errors))

    def test_accepts_historical_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-08-16T10:00:00+08:00
报告时区：Asia/Shanghai

> 覆盖范围：2026年7月13日至2026年7月19日历史自然周。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 7月14日 | 机构 | 动作 | 判断 |
| 7月18日 | 机构 | 动作 | 判断 |
"""
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(
                path,
                period_start=date(2026, 7, 13),
                period_end=date(2026, 7, 19),
                issue_date=date(2026, 7, 19),
                cutoff=datetime.fromisoformat("2026-08-16T10:00:00+08:00"),
                now=datetime.fromisoformat("2026-08-17T00:00:00+08:00"),
            )
            self.assertEqual([], errors)

    def test_rejects_future_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-19T09:00:00+08:00"),
                now=datetime.fromisoformat("2026-07-19T08:00:00+08:00"),
            )
            self.assertTrue(any("future" in error for error in errors))

    def test_rejects_cutoff_earlier_than_period_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-10T12:00:00+08:00"),
            )
            self.assertTrue(
                any("earlier than period_start" in error for error in errors)
            )

    def test_rejects_heading_period_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace(
                "# 数字健康周报｜2026年7月13日—19日",
                "# 数字健康周报｜2026年7月1日—7日",
            )
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("first heading must be" in error for error in errors))

    def test_rejects_unresolved_partial_period_template_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace(
                "> 截至当前时点，本周尚未结束。",
                "> 截止说明：[若周期尚未结束，写明“截至上述时点，本周尚未结束”；完整周写明覆盖范围。]",
            )
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("placeholder" in error for error in errors))

    def test_rejects_naive_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(
                path,
                cutoff=datetime(2026, 7, 19, 8, 58),
            )
            self.assertTrue(
                any(
                    "cutoff must include explicit timezone offset" in error
                    for error in errors
                )
            )

    def test_rejects_naive_now(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors = self.validate(
                path,
                now=datetime(2026, 7, 20, 12, 0),
            )
            self.assertTrue(
                any(
                    "now must include explicit timezone offset" in error
                    for error in errors
                )
            )

    def test_accepts_timezone_offset_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            errors_same = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-19T08:58:00+08:00"),
                now=datetime.fromisoformat("2026-07-19T00:58:00Z"),
            )
            self.assertEqual([], errors_same)

            errors_diff_offset = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-19T08:58:00+08:00"),
                now=datetime.fromisoformat("2026-07-19T09:58:00+09:00"),
            )
            self.assertEqual([], errors_diff_offset)

            errors_future = self.validate(
                path,
                cutoff=datetime.fromisoformat("2026-07-19T08:58:01+08:00"),
                now=datetime.fromisoformat("2026-07-19T00:58:00Z"),
            )
            self.assertTrue(any("future" in error for error in errors_future))

    def test_period_end_boundary_last_minute_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path_completed = self.write_report(
                directory, "DHWB-20260719.md", COMPLETED_WEEK_CONTENT
            )
            errors = self.validate(
                path_completed,
                cutoff=datetime.fromisoformat("2026-07-19T23:59:00+08:00"),
                now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
            )
            self.assertTrue(any("has not ended" in error for error in errors))

            path_partial = self.write_report(
                directory,
                "DHWB-20260719.md",
                VALID_CONTENT.replace("08:58:00", "23:59:00"),
            )
            self.assertEqual(
                [],
                self.validate(
                    path_partial,
                    cutoff=datetime.fromisoformat("2026-07-19T23:59:00+08:00"),
                    now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
                ),
            )

    def test_period_end_boundary_last_second_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path_completed = self.write_report(
                directory, "DHWB-20260719.md", COMPLETED_WEEK_CONTENT
            )
            errors = self.validate(
                path_completed,
                cutoff=datetime.fromisoformat("2026-07-19T23:59:59+08:00"),
                now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
            )
            self.assertTrue(any("has not ended" in error for error in errors))

            path_partial = self.write_report(
                directory,
                "DHWB-20260719.md",
                VALID_CONTENT.replace("08:58:00", "23:59:59"),
            )
            self.assertEqual(
                [],
                self.validate(
                    path_partial,
                    cutoff=datetime.fromisoformat("2026-07-19T23:59:59+08:00"),
                    now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
                ),
            )

    def test_period_end_boundary_last_microsecond_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path_completed = self.write_report(
                directory, "DHWB-20260719.md", COMPLETED_WEEK_CONTENT
            )
            errors = self.validate(
                path_completed,
                cutoff=datetime.fromisoformat("2026-07-19T23:59:59.999999+08:00"),
                now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
            )
            self.assertTrue(any("has not ended" in error for error in errors))

            path_partial = self.write_report(
                directory,
                "DHWB-20260719.md",
                VALID_CONTENT.replace("08:58:00", "23:59:59.999999"),
            )
            self.assertEqual(
                [],
                self.validate(
                    path_partial,
                    cutoff=datetime.fromisoformat("2026-07-19T23:59:59.999999+08:00"),
                    now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
                ),
            )

    def test_period_end_boundary_next_day_zero_is_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path_completed = self.write_report(
                directory, "DHWB-20260719.md", COMPLETED_WEEK_CONTENT
            )
            errors = self.validate(
                path_completed,
                cutoff=datetime.fromisoformat("2026-07-20T00:00:00+08:00"),
                now=datetime.fromisoformat("2026-07-21T00:00:00+08:00"),
            )
            self.assertEqual([], errors)

    def test_historical_backfill_rejects_event_after_period_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = """# 数字健康周报｜2026年7月13日—19日

报告周期：2026-07-13 至 2026-07-19
出刊日期：2026-07-19
生成时点：2026-08-16T10:00:00+08:00
报告时区：Asia/Shanghai

> 覆盖范围：2026年7月13日至2026年7月19日历史自然周。

## 关键事件与来源

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 2026-07-14 | 机构 | 动作 | 判断 |
| 2026-07-20 | 机构 | 动作 | 判断 |
"""
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(
                path,
                period_start=date(2026, 7, 13),
                period_end=date(2026, 7, 19),
                issue_date=date(2026, 7, 19),
                cutoff=datetime.fromisoformat("2026-08-16T10:00:00+08:00"),
                now=datetime.fromisoformat("2026-08-17T00:00:00+08:00"),
            )
            self.assertTrue(
                any("outside the reporting period" in error for error in errors)
            )

    def test_cli_positive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md", VALID_CONTENT)
            with patch("validate_weekly_brief.datetime", MockDatetime):
                ret = main(
                    [
                        "--file",
                        str(path),
                        "--period-start",
                        "2026-07-13",
                        "--period-end",
                        "2026-07-19",
                        "--issue-date",
                        "2026-07-19",
                        "--cutoff",
                        "2026-07-19T08:58:00+08:00",
                    ]
                )
            self.assertEqual(0, ret)

    def test_cli_negative_missing_arguments(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--period-start", "2026-07-13"])
        self.assertNotEqual(0, ctx.exception.code)

    def test_cli_negative_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md", VALID_CONTENT)
            with patch("validate_weekly_brief.datetime", MockDatetime):
                ret = main(
                    [
                        "--file",
                        str(path),
                        "--period-start",
                        "2026-07-14",
                        "--period-end",
                        "2026-07-19",
                        "--issue-date",
                        "2026-07-19",
                        "--cutoff",
                        "2026-07-19T08:58:00+08:00",
                    ]
                )
            self.assertEqual(1, ret)

    def test_cli_negative_naive_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md", VALID_CONTENT)
            with patch("validate_weekly_brief.datetime", MockDatetime):
                ret = main(
                    [
                        "--file",
                        str(path),
                        "--period-start",
                        "2026-07-13",
                        "--period-end",
                        "2026-07-19",
                        "--issue-date",
                        "2026-07-19",
                        "--cutoff",
                        "2026-07-19T08:58:00",
                    ]
                )
            self.assertEqual(1, ret)

    def test_cli_rejects_now_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md", VALID_CONTENT)
            with self.assertRaises(SystemExit) as ctx:
                main(
                    [
                        "--file",
                        str(path),
                        "--period-start",
                        "2026-07-13",
                        "--period-end",
                        "2026-07-19",
                        "--issue-date",
                        "2026-07-19",
                        "--cutoff",
                        "2026-07-19T08:58:00+08:00",
                        "--now",
                        "2026-07-20T00:00:00+08:00",
                    ]
                )
            self.assertNotEqual(0, ctx.exception.code)

    def test_cli_subprocess_positive_and_negative(self) -> None:
        # Subprocess tests execute the validator without CLI mocking hooks.
        # They use a stable historical year-2000 fixture and rely only on the
        # host system clock being later than 2000-01-09.
        import subprocess

        script = Path(__file__).resolve().parent / "validate_weekly_brief.py"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory, "DHWB-20000109.md", HISTORICAL_2000_CONTENT
            )
            proc_ok = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(script),
                    "--file",
                    str(path),
                    "--period-start",
                    "2000-01-03",
                    "--period-end",
                    "2000-01-09",
                    "--issue-date",
                    "2000-01-09",
                    "--cutoff",
                    "2000-01-09T08:58:00+08:00",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, proc_ok.returncode)
            self.assertIn("OK:", proc_ok.stdout)

            proc_fail = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(script),
                    "--file",
                    str(path),
                    "--period-start",
                    "2000-01-04",
                    "--period-end",
                    "2000-01-09",
                    "--issue-date",
                    "2000-01-09",
                    "--cutoff",
                    "2000-01-09T08:58:00+08:00",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(1, proc_fail.returncode)
            self.assertIn("FAIL:", proc_fail.stdout)

    def test_cli_subprocess_rejects_now_flag(self) -> None:
        import subprocess

        script = Path(__file__).resolve().parent / "validate_weekly_brief.py"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory, "DHWB-20000109.md", HISTORICAL_2000_CONTENT
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(script),
                    "--file",
                    str(path),
                    "--period-start",
                    "2000-01-03",
                    "--period-end",
                    "2000-01-09",
                    "--issue-date",
                    "2000-01-09",
                    "--cutoff",
                    "2000-01-09T08:58:00+08:00",
                    "--now",
                    "2026-07-20T00:00:00+08:00",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("unrecognized arguments: --now", proc.stderr)


class WeeklyBriefMetadataTests(unittest.TestCase):
    write_report = WeeklyBriefValidationTests.write_report
    validate = WeeklyBriefValidationTests.validate

    def test_body_metadata_conflicts_and_missing_duplicate_fields(self) -> None:
        for old, new in [
            (
                "报告周期：2026-07-13 至 2026-07-19",
                "报告周期：2099-01-01 至 2099-01-07",
            ),
            ("出刊日期：2026-07-19", "出刊日期：2099-01-07"),
            ("生成时点：2026-07-19T08:58:00+08:00", "生成时点：2099-01-07T00:00:00Z"),
            ("报告时区：Asia/Shanghai", "报告时区：UTC"),
            ("出刊日期：2026-07-19", ""),
            ("出刊日期：2026-07-19", "出刊日期：2026-07-19\n出刊日期：2026-07-19"),
        ]:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as directory:
                path = self.write_report(
                    directory, "DHWB-20260719.md", VALID_CONTENT.replace(old, new)
                )
                self.assertTrue(self.validate(path))

    def test_completed_week_timezone_equivalent_cutoffs(self) -> None:
        content = COMPLETED_WEEK_CONTENT.replace(
            "2026年7月13日—19日", "2026年8月31日—9月6日"
        )
        content = content.replace("2026-07-13", "2026-08-31").replace(
            "2026-07-19", "2026-09-06"
        )
        content = content.replace(
            "2026-07-20T00:00:00+08:00", "2026-09-07T00:30:00+08:00"
        )
        content = content.replace("7月13日", "8月31日").replace(
            "7月15—16日", "9月1—2日"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260906.md", content)
            for value in ("2026-09-07T00:30:00+08:00", "2026-09-06T16:30:00Z"):
                self.assertEqual(
                    [],
                    self.validate(
                        path,
                        period_start=date(2026, 8, 31),
                        period_end=date(2026, 9, 6),
                        issue_date=date(2026, 9, 6),
                        cutoff=datetime.fromisoformat(value),
                        now=datetime.fromisoformat("2026-09-08T00:00Z"),
                    ),
                )

    def test_malformed_rows_do_not_disappear(self) -> None:
        for value in ("2026/09/99", "不详", "2026-07-99", "7月16—15日"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = self.write_report(
                    directory,
                    "DHWB-20260719.md",
                    VALID_CONTENT.replace("7月13日 |", value + " |"),
                )
                self.assertTrue(self.validate(path))

    def test_background_table_is_not_current_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT + "\n## 背景事件\n\n| 2000-01-01 | 历史背景 |\n"
            path = self.write_report(directory, "DHWB-20260719.md", content)
            self.assertEqual([], self.validate(path))

    def test_empty_marker_conflicts_with_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory,
                "DHWB-20260719.md",
                VALID_CONTENT + "\n本周期未发现符合纳入标准的事件\n",
            )
            self.assertTrue(any("contradicts" in e for e in self.validate(path)))


class WeeklyBriefTemplateContractTests(unittest.TestCase):
    write_report = WeeklyBriefValidationTests.write_report
    validate = WeeklyBriefValidationTests.validate

    def test_invalid_report_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            for zone in ("Invalid/Not_A_Zone", "../UTC", ""):
                with self.subTest(zone=zone):
                    self.assertIn(
                        "report timezone unavailable or invalid",
                        self.validate(path, report_timezone=zone),
                    )

    def test_missing_event_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory,
                "DHWB-20260719.md",
                VALID_CONTENT.replace("## 关键事件与来源", "## 背景事件"),
            )
            self.assertIn(
                "exactly one ## 关键事件与来源 section required", self.validate(path)
            )

    def test_duplicate_event_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(
                directory, "DHWB-20260719.md", VALID_CONTENT + "\n## 关键事件与来源\n"
            )
            self.assertIn(
                "exactly one ## 关键事件与来源 section required", self.validate(path)
            )

    def test_duplicate_empty_period_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.split("| 事件日期", 1)[0]
            content += "本周期未发现符合纳入标准的事件\n" * 2
            path = self.write_report(directory, "DHWB-20260719.md", content)
            self.assertIn(
                "empty-period marker contradicts event rows or is duplicated",
                self.validate(path),
            )

    def test_utc_previous_date_uses_report_date_for_start_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace(
                "2026-07-19T08:58:00+08:00", "2026-07-13T00:30:00+08:00"
            )
            content = content.replace("| 7月15—16日 | 机构 | 动作 | 判断 |\n", "")
            path = self.write_report(directory, "DHWB-20260719.md", content)
            cutoff = datetime.fromisoformat("2026-07-12T16:30:00Z")
            self.assertEqual([], self.validate(path, cutoff=cutoff))
            path.write_text(
                path.read_text(encoding="utf-8").replace("| 7月13日 |", "| 7月14日 |"),
                encoding="utf-8",
            )
            self.assertTrue(
                any(
                    "later than the cutoff" in e
                    for e in self.validate(path, cutoff=cutoff)
                )
            )

    def test_utc_report_timezone_keeps_sunday_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = COMPLETED_WEEK_CONTENT.replace(
                "报告时区：Asia/Shanghai", "报告时区：UTC"
            )
            path = self.write_report(directory, "DHWB-20260719.md", content)
            cutoff = datetime.fromisoformat("2026-07-19T16:00:00Z")
            self.assertIn(
                "partial-week report must state that the week has not ended",
                self.validate(path, cutoff=cutoff, report_timezone="UTC"),
            )
            content = path.read_text(encoding="utf-8").replace(
                "> 覆盖范围：", "> 截至上述时点，本周尚未结束。覆盖范围："
            )
            path.write_text(content, encoding="utf-8")
            self.assertEqual(
                [], self.validate(path, cutoff=cutoff, report_timezone="UTC")
            )

    def test_filled_official_template_matches_real_cli(self) -> None:
        # Only the shipped template and synthetic historical data; no archive reads.
        import re
        import subprocess

        skill = Path(__file__).resolve().parents[1]
        template = (skill / "references" / "template.md").read_text(encoding="utf-8")
        for empty, partial, zone, invalid in (
            (False, False, "Asia/Shanghai", False),
            (True, False, "Asia/Shanghai", False),
            (False, True, "UTC", False),
            (False, False, "Asia/Shanghai", True),
        ):
            with (
                self.subTest(empty=empty, partial=partial, zone=zone, invalid=invalid),
                tempfile.TemporaryDirectory() as directory,
            ):
                cutoff = "2000-01-09T08:58:00Z" if partial else "2000-01-09T16:00:00Z"
                content = template
                if empty:
                    content = re.sub(
                        r"^\| \[YYYY-MM-DD\] .*\n",
                        "本周期未发现符合纳入标准的事件\n",
                        content,
                        count=1,
                        flags=re.M,
                    )
                fields = {
                    "按报告周期填写规范化标题": "2000年1月3日—9日",
                    "PERIOD_START": "2000-01-03",
                    "PERIOD_END": "2000-01-09",
                    "ISSUE_DATE": "2000-01-09",
                    "CUTOFF_TIME 带偏移ISO-8601": cutoff,
                    "REGION": "合成地区",
                    "AUDIENCE": "合成受众",
                    "YYYY-MM-DD": "2000-01-03",
                    "原始页面 URL": "https://example.org/synthetic",
                }
                content = re.sub(
                    r"\[([^\]\n]+)\]",
                    lambda m, fields=fields, partial=partial: fields.get(
                        m[1],
                        "截至上述时点，本周尚未结束"
                        if m[1].startswith("若周期尚未结束") and partial
                        else "合成说明",
                    ),
                    content,
                )
                content = content.replace(
                    "报告时区：Asia/Shanghai", f"报告时区：{zone}"
                )
                if invalid:
                    content = content.replace(
                        "出刊日期：2000-01-09", "出刊日期：2000-01-08"
                    )
                path = self.write_report(directory, "DHWB-20000109.md", content)
                errors = validate_report(
                    path,
                    date(2000, 1, 3),
                    date(2000, 1, 9),
                    date(2000, 1, 9),
                    datetime.fromisoformat(cutoff),
                    report_timezone=zone,
                )
                self.assertEqual(invalid, bool(errors), errors)
                args = [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    str(skill / "scripts" / "validate_weekly_brief.py"),
                    "--file",
                    str(path),
                    "--period-start",
                    "2000-01-03",
                    "--period-end",
                    "2000-01-09",
                    "--issue-date",
                    "2000-01-09",
                    "--cutoff",
                    cutoff,
                ]
                if zone != "Asia/Shanghai":
                    args += ["--report-timezone", zone]
                proc = subprocess.run(
                    args, capture_output=True, text=True, encoding="utf-8", timeout=30
                )
                self.assertEqual(
                    int(invalid), proc.returncode, proc.stdout + proc.stderr
                )
                self.assertIn("FAIL:" if invalid else "OK:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
