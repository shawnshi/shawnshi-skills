import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import installed_environment_gate as gate


def distribution(name, version):
    return types.SimpleNamespace(metadata={"Name": name}, version=version)


class InstalledEnvironmentGateTests(unittest.TestCase):
    def test_exact_lock_plus_pip_passes(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "requirements.lock.txt"
            lock.write_text("Example_Pkg==1.2.3\n", encoding="utf-8")
            with patch.object(
                gate.metadata,
                "distributions",
                return_value=[distribution("example-pkg", "1.2.3"), distribution("pip", "26.0")],
            ):
                result = gate.verify_installed(lock)
        self.assertTrue(result["ok"])

    def test_extra_missing_or_wrong_version_fails(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "requirements.lock.txt"
            lock.write_text("expected==1.0\n", encoding="utf-8")
            cases = (
                [distribution("expected", "1.0"), distribution("extra", "1.0")],
                [distribution("pip", "26.0")],
                [distribution("expected", "2.0")],
            )
            for installed in cases:
                with self.subTest(installed=installed), patch.object(
                    gate.metadata, "distributions", return_value=installed
                ):
                    with self.assertRaisesRegex(ValueError, "installed_environment_lock_mismatch"):
                        gate.verify_installed(lock)


if __name__ == "__main__":
    unittest.main()
