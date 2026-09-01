import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("runtime_authority.py")
SPEC = importlib.util.spec_from_file_location("runtime_authority", MODULE_PATH)
if SPEC is None:
    raise RuntimeError("runtime_authority module spec is unavailable")
authority = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("runtime_authority module loader is unavailable")
SPEC.loader.exec_module(authority)


class RuntimeAuthorityTests(unittest.TestCase):
    def test_production_binding_is_current_and_portable(self):
        config_path = MODULE_PATH.parent.parent / "runtime-authority.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            config["authority_locator"],
            {"base": "skill_root", "segments": ["SKILL.md"]},
        )
        self.assertEqual(config["proxy_locators"], [])

        result = authority.verify(config)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority_version"], "11.6.1")
        self.assertIn("scripts/garmin_auto_sync.py", result["entrypoints"])
        self.assertNotIn("task_binding", result)

    def test_text_hash_is_newline_invariant(self):
        skill = MODULE_PATH.parent / "newline-fixture.tmp"
        self.addCleanup(skill.unlink, missing_ok=True)
        skill.write_bytes(b"alpha\nbeta\n")
        lf_hash = authority._sha256(skill)
        skill.write_bytes(b"alpha\r\nbeta\r\n")
        self.assertEqual(authority._sha256(skill), lf_hash)

    def test_hash_drift_fails_closed(self):
        skill = MODULE_PATH.parent.parent / "SKILL.md"
        config = {
            "schema_version": 1,
            "skill_name": "personal-health-analysis",
            "authority_version": "11.6.1",
            "authority_locator": {"base": "user_home", "segments": ["unused"]},
            "authority_sha256": "0" * 64,
            "proxy_locators": [],
            "entrypoint_sha256": {},
        }
        with mock.patch.object(authority, "_locator", return_value=skill):
            result = authority.verify(config)
        self.assertEqual(result["error_code"], "AUTHORITY_HASH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
