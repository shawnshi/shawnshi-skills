"""Bounded header extraction from synthetic reports only."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_report_headers import inspect_headers


class HeaderInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def report(self, day, region="中国为主", zone="Asia/Shanghai", body=b"BODY_NOT_FOR_OUTPUT"):
        path = self.root / ("DHWB-" + day.replace("-", "") + ".md")
        header = f"# 合成周报 {day}\n地区：{region}\n报告时区：{zone}\n\n## 本周结论\n"
        path.write_bytes(header.encode("utf-8") + body)
        return path

    def three(self):
        for day in ("2000-01-02", "2000-01-09", "2000-01-16"):
            self.report(day)

    def test_only_three_prior_headers_are_returned(self):
        self.three()
        self.report("2000-01-23")
        self.report("1999-12-26")
        (self.root / "unrelated.txt").write_text("UNRELATED", encoding="utf-8")
        result = inspect_headers(self.root, date(2000, 1, 23))
        self.assertEqual("stable", result["status"])
        self.assertEqual(["DHWB-20000116.md", "DHWB-20000109.md", "DHWB-20000102.md"],
                         [row["filename"] for row in result["records"]])
        self.assertNotIn("BODY_NOT_FOR_OUTPUT", json.dumps(result))
        self.assertNotIn("UNRELATED", json.dumps(result))

    def test_body_is_not_decoded(self):
        self.three()
        self.report("2000-01-16", body=b"\xff\xfe")
        self.assertEqual("stable", inspect_headers(self.root, date(2000, 1, 23))["status"])

    def test_missing_history_is_not_an_access_error(self):
        self.assertEqual("no_history", inspect_headers(self.root, date(2000, 1, 23))["status"])
        self.report("2000-01-16")
        self.assertEqual("insufficient", inspect_headers(self.root, date(2000, 1, 23))["status"])
        with self.assertRaises(FileNotFoundError):
            inspect_headers(self.root / "missing", date(2000, 1, 23))

    def test_conflicting_region_or_timezone_is_explicit(self):
        self.three()
        self.report("2000-01-16", region="仅中国")
        self.assertEqual("conflict", inspect_headers(self.root, date(2000, 1, 23))["status"])
        self.report("2000-01-16", zone="UTC")
        self.assertEqual("conflict", inspect_headers(self.root, date(2000, 1, 23))["status"])

    def test_missing_fields_are_not_invented(self):
        self.three()
        path = self.root / "DHWB-20000116.md"
        path.write_text("# 合成\n## 本周结论\n正文", encoding="utf-8")
        self.assertEqual("insufficient", inspect_headers(self.root, date(2000, 1, 23))["status"])

    def test_duplicate_metadata_and_title_fail(self):
        self.three()
        path = self.root / "DHWB-20000116.md"
        for header in ("# 合成\n地区：中国\n地区：美国\n", "# 合成\n# 第二标题\n"):
            path.write_text(header + "## 本周结论\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect_headers(self.root, date(2000, 1, 23))

    def test_header_byte_line_and_boundary_limits_fail_closed(self):
        self.three()
        path = self.root / "DHWB-20000116.md"
        for header in (b"# " + b"x" * 4096, b"# title\n" + b"\n" * 64, b"# title\n\xff\n## body\n"):
            path.write_bytes(header)
            with self.assertRaises((ValueError, UnicodeError)):
                inspect_headers(self.root, date(2000, 1, 23))

    def test_fenced_header_fields_do_not_supply_convention(self):
        self.three()
        path = self.root / "DHWB-20000116.md"
        path.write_text("# 合成\n```\n地区：美国\n报告时区：UTC\n```\n## 本周结论\n", encoding="utf-8")
        result = inspect_headers(self.root, date(2000, 1, 23))
        self.assertEqual("insufficient", result["status"])
        self.assertNotIn("地区", result["records"][0])

    def test_comment_metadata_is_not_used(self):
        self.three()
        path = self.root / "DHWB-20000116.md"
        path.write_text("# 合成\n<!--\n地区：美国\n-->\n## 本周结论\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            inspect_headers(self.root, date(2000, 1, 23))

    def test_changed_file_identity_fails_before_header_read(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        self.three()
        with patch("inspect_report_headers.os.fstat", return_value=SimpleNamespace(st_dev=-1, st_ino=-1)):
            with self.assertRaises(ValueError):
                inspect_headers(self.root, date(2000, 1, 23))

    def test_symlink_report_is_not_followed(self):
        self.three()
        link = self.root / "DHWB-20000116.md"
        target = self.root / "other.md"
        link.rename(target)
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlink capability unavailable: {exc}")
        with self.assertRaises(ValueError):
            inspect_headers(self.root, date(2000, 1, 23))

    def test_cli_read_only_and_error_not_normalized_as_history_empty(self):
        self.three()
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        script = Path(__file__).with_name("inspect_report_headers.py")
        command = [sys.executable, "-B", "-X", "utf8", str(script), "--directory", str(self.root), "--before", "2000-01-23"]
        result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("stable", json.loads(result.stdout)["status"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})
        bad = subprocess.run(command[:-4] + ["--directory", str(self.root / "missing"), "--before", "2000-01-23"],
                             capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(1, bad.returncode)
        self.assertEqual("", bad.stdout)
        self.assertEqual("error", json.loads(bad.stderr)["status"])


if __name__ == "__main__":
    unittest.main()
