from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from validate_weekly_brief import validate_report


VALID_CONTENT = """# 数字健康周报｜2026年7月13日—19日

生成时点：2026年7月19日08:58（北京时间）

> 截至当前时点，本周尚未结束。

| 事件日期 | 主体与动作 | 已核实事实 | 影响判断 |
|---|---|---|---|
| 7月13日 | 机构 | 动作 | 判断 |
| 7月15—16日 | 机构 | 动作 | 判断 |
"""


class WeeklyBriefValidationTests(unittest.TestCase):
    def write_report(self, directory: str, name: str, content: str = VALID_CONTENT) -> Path:
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
        }
        arguments.update(overrides)
        return validate_report(**arguments)

    def test_accepts_canonical_partial_week_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_report(directory, "DHWB-20260719.md")
            self.assertEqual([], self.validate(path))

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

    def test_rejects_missing_partial_week_notice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            content = VALID_CONTENT.replace("> 截至当前时点，本周尚未结束。\n", "")
            path = self.write_report(directory, "DHWB-20260719.md", content)
            errors = self.validate(path)
            self.assertTrue(any("has not ended" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
