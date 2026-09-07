"""Scout structural-gate regressions; synthetic records are not research evidence."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_lectures_scout as validator

ROW = "| R1 | 2000-01-05 | Synthetic method | 预印本 | v2 | https://example.org/paper/v2 | S1 |"
CONTENT = """# 医疗数字化文献侦察报告 - 2000-01-09

报告周期：2000-01-03 至 2000-01-09
出刊日期：2000-01-09
生成时点：2000-01-10T00:00:00+08:00
报告时区：Asia/Shanghai
命名依据：explicit

## 本期研究

| 研究ID | 日期 | 标题 | 评审状态 | 版本 | 永久链接 | 来源编号 |
|---|---|---|---|---|---|---|
""" + ROW + """

## 来源

| 来源编号 | 原始链接 |
|---|---|
| S1 | https://example.org/paper/v2 |
"""


class ValidateLecturesScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hit-scout-validator-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "DHLS-20000109.md"
        self.args = dict(period_start=date(2000, 1, 3), period_end=date(2000, 1, 9),
                         issue_date=date(2000, 1, 9), cutoff=datetime.fromisoformat("2000-01-10T00:00:00+08:00"),
                         now=datetime.fromisoformat("2000-02-01T00:00:00+08:00"))

    def check(self, content=CONTENT, **overrides):
        self.path.write_text(content, encoding="utf-8")
        return validator.validate_report(self.path, **(self.args | overrides))

    def rejects(self, content, message, **overrides):
        self.assertTrue(any(message in error for error in self.check(content, **overrides)), message)

    def test_valid_explicit_window_uses_end_not_generation_date(self):
        self.assertEqual([], self.check())

    def test_source_missing_and_directory_io(self):
        for path in (self.path, Path(self.temp.name)):
            with self.subTest(path=path):
                self.assertIn("source IO", validator.validate_report(path, **self.args)[0])

    def test_invalid_utf8_source(self):
        self.path.write_bytes(b"\xff")
        self.assertIn("source IO", validator.validate_report(self.path, **self.args)[0])

    def test_metadata_mismatch(self):
        for old, new in (("2000-01-03 至", "2000-01-04 至"), ("出刊日期：2000-01-09", "出刊日期：2000-01-08"),
                         ("报告时区：Asia/Shanghai", "报告时区：UTC"), ("命名依据：explicit", "命名依据：generated")):
            with self.subTest(field=old):
                self.rejects(CONTENT.replace(old, new), "mismatch")

    def test_metadata_missing_or_duplicate_not_rescued_by_body(self):
        field = "报告周期：2000-01-03 至 2000-01-09"
        self.rejects(CONTENT.replace(field, "") + "\n" + field, "exactly once")
        self.rejects(CONTENT.replace(field, field + "\n" + field), "exactly once")

    def test_cutoff_future_and_naive(self):
        self.rejects(CONTENT, "future cutoff", now=datetime.fromisoformat("2000-01-09T00:00:00Z"))
        self.rejects(CONTENT, "cutoff must include timezone", cutoff=datetime(2000, 1, 10))

    def test_header_cutoff_aware_equivalent_instant(self):
        self.assertEqual([], self.check(CONTENT.replace("2000-01-10T00:00:00+08:00", "2000-01-09T16:00:00Z")))
        self.rejects(CONTENT.replace("2000-01-10T00:00:00+08:00", "2000-01-10T00:00:00"), "生成时点 mismatch")

    def test_generated_mode_timezone_crossday_uses_local_date(self):
        content = CONTENT.replace("2000-01-09", "2000-01-10").replace("命名依据：explicit", "命名依据：generated")
        content = content.replace("2000-01-03 至 2000-01-10", "2000-01-03 至 2000-01-09")
        self.path = self.path.with_name("DHLS-20000110.md")
        self.assertEqual([], self.check(content, issue_date=date(2000, 1, 10), window_mode="generated",
                                        cutoff=datetime.fromisoformat("2000-01-09T16:00:00Z")))

    def test_wrong_issue_rule_or_filename(self):
        self.rejects(CONTENT, "issue date must use", issue_date=date(2000, 1, 10))
        self.path = self.path.with_name("custom.md")
        self.rejects(CONTENT, "issue filename mismatch")
        self.assertEqual([], self.check(allow_custom_filename=True))

    def test_title_mismatch(self):
        self.rejects(CONTENT.replace("报告 - 2000-01-09", "报告 - 2000-01-10"), "title issue date mismatch")

    def test_current_outside_window_background_allowed(self):
        old = ROW.replace("R1", "R2").replace("2000-01-05", "1999-12-01")
        self.rejects(CONTENT.replace(ROW, old), "current research outside")
        self.assertEqual([], self.check(CONTENT + "\n## 背景研究\n" + old + "\n"))

    def test_research_after_cutoff_and_invalid_date(self):
        self.rejects(CONTENT.replace("2000-01-05", "2000-02-02"), "research date after cutoff")
        self.rejects(CONTENT.replace("2000-01-05", "2000-02-30"), "invalid research date")

    def test_duplicate_and_invalid_research_ids(self):
        self.rejects(CONTENT.replace(ROW, ROW + "\n" + ROW), "invalid/duplicate research ID")
        self.rejects(CONTENT.replace("| R1 |", "| DOI1 |"), "invalid/duplicate research ID")

    def test_known_review_statuses_and_unknown_label(self):
        for status in validator.STATUSES:
            with self.subTest(status=status):
                self.assertEqual([], self.check(CONTENT.replace("预印本", status)))
        self.rejects(CONTENT.replace("预印本", "已证实临床有效"), "unknown review status")

    def test_explicit_version_required(self):
        for version in ("", "未知", "未核实", "不适用", "-"):
            with self.subTest(version=version):
                self.rejects(CONTENT.replace("| v2 |", f"| {version} |"), "explicit version required")

    def test_permanent_https_link_required(self):
        for link in ("http://example.org/paper", "https://user:pass@example.org/paper", "https://", "https://example.org/a b"):
            with self.subTest(link=link):
                self.rejects(CONTENT.replace(ROW, ROW.replace("https://example.org/paper/v2", link)), "permanent/original HTTPS")

    def test_malformed_url_source_and_permanent_are_errors_not_exceptions(self):
        self.rejects(CONTENT.replace(ROW, ROW.replace("https://example.org/paper/v2", "https://[broken")), "permanent/original HTTPS")
        self.rejects(CONTENT.replace("| S1 | https://example.org/paper/v2 |", "| S1 | https://[broken |"), "invalid source row")

    def test_url_ports_in_permanent_and_source_links(self):
        original = "https://example.org/paper/v2"
        source_row = f"| S1 | {original} |"
        for port in ("abc", "99999"):
            link = f"https://example.org:{port}/paper/v2"
            with self.subTest(port=port, column="permanent"):
                self.rejects(CONTENT.replace(ROW, ROW.replace(original, link)), "permanent/original HTTPS")
            with self.subTest(port=port, column="source"):
                self.rejects(CONTENT.replace(source_row, source_row.replace(original, link)), "invalid source row")
        for link in (original, "https://example.org:443/paper/v2", "https://example.org:8443/paper/v2"):
            with self.subTest(link=link):
                self.assertEqual([], self.check(CONTENT.replace(original, link)))
        self.rejects(CONTENT.replace(source_row, source_row.replace("https:", "http:")), "invalid source row")

    def test_source_id_duplicate_and_invalid(self):
        self.rejects(CONTENT + "| S1 | https://example.org/another |\n", "duplicate source ID")
        self.rejects(CONTENT.replace("| S1 | https://", "| SOURCE1 | https://"), "invalid source row")

    def test_unknown_source_and_research_references(self):
        self.rejects(CONTENT.replace("| S1 |\n", "| S2 |\n"), "unknown source reference ID")
        self.rejects(CONTENT + "\n## 解释\n见 [S2]。", "unknown source reference ID")
        self.rejects(CONTENT + "\n## 解释\n见 [R2]。", "unknown research reference ID")

    def test_reference_id_list_format(self):
        self.rejects(CONTENT.replace("| S1 |\n", "| S1, S2 |\n"), "invalid source reference IDs")
        content = CONTENT.replace("| S1 |\n", "| S1,S2 |\n") + "| S2 | https://example.org/second |\n"
        self.assertEqual([], self.check(content))

    def test_known_placeholders_and_replacement_character(self):
        for token in ("[待填写结论]", "[PERIOD_START]", "[永久HTTPS链接]", "\ufffd"):
            with self.subTest(token=token):
                self.rejects(CONTENT + "\n## 说明\n" + token, "unresolved placeholder")

    def test_scientific_intervals_and_ordinary_markdown_are_valid(self):
        self.assertEqual([], self.check(CONTENT + "\n## 研究细节\n95% CI [0.82, 1.07]；N/P 原文未报告。\n"
                                       "- [x] 核验格式\n[原文](https://example.org/paper/v2)；见 [R1]、[S1]。\n"
                                       "[reference]: https://example.org/reference\n"))

    def test_valid_empty_result(self):
        self.assertEqual([], self.check(CONTENT.replace(ROW, validator.EMPTY)))

    def test_empty_missing_duplicate_or_contradictory(self):
        for replacement in ("", validator.EMPTY + "\n" + validator.EMPTY, ROW + "\n" + validator.EMPTY):
            with self.subTest(replacement=replacement):
                self.rejects(CONTENT.replace(ROW, replacement), "empty research marker")

    def test_required_and_duplicate_sections(self):
        self.rejects(CONTENT.replace("## 本期研究", "## 研究概览"), "required/duplicate")
        self.rejects(CONTENT + "\n## 来源\n", "required/duplicate")
        self.rejects(CONTENT + "\n## 背景研究\n\n## 背景研究\n", "required/duplicate")

    def test_malformed_research_row_and_missing_title(self):
        self.rejects(CONTENT.replace(ROW, "| R1 | 2000-01-05 |"), "malformed research row")
        self.rejects(CONTENT.replace("Synthetic method", ""), "missing title")

    def test_invalid_timezone_period_and_window_mode(self):
        self.rejects(CONTENT, "invalid metadata", report_timezone="Unknown/Zone")
        self.rejects(CONTENT, "invalid period/cutoff", period_start=date(2000, 1, 11))
        self.rejects(CONTENT, "unknown window mode", window_mode="other")

    def test_background_does_not_count_as_current_result(self):
        self.rejects(CONTENT.replace("## 本期研究", "## 本期研究\n\n## 背景研究"), "empty research marker missing")

    def test_cli_malformed_url_has_failure_without_traceback(self):
        self.path.write_text(CONTENT.replace("https://example.org/paper/v2", "https://[broken"), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(validator.__file__)),
                                 "--file", str(self.path), "--period-start", "2000-01-03", "--period-end", "2000-01-09",
                                 "--issue-date", "2000-01-09", "--cutoff", "2000-01-10T00:00:00+08:00"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(1, result.returncode)
        self.assertIn("FAIL:", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
