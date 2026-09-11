"""Synthetic audit regressions; no real reports, network, or archive publication."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_weekly_brief import EMPTY_EVENT_MARKER, validate_report

HEAD = """# 数字健康周报｜2000年1月3日—9日

报告周期：2000-01-03 至 2000-01-09
出刊日期：2000-01-09
生成时点：2000-01-10T00:00:00+08:00
报告时区：Asia/Shanghai

"""
SECTION = "## 关键事件与来源\n\n"
TABLE = "| 事件日期 | 主体与已核实动作 | 事实或来源主张 | 分析判断 | 证据强度 | 直接来源 |\n|---|---|---|---|---|---|\n"
ROW = "| 2000-01-05 | 合成机构发布文件 | 合成事实 | 待验证影响 | 中 | https://example.org/source |\n"


class AuditRegressions(unittest.TestCase):
    def check_content(self, content: str, **overrides: object) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DHWB-20000109.md"
            path.write_text(content, encoding="utf-8")
            args = dict(
                file_path=path, period_start=date(2000, 1, 3),
                period_end=date(2000, 1, 9), issue_date=date(2000, 1, 9),
                cutoff=datetime.fromisoformat("2000-01-10T00:00:00+08:00"),
            )
            args.update(overrides)
            return validate_report(**args)

    def test_six_columns_with_direct_source(self):
        self.assertEqual([], self.check_content(HEAD + SECTION + TABLE + ROW))

    def test_rejects_missing_columns_and_empty_cells(self):
        rows = ["| 2000-01-05 |\n", ROW.replace("| 中 ", ""),
                ROW.replace("| 中 |", "| |"), ROW.replace("合成事实", ""),
                ROW.rstrip() + " extra |\n"]
        for row in rows:
            with self.subTest(row=row):
                self.assertTrue(any("six nonempty" in e for e in self.check_content(HEAD + SECTION + TABLE + row)))

    def test_rejects_bad_sources(self):
        for source in ("S1", "见来源清单", "10.1000/test", "ftp://example.org/a",
                       "https://", "https://user:password@example.org/a", "https://example.org:bad/a"):
            with self.subTest(source=source):
                content = HEAD + SECTION + TABLE + ROW.replace("https://example.org/source", source)
                self.assertTrue(any("HTTP(S)" in e for e in self.check_content(content)))

    def test_accepts_markdown_url_and_escaped_pipe(self):
        row = ROW.replace("合成事实", r"标签 A\|B").replace(
            "https://example.org/source", "[原文](https://example.org/source?q=1#part)"
        )
        self.assertEqual([], self.check_content(HEAD + SECTION + TABLE + row))

    def test_rejects_noncanonical_header_and_separator(self):
        for table in (TABLE.replace("主体与已核实动作", "主体"), TABLE.replace("|---|---|---|---|---|---|", "|---|---|")):
            with self.subTest(table=table):
                self.assertTrue(self.check_content(HEAD + SECTION + table + ROW))

    def test_fenced_events_cannot_pass(self):
        for fence in ("```", "~~~", "````"):
            with self.subTest(fence=fence):
                self.assertTrue(self.check_content(HEAD + fence + "markdown\n" + SECTION + TABLE + ROW + fence))
                self.assertTrue(self.check_content(HEAD + SECTION + fence + "\n" + EMPTY_EVENT_MARKER + "\n" + fence))

    def test_extra_empty_columns_are_not_stripped(self):
        for row in (ROW.rstrip() + "|\n", "|" + ROW):
            self.assertTrue(any("six nonempty" in e for e in self.check_content(HEAD + SECTION + TABLE + row)))

    def test_indented_code_cannot_supply_events(self):
        content = HEAD + SECTION + "    " + ROW
        self.assertTrue(any("no dated event" in e for e in self.check_content(content)))

    def test_hidden_html_comments_cannot_supply_events(self):
        self.assertTrue(self.check_content(HEAD + "<!--\n" + SECTION + TABLE + ROW + "-->\n"))

    def test_invalid_backtick_info_cannot_hide_bad_event(self):
        content = (HEAD + SECTION + TABLE + ROW + "\n```bad`info\n\n"
                   + TABLE + "| 1999-12-31 |\n\n```\n")
        errors = self.check_content(content)
        self.assertTrue(any("six nonempty" in e for e in errors), errors)
        self.assertTrue(any("outside the reporting period" in e for e in errors), errors)

    def test_tilde_info_can_contain_backticks(self):
        content = (HEAD + SECTION + TABLE + ROW + "\n~~~bad`info\n"
                   + TABLE + "| 1999-12-31 |\n~~~\n")
        self.assertEqual([], self.check_content(content))

    def test_fenced_metadata_cannot_pass(self):
        self.assertTrue(self.check_content("```\n" + HEAD + "```\n" + SECTION + TABLE + ROW))

    def test_fenced_background_does_not_create_duplicate_section(self):
        content = HEAD + SECTION + TABLE + ROW + "\n## 说明\n~~~\n" + SECTION + "~~~\n"
        self.assertEqual([], self.check_content(content))

    def test_every_shipped_template_placeholder_is_rejected(self):
        template = (Path(__file__).resolve().parents[1] / "references/template.md").read_text(encoding="utf-8")
        for value in set(re.findall(r"\[[^\]\n]+\]", template)):
            with self.subTest(value=value):
                errors = self.check_content(HEAD + SECTION + TABLE + ROW + "\n## 说明\n" + value)
                self.assertTrue(any("placeholder" in e for e in errors), value)

    def test_old_prose_placeholder_is_rejected(self):
        errors = self.check_content(HEAD + SECTION + TABLE + ROW + "\n## 本周结论\n[基于本期事件的结论；没有足够证据时明确说明。]")
        self.assertTrue(any("placeholder" in e for e in errors))

    def test_late_header_partial_notice_accepted(self):
        head = HEAD.replace("2000-01-10T00:00:00+08:00", "2000-01-09T12:00:00+08:00")
        content = head + "\n" * 20 + "> 截至上述时点，本周尚未结束。\n" + SECTION + TABLE + ROW
        self.assertEqual([], self.check_content(content, cutoff=datetime.fromisoformat("2000-01-09T12:00:00+08:00")))

    def test_body_notice_does_not_replace_header_notice(self):
        content = HEAD.replace("2000-01-10T00:00:00+08:00", "2000-01-09T12:00:00+08:00") + SECTION + TABLE + ROW + "本周尚未结束"
        self.assertTrue(any("has not ended" in e for e in self.check_content(content, cutoff=datetime.fromisoformat("2000-01-09T12:00:00+08:00"))))

    def test_cross_year_natural_week(self):
        content = HEAD.replace("2000年1月3日—9日", "1999年12月27日—2000年1月2日").replace("2000-01-03", "1999-12-27").replace("2000-01-09", "2000-01-02") + SECTION + TABLE + ROW.replace("2000-01-05", "2000-01-01")
        self.assertEqual([], self.check_content(content, period_start=date(1999, 12, 27), period_end=date(2000, 1, 2), issue_date=date(2000, 1, 2), allow_custom_filename=True))

    def test_read_only_shared_identity_revalidates_new_source(self):
        shared = Path(__file__).resolve().parents[2] / "shared/scripts"
        sys.path.insert(0, str(shared))
        import report_archive
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DHWB-20000109.md"
            path.write_text(HEAD + SECTION + TABLE + ROW, encoding="utf-8")
            kwargs = dict(skill="hit-weekly-brief", custom_filename=False, custom_period=False, target_name=path.name)
            self.assertEqual("2000-01-03", report_archive.identity(path, validate=True, **kwargs)["period_start"])
            path.write_text(HEAD + SECTION + "| 2000-01-05 |\n", encoding="utf-8")
            # Legacy target identity remains readable; it is never auto-migrated.
            self.assertEqual("2000-01-03", report_archive.identity(path, validate=False, **kwargs)["period_start"])
            with self.assertRaises(report_archive.Blocked):
                report_archive.identity(path, validate=True, **kwargs)

    def test_fresh_process_rejects_date_only_row(self):
        script = Path(__file__).resolve().parent / "validate_weekly_brief.py"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DHWB-20000109.md"
            path.write_text(HEAD + SECTION + "| 2000-01-05 |\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, "-B", "-X", "utf8", str(script), "--file", str(path), "--period-start", "2000-01-03", "--period-end", "2000-01-09", "--issue-date", "2000-01-09", "--cutoff", "2000-01-10T00:00:00+08:00"], capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
            self.assertIn("six nonempty", proc.stdout)

    def test_rw002_duplicate_and_blank_metadata(self):
        dup_empty = HEAD.replace("出刊日期：2000-01-09", "出刊日期：\n出刊日期：2000-01-09")
        errors = self.check_content(dup_empty + SECTION + TABLE + ROW)
        self.assertTrue(any("exactly once" in e for e in errors), errors)

        blank_val = HEAD.replace("出刊日期：2000-01-09", "出刊日期：   ")
        errors_blank = self.check_content(blank_val + SECTION + TABLE + ROW)
        self.assertTrue(any("must not be blank" in e for e in errors_blank), errors_blank)

    def test_rw003_event_table_requires_header_and_separator(self):
        no_header = HEAD + SECTION + ROW
        errors = self.check_content(no_header)
        self.assertTrue(any("event table header required" in e or "must follow table header" in e for e in errors), errors)

        no_sep = HEAD + SECTION + "| 事件日期 | 主体与已核实动作 | 事实或来源主张 | 分析判断 | 证据强度 | 直接来源 |\n" + ROW
        errors_no_sep = self.check_content(no_sep)
        self.assertTrue(any("separator" in e for e in errors_no_sep), errors_no_sep)

        detached_sep = HEAD + SECTION + "| 事件日期 | 主体与已核实动作 | 事实或来源主张 | 分析判断 | 证据强度 | 直接来源 |\n\n|---|---|---|---|---|---|\n" + ROW
        errors_detached = self.check_content(detached_sep)
        self.assertTrue(any("separator" in e or "must follow" in e for e in errors_detached), errors_detached)

        parts = TABLE.split("\n", 1)
        text_before_sep = HEAD + SECTION + parts[0] + "\n说明文字\n" + parts[1] + ROW
        self.assertTrue(any("separator" in e for e in self.check_content(text_before_sep)))

        heading_before_sep = HEAD + SECTION + parts[0] + "\n### 说明\n" + parts[1] + ROW
        self.assertTrue(any("separator" in e for e in self.check_content(heading_before_sep)))

        text_before_row = HEAD + SECTION + TABLE + "说明文字\n" + ROW
        self.assertTrue(any("must follow table header and separator" in e for e in self.check_content(text_before_row)))


if __name__ == "__main__":
    unittest.main()
