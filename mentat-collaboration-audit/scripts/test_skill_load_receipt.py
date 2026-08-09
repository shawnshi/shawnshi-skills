import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("skill_load_receipt.py")
SPEC = importlib.util.spec_from_file_location("skill_load_receipt", MODULE_PATH)
receipt_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(receipt_module)


class SkillLoadReceiptTests(unittest.TestCase):
    def test_receipt_has_recomputable_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text(
                "---\nname: sample-skill\nversion: 2.1.0\n---\n# Sample\n",
                encoding="utf-8",
            )
            receipt = receipt_module.build_receipt(skill, "task-1", "root", "epoch-2")
            self.assertEqual(receipt["event_type"], "skill_load")
            self.assertEqual(receipt["context_epoch"], "epoch-2")
            self.assertEqual(receipt["skill_name"], "sample-skill")
            self.assertEqual(receipt["skill_version"], "2.1.0")
            self.assertRegex(receipt["skill_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(receipt["skill_tokens"], 0)
            self.assertEqual(receipt["tokenizer"], "cl100k_base")

    def test_missing_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                receipt_module.build_receipt(skill, "", "root", "epoch-1")


if __name__ == "__main__":
    unittest.main()
