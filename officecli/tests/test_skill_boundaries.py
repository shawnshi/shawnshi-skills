import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SkillInstallAuthorizationTests(unittest.TestCase):
    def test_missing_cli_reports_requirement_before_remote_commands(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        install = text.split("## Install", 1)[1].split("## ", 1)[0]
        for rule in ["report the missing CLI", "stop the CLI-dependent document operation", "not permission to install software or execute remote code", "current explicit authorization covers installation on this target", "execution of the selected remote installer", "without running an installer", "Do not request approval again"]:
            self.assertIn(rule, install)
            self.assertLess(install.index(rule), install.index("curl -fsSL"))
        self.assertIn("irm https://", install)

    def test_provenance_distinguishes_local_revision(self):
        text = (ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
        self.assertIn("459b1a473faf33f2f52e697ac6d265a3f67b176a", text)
        self.assertIn("Recorded pre-revision local Git blob", text)
        self.assertIn("no longer claimed byte-equivalent", text)
        self.assertIn("not re-fetched or independently verified", text)

if __name__ == "__main__":
    unittest.main()
