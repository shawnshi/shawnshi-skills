import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("runtime_authority.py")
SPEC = importlib.util.spec_from_file_location("runtime_authority", MODULE_PATH)
authority = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(authority)


class RuntimeAuthorityTests(unittest.TestCase):
    def test_production_binding_is_current_and_proxy_only(self):
        config_path = MODULE_PATH.parent.parent / "runtime-authority.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        proxy = Path(__file__).resolve().parents[3] / "gemini-config-skills" / "personal-health-analysis" / "SKILL.md"
        canonical = MODULE_PATH.parent.parent / "SKILL.md"
        canonical_sha = authority._sha256(canonical)
        proxy_meta = {
            "name": "personal-health-analysis",
            "authority_proxy_for": str(canonical),
            "authority_version": "11.6.0",
            "authority_sha256": canonical_sha,
        }
        with (
            mock.patch.object(authority, "_locator", side_effect=[canonical, proxy, Path("missing-proxy")]),
            mock.patch.object(authority, "_frontmatter", side_effect=[{"name": "personal-health-analysis", "version": "11.6.0"}, proxy_meta]),
        ):
            result = authority.verify(config)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority_version"], "11.6.0")
        self.assertIn("scripts/garmin_auto_sync.py", result["entrypoints"])
        self.assertRegex(result["task_binding"]["arguments_sha256"], r"^[0-9a-f]{64}$")

    def test_hash_drift_fails_closed(self):
        skill = MODULE_PATH.parent.parent / "SKILL.md"
        config = {
            "schema_version": 1,
            "skill_name": "personal-health-analysis",
            "authority_version": "11.6.0",
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
