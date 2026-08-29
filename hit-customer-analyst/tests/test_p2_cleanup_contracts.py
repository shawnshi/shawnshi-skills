from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.common import SKILL_ROOT


SCRIPTS = SKILL_ROOT / "scripts"
ASSETS = SKILL_ROOT / "assets"
VALIDATION_CASES = SKILL_ROOT / "references" / "validation-cases.md"
LEGACY_ASSET_PATTERN = (
    r"^(?:owner|version):|\b(?:review_required|not_connected|(?:I|L|N)-E[0-9]{3})\b"
)


def run_python(script: str, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / script), *args],
        cwd=SKILL_ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def run_release_scan(target: Path) -> subprocess.CompletedProcess[str]:
    shell = f"""
legacy_asset_scan_rc=0
rg -n '{LEGACY_ASSET_PATTERN}' "$1" || legacy_asset_scan_rc=$?
if [ "$legacy_asset_scan_rc" -eq 0 ]; then
  exit 1
elif [ "$legacy_asset_scan_rc" -ne 1 ]; then
  exit "$legacy_asset_scan_rc"
fi
"""
    return subprocess.run(
        ["bash", "-c", shell, "release-asset-scan", str(target)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class P2CliHelpContracts(unittest.TestCase):
    def test_intake_help_is_v3_and_file_only_across_clis(self):
        cases = (
            ("preflight_intake.py", ("--help",)),
            ("init_workspace.py", ("--help",)),
            ("research_plan.py", ("plan", "--help")),
            ("build_candidate.py", ("--help",)),
            ("commit_run.py", ("--help",)),
            ("migrate_workspace.py", ("--help",)),
        )
        for script, args in cases:
            with self.subTest(script=script):
                result = run_python(script, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("intake v3普通文件", result.stdout)
                self.assertNotIn("v2 intake", result.stdout)
                self.assertNotIn("用-从stdin读取", result.stdout)

    def test_preflight_cli_rejects_stdin_before_parsing_payload(self):
        result = run_python("preflight_intake.py", "-", input_text="{}\n")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "invalid")
        self.assertIn("不能从stdin执行", payload["error"])


class P2ReleaseScanContracts(unittest.TestCase):
    def test_release_scan_uses_exact_tokens_and_distinguishes_rg_statuses(self):
        validation_text = VALIDATION_CASES.read_text(encoding="utf-8")
        self.assertIn(LEGACY_ASSET_PATTERN, validation_text)
        self.assertIn('legacy_asset_scan_rc" -ne 1', validation_text)
        self.assertEqual(run_release_scan(ASSETS).returncode, 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample = root / "tokens.md"
            sample.write_text(
                "internal_review_required\n"
                "research_fact_review_required\n"
                "not_connectedness\n"
                "I-E001x\n"
                "review_required\n"
                "not_connected\n"
                "I-E001\n"
                "L-E999\n"
                "N-E123\n"
                "owner: legacy\n"
                "version: 1\n",
                encoding="utf-8",
            )
            raw_match = subprocess.run(
                ["rg", "-n", LEGACY_ASSET_PATTERN, str(sample)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(raw_match.returncode, 0)
            self.assertNotIn("internal_review_required", raw_match.stdout)
            self.assertNotIn("research_fact_review_required", raw_match.stdout)
            self.assertNotIn("not_connectedness", raw_match.stdout)
            self.assertNotIn("I-E001x", raw_match.stdout)
            for token in ("review_required", "not_connected", "I-E001", "L-E999", "N-E123", "owner:", "version:"):
                self.assertIn(token, raw_match.stdout)
            self.assertEqual(run_release_scan(sample).returncode, 1)
            self.assertGreater(run_release_scan(root / "missing").returncode, 1)


if __name__ == "__main__":
    unittest.main()
