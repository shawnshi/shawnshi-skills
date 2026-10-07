"""Regression guard (CA-1): scripts must load without an external PYTHONPATH.

``tests/common.load_module`` executes scripts such as ``build_candidate.py`` and
``draft_fields.py``. Those scripts use bare sibling imports (``import
init_workspace as init``), which only resolve because ``python <script>`` puts
``scripts/`` on ``sys.path[0]``. Any runner that imports the suite instead of
invoking a script directly (pytest, a CI collector) must therefore not depend on
that implicit coupling.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest

from tests.common import SKILL_ROOT

# Runs in a fresh interpreter with the skill's parent directory as cwd, so no
# script directory is on sys.path unless tests.common registers it itself.
_PROBE = """
import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("probe_common", root / "tests" / "common.py")
module = importlib.util.module_from_spec(spec)
sys.modules["probe_common"] = module
spec.loader.exec_module(module)
module.load_module("probe_builder", root / "scripts" / "build_candidate.py")
module.load_module("probe_draft", root / "scripts" / "draft_fields.py")
print("IMPORT_OK")
"""


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class ImportPathRegistrationTests(unittest.TestCase):
    def test_common_registers_scripts_dir_without_external_pythonpath(self):
        proc = subprocess.run(
            [sys.executable, "-B", "-c", _PROBE, str(SKILL_ROOT)],
            cwd=str(SKILL_ROOT.parent),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=60,
            env=_clean_env(),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("IMPORT_OK", proc.stdout)

    @unittest.skipUnless(importlib.util.find_spec("pytest") is not None, "pytest not installed")
    def test_pytest_collects_suite_from_parent_directory(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                str(SKILL_ROOT / "tests"),
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=str(SKILL_ROOT.parent),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=120,
            env=_clean_env(),
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            proc.stdout[-2000:] + proc.stderr[-2000:],
        )


if __name__ == "__main__":
    unittest.main()
