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
SCRIPT = ROOT / "scripts/validate_lectures_scout.py"


class RuntimeContractTests(unittest.TestCase):
    def test_describe_contract_is_read_only_json(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--describe-contract"],
                                    cwd=td, capture_output=True, encoding="utf-8", timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("hit-lectures-scout", value["skill"])
            self.assertEqual(1, value["schema_version"])
            self.assertTrue(value["read_only"])
            self.assertTrue(value["tables"])
            self.assertEqual([], list(Path(td).iterdir()))

    def test_describe_cannot_mix_with_validation_arguments(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--describe-contract", "--file", "missing.md"],
                                capture_output=True, timeout=10)
        self.assertEqual(2, result.returncode)


    def test_legal_atx_titles_and_header_boundaries(self):
        from test_validate_lectures_scout import CONTENT, ValidateLecturesScoutTests
        fixture = ValidateLecturesScoutTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        check = fixture.check
        title = CONTENT.splitlines()[0]
        for count in range(4):
            self.assertEqual([], check(CONTENT.replace(title, " " * count + title)))
        self.assertTrue(check(CONTENT.replace(title, "    " + title)))
        self.assertTrue(check(CONTENT.replace(title, title + " ###")))
        self.assertTrue(check("#\n" + CONTENT))
        for level in range(3, 7):
            content = CONTENT.replace("命名依据：explicit", "#" * level + " 说明\n命名依据：explicit")
            self.assertEqual([], check(content))

    def test_title_boundary_agrees_with_shared_archive_identity(self):
        import report_archive as archive
        from test_validate_lectures_scout import CONTENT
        from datetime import date, datetime
        import validate_lectures_scout as gate
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DHLS-20000109.md"
            args = dict(period_start=date(2000, 1, 3), period_end=date(2000, 1, 9),
                        issue_date=date(2000, 1, 9), cutoff=datetime.fromisoformat("2000-01-10T00:00:00+08:00"))
            for prefix in ("", " ", "  ", "   "):
                path.write_text(prefix + CONTENT, encoding="utf-8")
                self.assertEqual([], gate.validate_report(path, **args))
                value = archive.identity(path, "hit-lectures-scout", validate=True,
                                         custom_filename=False, custom_period=False, target_name=path.name)
                self.assertEqual("hit-lectures-scout", value["skill"])
            title = CONTENT.splitlines()[0]
            path.write_text(CONTENT.replace(title, title + " ###"), encoding="utf-8")
            self.assertTrue(gate.validate_report(path, **args))
            with self.assertRaises(archive.Blocked):
                archive.identity(path, "hit-lectures-scout", validate=True,
                                 custom_filename=False, custom_period=False, target_name=path.name)


if __name__ == "__main__":
    unittest.main()
