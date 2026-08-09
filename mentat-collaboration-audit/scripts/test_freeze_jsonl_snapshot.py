import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("freeze_jsonl_snapshot.py")
SPEC = importlib.util.spec_from_file_location("freeze_jsonl_snapshot", MODULE_PATH)
freeze = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(freeze)


class FreezeSnapshotTests(unittest.TestCase):
    def test_freezes_only_complete_jsonl_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "active.jsonl"
            output = root / "scratch" / "snapshot.jsonl"
            source.write_bytes(b'{"n":1}\n{"n":2}\n{"partial":')
            receipt = freeze.freeze_jsonl(source, output)
            self.assertEqual(output.read_bytes(), b'{"n":1}\n{"n":2}\n')
            self.assertEqual(receipt["records"], 2)
            self.assertTrue(receipt["trailing_partial_record_excluded"])
            self.assertEqual(receipt["frozen_bytes"], len(output.read_bytes()))
            self.assertRegex(receipt["snapshot_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("frozen_at", receipt)

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "active.jsonl"
            output = root / "snapshot.jsonl"
            source.write_text('{"n":1}\n', encoding="utf-8")
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                freeze.freeze_jsonl(source, output)


if __name__ == "__main__":
    unittest.main()
