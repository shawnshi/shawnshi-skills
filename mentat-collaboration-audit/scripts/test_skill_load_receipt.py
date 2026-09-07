import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
            normalized_path = receipt_module.os.path.normcase(str(skill.resolve())).replace(
                "\\", "/"
            )
            self.assertEqual(
                receipt["skill_path_sha256"],
                hashlib.sha256(normalized_path.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn("skill_path", receipt)
            self.assertNotIn(str(Path(tmp).resolve()), json.dumps(receipt))
            self.assertGreater(receipt["skill_tokens"], 0)
            self.assertEqual(receipt["tokenizer"], "cl100k_base")

    def test_missing_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                receipt_module.build_receipt(skill, "", "root", "epoch-1")

    def test_tokenizer_unavailable_emits_hash_only_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            with mock.patch.object(
                receipt_module.tiktoken,
                "get_encoding",
                side_effect=RuntimeError("offline cache miss"),
            ):
                receipt = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")

            self.assertEqual(receipt["event_type"], "skill_load")
            self.assertRegex(receipt["skill_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("skill_tokens", receipt)
            self.assertNotIn("tokenizer", receipt)
            self.assertEqual(receipt["token_measurement_status"], "error")
            self.assertEqual(receipt["token_measurement_error_type"], "RuntimeError")

    def test_append_is_idempotent_for_replayed_event_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            output = root / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            receipt = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")

            self.assertTrue(receipt_module.append_receipt(output, receipt))
            self.assertFalse(receipt_module.append_receipt(output, receipt))
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(records), 1)

    def test_distinct_occurrences_of_same_business_key_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            output = Path(tmp) / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            first = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")
            second = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")
            self.assertNotEqual(first["event_id"], second["event_id"])
            self.assertEqual(first["event_identity"], "occurrence")
            self.assertEqual(first["token_measurement_basis"], "skill_text")
            self.assertTrue(receipt_module.append_receipt(output, first))
            self.assertTrue(receipt_module.append_receipt(output, second))
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 2)

    def test_explicit_replay_and_conflict_preserve_existing_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            output = Path(tmp) / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            first = receipt_module.build_receipt(skill, "task-1", "root", "1", event_id="stable-1", candidate_event_id="candidate-1")
            replay = receipt_module.build_receipt(skill, "task-1", "root", "1", event_id="stable-1", candidate_event_id="candidate-1")
            self.assertTrue(receipt_module.append_receipt(output, first))
            before = output.read_bytes()
            self.assertFalse(receipt_module.append_receipt(output, replay))
            for conflicting in (dict(replay, skill_tokens=replay["skill_tokens"] + 1),
                                dict(replay, outcome=None), dict(replay, skill_tokens=True)):
                with self.assertRaisesRegex(ValueError, "conflicts"):
                    receipt_module.append_receipt(output, conflicting)
            self.assertEqual(output.read_bytes(), before)
            self.assertFalse(output.with_suffix(".jsonl.lock").exists())

    def test_legacy_append_remains_readable_without_fabricating_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            output = Path(tmp) / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            legacy = receipt_module.build_receipt(skill, "task-1", "root", "1")
            legacy.pop("event_identity")
            legacy.pop("event_id")
            self.assertTrue(receipt_module.append_receipt(output, legacy))
            self.assertFalse(receipt_module.append_receipt(output, legacy))
            current = receipt_module.build_receipt(skill, "task-1", "root", "1")
            self.assertTrue(receipt_module.append_receipt(output, current))
            self.assertNotIn("event_id", json.loads(output.read_text(encoding="utf-8").splitlines()[0]))

    def test_changed_epoch_is_a_distinct_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            output = root / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            first = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")
            second = receipt_module.build_receipt(skill, "task-1", "root", "epoch-2")

            self.assertTrue(receipt_module.append_receipt(output, first))
            self.assertTrue(receipt_module.append_receipt(output, second))
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 2)

    def test_replay_still_checks_the_entire_existing_receipt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "SKILL.md"
            output = Path(tmp) / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            receipt = receipt_module.build_receipt(skill, "task-1", "root", "1", event_id="stable")
            receipt_module.append_receipt(output, receipt)
            with output.open("a", encoding="utf-8") as handle:
                handle.write("{invalid}\n")
            before = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "invalid receipt JSON"):
                receipt_module.append_receipt(output, receipt)
            self.assertEqual(output.read_bytes(), before)
            self.assertFalse(output.with_suffix(".jsonl.lock").exists())

    def test_malformed_existing_receipt_fails_closed_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            output = root / "receipts.jsonl"
            skill.write_text("---\nname: sample\n---\nbody\n", encoding="utf-8")
            output.write_text("{not-json}\n", encoding="utf-8")
            receipt = receipt_module.build_receipt(skill, "task-1", "root", "epoch-1")

            with self.assertRaises(ValueError):
                receipt_module.append_receipt(output, receipt)

            self.assertFalse(output.with_name(output.name + ".lock").exists())


if __name__ == "__main__":
    unittest.main()
