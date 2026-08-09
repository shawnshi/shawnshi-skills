import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
INTEGRITY_SCRIPT = Path(__file__).with_name("wheelhouse_integrity.py")
ENVIRONMENT_GATE = Path(__file__).with_name("installed_environment_gate.py")
PUBLISH_SCRIPT = Path(__file__).with_name("publish_directory_no_replace.py")


class InstallerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(INTEGRITY_SCRIPT, self.root / "scripts" / INTEGRITY_SCRIPT.name)
        shutil.copy2(ENVIRONMENT_GATE, self.root / "scripts" / ENVIRONMENT_GATE.name)
        shutil.copy2(PUBLISH_SCRIPT, self.root / "scripts" / PUBLISH_SCRIPT.name)
        self.lock = self.root / "requirements.lock.txt"
        self.lock.write_text("pia-installer-fixture==1.0\n", encoding="utf-8")
        self.wheelhouse = self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        self._create_fixture_wheel()
        self._create_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def _create_fixture_wheel(self):
        wheel = self.wheelhouse / "pia_installer_fixture-1.0-py3-none-any.whl"
        module = b"VALUE = 'offline-only'\n"
        metadata = b"Metadata-Version: 2.1\nName: pia-installer-fixture\nVersion: 1.0\n"
        wheel_metadata = (
            b"Wheel-Version: 1.0\nGenerator: pia-test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        )
        records = {
            "pia_installer_fixture/__init__.py": module,
            "pia_installer_fixture-1.0.dist-info/METADATA": metadata,
            "pia_installer_fixture-1.0.dist-info/WHEEL": wheel_metadata,
        }
        record_lines = [
            f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b'=').decode()},{len(payload)}"
            for name, payload in records.items()
        ]
        record_name = "pia_installer_fixture-1.0.dist-info/RECORD"
        records[record_name] = ("\n".join(record_lines) + f"\n{record_name},,\n").encode()
        with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in records.items():
                archive.writestr(name, payload)

    def _create_manifest(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(self.root / "scripts" / INTEGRITY_SCRIPT.name),
                "create",
                "--wheelhouse",
                str(self.wheelhouse),
                "--requirements-lock",
                str(self.lock),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def _powershell(self):
        return shutil.which("pwsh") or shutil.which("powershell")

    def _copy_powershell_installer(self):
        destination = self.root / "install.ps1"
        shutil.copy2(SKILL_ROOT / "install.ps1", destination)
        return destination

    def _bash(self):
        discovered = shutil.which("bash")
        if discovered:
            return discovered
        if os.name == "nt":
            for candidate in (
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/usr/bin/bash.exe",
            ):
                if candidate.is_file():
                    return str(candidate)
        return None

    def _copy_shell_installer(self):
        destination = self.root / "install.sh"
        shutil.copy2(SKILL_ROOT / "install.sh", destination)
        return destination

    def test_powershell_refuses_online_mode_before_creating_target(self):
        executable = self._powershell()
        if executable is None:
            self.skipTest("PowerShell is unavailable")
        installer = self._copy_powershell_installer()
        target = self.root / "must-not-exist"
        result = subprocess.run(
            [executable, "-NoProfile", "-File", str(installer), "-VenvPath", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Online installation is disabled", result.stderr)
        self.assertFalse(target.exists())

    def test_powershell_offline_install_uses_verified_wheelhouse(self):
        executable = self._powershell()
        if executable is None:
            self.skipTest("PowerShell is unavailable")
        installer = self._copy_powershell_installer()
        target = self.root / "offline-venv"
        environment = os.environ.copy()
        environment["PIP_INDEX_URL"] = "http://127.0.0.1:9/forbidden"
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-File",
                str(installer),
                "-Offline",
                "-Wheelhouse",
                str(self.wheelhouse),
                "-VenvPath",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        installed_python = target / "Scripts" / "python.exe"
        self.assertTrue(installed_python.is_file())
        probe = subprocess.run(
            [str(installed_python), "-I", "-c", "import pia_installer_fixture"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_powershell_refuses_to_modify_existing_target(self):
        executable = self._powershell()
        if executable is None:
            self.skipTest("PowerShell is unavailable")
        installer = self._copy_powershell_installer()
        target = self.root / "existing-venv"
        target.mkdir()
        sentinel = target / "sentinel.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-File",
                str(installer),
                "-Offline",
                "-Wheelhouse",
                str(self.wheelhouse),
                "-VenvPath",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_failed_post_install_gate_does_not_publish_partial_environment(self):
        executable = self._powershell()
        if executable is None:
            self.skipTest("PowerShell is unavailable")
        installer = self._copy_powershell_installer()
        target = self.root / "must-not-publish"
        (self.root / "scripts" / ENVIRONMENT_GATE.name).write_text(
            "raise SystemExit(1)\n", encoding="utf-8"
        )
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-File",
                str(installer),
                "-VenvPath",
                str(target),
                "-Offline",
                "-Wheelhouse",
                str(self.wheelhouse),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PIP_INDEX_URL": "http://127.0.0.1:9/unreachable"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".pia-venv-staging-*")), [])

    def test_shell_refuses_online_mode_before_creating_target(self):
        executable = self._bash()
        if executable is None:
            self.skipTest("Bash is unavailable")
        installer = self._copy_shell_installer()
        target = self.root / "shell-must-not-exist"
        result = subprocess.run(
            [executable, str(installer), "--venv", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Online installation is disabled", result.stderr)
        self.assertFalse(target.exists())

    def test_shell_offline_install_uses_verified_wheelhouse(self):
        executable = self._bash()
        if executable is None:
            self.skipTest("Bash is unavailable")
        installer = self._copy_shell_installer()
        target = self.root / "shell-offline-venv"
        environment = os.environ.copy()
        environment["PIP_INDEX_URL"] = "http://127.0.0.1:9/forbidden"
        result = subprocess.run(
            [
                executable,
                str(installer),
                "--offline",
                "--wheelhouse",
                str(self.wheelhouse),
                "--venv",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        candidates = (target / "bin" / "python", target / "Scripts" / "python.exe")
        installed_python = next((path for path in candidates if path.is_file()), None)
        self.assertIsNotNone(installed_python)
        probe = subprocess.run(
            [str(installed_python), "-I", "-c", "import pia_installer_fixture"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_shell_failed_post_install_gate_does_not_publish_partial_environment(self):
        executable = self._bash()
        if executable is None:
            self.skipTest("Bash is unavailable")
        installer = self._copy_shell_installer()
        target = self.root / "shell-must-not-publish"
        (self.root / "scripts" / ENVIRONMENT_GATE.name).write_text(
            "raise SystemExit(1)\n", encoding="utf-8"
        )
        result = subprocess.run(
            [
                executable,
                str(installer),
                "--offline",
                "--wheelhouse",
                str(self.wheelhouse),
                "--venv",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PIP_INDEX_URL": "http://127.0.0.1:9/unreachable"},
            timeout=120,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".pia-venv-staging-*")), [])

    def test_installers_contain_no_online_pip_fallback(self):
        powershell = (SKILL_ROOT / "install.ps1").read_text(encoding="utf-8")
        shell = (SKILL_ROOT / "install.sh").read_text(encoding="utf-8")
        for name, content in (("PowerShell", powershell), ("Shell", shell)):
            with self.subTest(installer=name):
                self.assertIn("Online installation is disabled", content)
                self.assertIn("--require-hashes", content)
                self.assertIn("--no-index", content)
                self.assertIn("--disable-pip-version-check", content)
                self.assertIn("--isolated", content)
                self.assertIn("--find-links", content)
        self.assertNotIn("@('-m', 'pip', 'install', '--requirement', $requirements)", powershell)
        self.assertNotIn('PIP_ARGS=(-m pip install --requirement "$REQUIREMENTS")', shell)


if __name__ == "__main__":
    unittest.main()
