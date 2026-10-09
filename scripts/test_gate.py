import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("sh"), "POSIX shell unavailable")
class GateEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skills gate ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copy2(Path(__file__).with_name("gate.sh"), scripts / "gate.sh")
        binary = self.root / "bin"
        binary.mkdir()
        python = binary / "python"
        python.write_text(
            "#!/usr/bin/env sh\n"
            'case "$*" in\n'
            '  *"import pytest"*) [ "${NO_PYTEST:-0}" = 0 ] || exit 93; exit 0 ;;\n'
            '  *"-m pytest"*) echo TESTS_REQUESTED; exit 0 ;;\n'
            '  *"scripts/validate_openai_yaml.py"*)\n'
            '    if [ "${BAD_METADATA:-0}" = 1 ]; then echo "fixture metadata failure"; exit 1; fi\n'
            '    echo \'{"checked":0,"failures":0,"issues":[],"warnings":[]}\'; exit 0 ;;\n'
            "esac\n"
            f"exec {shlex.quote(sys.executable.replace(chr(92), '/'))} \"$@\"\n",
            encoding="utf-8",
        )
        pwsh = binary / "pwsh"
        pwsh.write_text(
            "#!/usr/bin/env sh\n"
            'echo "PW_ARGS:$*"\n'
            'case "$*" in\n'
            '  *generate_resource_manifests.ps1*)\n'
            '    case "$*" in *-Check*) ;; *) echo REFRESH_REQUESTED ;; esac ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        pwsh.chmod(0o755)
        self.env = dict(os.environ)
        self.env["PATH"] = str(binary) + os.pathsep + self.env["PATH"]

    def run_gate(self, *args, **env):
        return subprocess.run(
            [shutil.which("sh"), str(self.root / "scripts" / "gate.sh"), *args],
            env={**self.env, **env}, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )

    def test_default_checks_do_not_test_refresh_or_write(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = self.run_gate("example-skill", NO_PYTEST="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("TESTS_REQUESTED", result.stdout)
        self.assertNotIn("REFRESH_REQUESTED", result.stdout)
        self.assertIn('"failures":0', result.stdout)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_tests_and_refresh_are_explicit(self):
        result = self.run_gate("--tests", "--refresh-manifests", "example-skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TESTS_REQUESTED", result.stdout)
        self.assertIn("REFRESH_REQUESTED", result.stdout)
        self.assertIn("-IncludeSkills example-skill", result.stdout)

    def test_missing_pytest_blocks_only_explicit_tests(self):
        result = self.run_gate("--tests", NO_PYTEST="1")
        self.assertEqual(result.returncode, 127)
        self.assertIn("--tests requires pytest", result.stderr)
        self.assertNotIn("PW_ARGS", result.stdout)

    def test_metadata_failure_preserves_diagnostic_and_stops(self):
        result = self.run_gate("example-skill", BAD_METADATA="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fixture metadata failure", result.stdout)
        self.assertNotIn("PW_ARGS", result.stdout)

    def test_unknown_option_is_not_treated_as_a_skill(self):
        result = self.run_gate("--not-an-option")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option", result.stderr)


if __name__ == "__main__":
    unittest.main()
