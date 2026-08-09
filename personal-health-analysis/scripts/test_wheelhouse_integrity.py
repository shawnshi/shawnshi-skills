import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("wheelhouse_integrity.py")


class WheelhouseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wheelhouse = self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        self.artifact = self.wheelhouse / "example-1.0-py3-none-any.whl"
        self.artifact.write_bytes(b"synthetic-wheel")
        self.lock = self.root / "requirements.lock.txt"
        self.lock.write_text("example==1.0\n", encoding="utf-8")
        self.manifest = self.wheelhouse / "wheelhouse-manifest.json"

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, operation, *extra):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                operation,
                "--wheelhouse",
                str(self.wheelhouse),
                "--manifest",
                str(self.manifest),
                "--requirements-lock",
                str(self.lock),
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def generate(self, output):
        return self.run_cli("generate-hash-requirements", "--output", str(output))

    def create(self):
        result = self.run_cli("create")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def assert_failure(self, result, code):
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], code)

    def test_create_then_verify(self):
        self.create()
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["python_version"], f"{sys.version_info.major}.{sys.version_info.minor}")
        self.assertEqual(payload["platform"], sys.platform.lower())
        self.assertEqual(payload["machine"], (platform.machine() or "unknown").lower())
        self.assertEqual(len(payload["artifacts"]), 1)
        result = self.run_cli("verify")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tampered_artifact_fails(self):
        self.create()
        self.artifact.write_bytes(b"synthetic-wheel-tampered")
        self.assert_failure(self.run_cli("verify"), "artifact_size_mismatch")

    def test_sdist_is_rejected(self):
        sdist = self.wheelhouse / "example-1.0.tar.gz"
        sdist.write_bytes(b"synthetic-sdist")
        self.assert_failure(self.run_cli("create"), "unexpected_wheelhouse_entry")

    def test_generates_hash_requirements_from_verified_manifest(self):
        self.create()
        output = self.root / "requirements.hashed.txt"
        result = self.generate(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_hash = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.assertEqual(
            output.read_text(encoding="utf-8"),
            f"example==1.0 --hash=sha256:{expected_hash}\n",
        )
        self.assertEqual(json.loads(result.stdout)["requirements"], 1)
        self.assert_failure(self.generate(output), "output_exists")

    def test_generation_rechecks_artifact_hash(self):
        self.create()
        self.artifact.write_bytes(b"synthetic-WHEEL")
        output = self.root / "requirements.hashed.txt"
        self.assert_failure(self.generate(output), "artifact_hash_mismatch")
        self.assertFalse(output.exists())

    def test_lock_mapping_and_lines_fail_closed(self):
        extra = self.wheelhouse / "extra-1.0-py3-none-any.whl"
        extra.write_bytes(b"extra")
        self.assert_failure(self.run_cli("create"), "wheel_not_mapped_to_lock")
        extra.unlink()

        self.lock.write_text("example==1.0\nmissing==2.0\n", encoding="utf-8")
        self.assert_failure(self.run_cli("create"), "locked_distribution_missing_wheel")

        self.lock.write_text("example>=1.0\n", encoding="utf-8")
        self.assert_failure(self.run_cli("create"), "requirements_lock_line_invalid")

    def test_offline_installers_require_per_distribution_hashes(self):
        skill_root = SCRIPT.parent.parent
        installers = {
            "PowerShell": (skill_root / "install.ps1").read_text(encoding="utf-8"),
            "Shell": (skill_root / "install.sh").read_text(encoding="utf-8"),
        }
        required_tokens = (
            "generate-hash-requirements",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-index",
            "--find-links",
            "pip --isolated check",
        )
        for installer, content in installers.items():
            with self.subTest(installer=installer):
                for token in required_tokens:
                    self.assertIn(token, content)
                self.assertGreaterEqual(content.count("verify"), 2)

    def test_extra_and_missing_artifacts_fail(self):
        self.create()
        extra = self.wheelhouse / "extra-1.0-py3-none-any.whl"
        extra.write_bytes(b"extra")
        self.assert_failure(self.run_cli("verify"), "wheelhouse_artifact_set_mismatch")
        extra.unlink()
        self.artifact.unlink()
        self.assert_failure(self.run_cli("verify"), "wheelhouse_empty")

    def test_create_refuses_to_overwrite_manifest_by_default(self):
        self.create()
        original = self.manifest.read_bytes()
        self.assert_failure(self.run_cli("create"), "manifest_exists")
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_runtime_lock_and_manifest_validation_fail_closed(self):
        cases = (
            ("python_version", "0.0", "manifest_python_version_mismatch"),
            ("platform", "not-this-platform", "manifest_platform_mismatch"),
            ("machine", "not-this-machine", "manifest_machine_mismatch"),
        )
        for key, value, expected_code in cases:
            with self.subTest(key=key):
                self.manifest.unlink(missing_ok=True)
                self.create()
                payload = json.loads(self.manifest.read_text(encoding="utf-8"))
                payload[key] = value
                self.manifest.write_text(json.dumps(payload), encoding="utf-8")
                self.assert_failure(self.run_cli("verify"), expected_code)

        self.manifest.unlink(missing_ok=True)
        self.create()
        self.lock.write_text("example==2.0\n", encoding="utf-8")
        self.assert_failure(self.run_cli("verify"), "requirements_lock_hash_mismatch")

        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["requirements_lock"]["sha256"] = "not-a-sha256"
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        self.assert_failure(self.run_cli("verify"), "manifest_lock_hash_invalid")


if __name__ == "__main__":
    unittest.main()
