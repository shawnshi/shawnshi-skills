import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("authority_gate.py")
SPEC = importlib.util.spec_from_file_location("authority_gate", MODULE_PATH)
if SPEC is None:
    raise RuntimeError("authority_gate module spec is unavailable")
authority_gate = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("authority_gate module loader is unavailable")
SPEC.loader.exec_module(authority_gate)


class AuthorityGateTests(unittest.TestCase):
    def _skill(self, path: Path, version: str = "11.0.0", extra: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: personal-diary-writer\nversion: {version}\n{extra}---\nbody\n",
            encoding="utf-8",
        )

    def _proxy(self, path: Path, authority: Path, digest: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            "name: personal-diary-writer\n"
            "description: Bound test proxy for diary writes.\n"
            "metadata:\n"
            "  version: 11.0.0-proxy\n"
            f"  authority_proxy_for: {authority.as_posix()}\n"
            "  authority_version: 11.0.0\n"
            f"  authority_sha256: {digest}\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )

    @staticmethod
    def _absolute(path: Path) -> dict:
        return {"base": "absolute", "path": str(path)}

    def test_bound_authority_emits_complete_skill_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority = root / "authority" / "SKILL.md"
            proxy = root / "proxy" / "SKILL.md"
            self._skill(authority)
            digest = authority_gate.sha256_file(authority)
            self._proxy(proxy, authority, digest)
            config = {
                "schema_version": 2,
                "skill_name": "personal-diary-writer",
                "authority_locator": self._absolute(authority),
                "authority_version": "11.0.0",
                "authority_sha256": digest,
                "candidate_locators": [
                    self._absolute(authority),
                    self._absolute(proxy),
                ],
                "allowed_proxy_locators": [self._absolute(proxy)],
            }
            with patch.object(authority_gate, "tiktoken", None):
                result = authority_gate.verify(config, "task-1", "root", "epoch-1")
            self.assertTrue(result["ok"])
            event = result["skill_load"]
            self.assertEqual(event["context_epoch"], "epoch-1")
            self.assertEqual(event["actor_type"], "root")
            self.assertEqual(event["skill_sha256"], digest)
            self.assertIsNone(event["skill_tokens"])
            self.assertIsNone(event["tokenizer"])
            self.assertGreater(event["skill_characters"], 0)

    def test_text_hash_is_newline_invariant(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_bytes(b"---\nname: example\n---\nbody\n")
            lf_hash = authority_gate.sha256_file(skill)
            skill.write_bytes(b"---\r\nname: example\r\n---\r\nbody\r\n")
            self.assertEqual(authority_gate.sha256_file(skill), lf_hash)

    def test_codex_root_actor_is_not_misclassified_as_subagent(self):
        self.assertEqual(authority_gate._actor_type("codex-root"), "root")
        self.assertEqual(authority_gate._actor_type("worker-1"), "subagent")

    def test_unbound_same_name_fork_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority = root / "authority" / "SKILL.md"
            fork = root / "fork" / "SKILL.md"
            self._skill(authority)
            self._skill(fork, version="1.0.0")
            config = {
                "schema_version": 2,
                "skill_name": "personal-diary-writer",
                "authority_locator": self._absolute(authority),
                "authority_version": "11.0.0",
                "authority_sha256": authority_gate.sha256_file(authority),
                "candidate_locators": [
                    self._absolute(authority),
                    self._absolute(fork),
                ],
                "allowed_proxy_locators": [],
            }
            result = authority_gate.verify(config, "task-2", "root", "epoch-1")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "UNBOUND_SKILL_FORK")

    def test_schema_v2_stale_proxy_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority = root / "authority" / "SKILL.md"
            proxy = root / "proxy" / "SKILL.md"
            self._skill(authority)
            digest = authority_gate.sha256_file(authority)
            self._proxy(proxy, authority, "0" * 64)
            config = {
                "schema_version": 2,
                "skill_name": "personal-diary-writer",
                "authority_locator": self._absolute(authority),
                "authority_version": "11.0.0",
                "authority_sha256": digest,
                "candidate_locators": [self._absolute(authority), self._absolute(proxy)],
                "allowed_proxy_locators": [self._absolute(proxy)],
            }
            result = authority_gate.verify(config, "task-4", "root", "epoch-1")
            self.assertEqual(result["error_code"], "PROXY_HASH_MISMATCH")

    def test_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            authority = Path(tmp) / "SKILL.md"
            self._skill(authority)
            config = {
                "schema_version": 2,
                "skill_name": "personal-diary-writer",
                "authority_locator": self._absolute(authority),
                "authority_version": "11.0.0",
                "authority_sha256": "0" * 64,
                "candidate_locators": [self._absolute(authority)],
                "allowed_proxy_locators": [],
            }
            result = authority_gate.verify(config, "task-3", "root", "epoch-1")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "AUTHORITY_HASH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
