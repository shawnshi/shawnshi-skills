"""Read-only CLI contract and task-specific regressions; synthetic fixtures only."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "shared/scripts"))
SCRIPT = ROOT / "scripts/validate_weekly_brief.py"


class RuntimeContractTests(unittest.TestCase):
    def test_describe_contract_is_read_only_json(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--describe-contract"],
                                    cwd=td, capture_output=True, encoding="utf-8", timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("hit-weekly-brief", value["skill"])
            self.assertEqual(1, value["schema_version"])
            self.assertTrue(value["read_only"])
            self.assertTrue(value["tables"])
            self.assertEqual([], list(Path(td).iterdir()))

    def test_describe_cannot_mix_with_validation_arguments(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--describe-contract", "--file", "missing.md"],
                                capture_output=True, timeout=10)
        self.assertEqual(2, result.returncode)


    def check(self, content):
        from datetime import date, datetime
        import validate_weekly_brief as gate
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DHWB-20000109.md"
            path.write_text(content, encoding="utf-8")
            return gate.validate_report(path, date(2000, 1, 3), date(2000, 1, 9), date(2000, 1, 9),
                                        datetime.fromisoformat("2000-01-10T00:00:00+08:00"))

    def report(self):
        from test_audit_regressions import HEAD, SECTION, TABLE, ROW
        return HEAD + SECTION + TABLE + ROW

    def test_mixed_indent_code_does_not_supply_events(self):
        from test_audit_regressions import HEAD, SECTION, TABLE, ROW
        for prefix in (" \t", "  \t", "   \t", "\t"):
            block = "\n".join(prefix + line for line in (SECTION + TABLE + ROW).splitlines())
            self.assertTrue(self.check(HEAD + block))
        for count in range(4):
            block = "\n".join(" " * count + line for line in (SECTION + TABLE + ROW).splitlines())
            self.assertEqual([], self.check(HEAD + block))

    def test_missing_duplicate_and_empty_formal_sections_fail(self):
        import re
        import validate_weekly_brief as gate
        content = self.report()
        for heading in gate.REQUIRED_SECTIONS:
            with self.subTest(heading=heading):
                pattern = r"(?ms)^" + re.escape(heading) + r"\n.*?(?=^## |\Z)"
                self.assertTrue(self.check(re.sub(pattern, "", content)))
                self.assertTrue(self.check(content + "\n" + heading + "\n重复正文。\n"))
        self.assertTrue(self.check(content.replace("合成结论。", "")))
        self.assertTrue(self.check(content.replace("合成结论。", "```\n伪正文\n```")))

    def test_closed_atx_sections_and_literal_title_boundary(self):
        import validate_weekly_brief as gate
        content = self.report()
        for heading in gate.REQUIRED_SECTIONS:
            self.assertEqual([], self.check(content.replace(heading, heading + " ##")))
        title = content.splitlines()[0]
        self.assertTrue(self.check(content.replace(title, title + " ###")))
        self.assertTrue(self.check("#\n" + content))

    def test_title_boundary_agrees_with_shared_archive_identity(self):
        import report_archive as archive
        content = self.report()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DHWB-20000109.md"
            for prefix in ("", " ", "  ", "   "):
                path.write_text(prefix + content, encoding="utf-8")
                self.assertEqual([], self.check(prefix + content))
                value = archive.identity(path, "hit-weekly-brief", validate=True,
                                         custom_filename=False, custom_period=False, target_name=path.name)
                self.assertEqual("hit-weekly-brief", value["skill"])
            title = content.splitlines()[0]
            invalid = content.replace(title, title + " ###")
            path.write_text(invalid, encoding="utf-8")
            self.assertTrue(self.check(invalid))
            with self.assertRaises(archive.Blocked):
                archive.identity(path, "hit-weekly-brief", validate=True,
                                 custom_filename=False, custom_period=False, target_name=path.name)

    def test_empty_subheadings_do_not_supply_body(self):
        for heading in ("###", "###  ", "  ###", "####", "######", "### ###", "###\t###"):
            self.assertTrue(self.check(self.report().replace("合成结论。", heading)))

    def test_empty_h2_ends_body_and_event_section(self):
        self.assertTrue(self.check(self.report().replace("合成结论。", "##\n伪正文")))
        content = self.report().replace("## 关键事件与来源\n", "## 关键事件与来源\n##\n")
        errors = self.check(content)
        self.assertTrue(any("no dated event" in error for error in errors), errors)

    def test_region_and_audience_must_be_header_fields(self):
        import re
        for field in ("地区", "受众"):
            content = re.sub("^" + field + "：.*\\n", "", self.report(), flags=re.M)
            self.assertTrue(self.check(content))
            self.assertTrue(self.check(content + "\n" + field + "：正文中的伪字段\n"))


if __name__ == "__main__":
    unittest.main()
