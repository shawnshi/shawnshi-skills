import importlib.util
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock


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

    def test_freezer_preserves_complete_lines_without_semantic_json_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "active.jsonl"
            output = root / "snapshot.jsonl"
            source.write_bytes(b'{"valid":1}\nnot-json\n{"partial":')

            receipt = freeze.freeze_jsonl(source, output)

            self.assertEqual(output.read_bytes(), b'{"valid":1}\nnot-json\n')
            self.assertEqual(receipt["records"], 2)
            self.assertTrue(receipt["trailing_partial_record_excluded"])

    def test_large_input_has_bounded_peak_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "large.jsonl"
            output = root / "snapshot.jsonl"
            row = b'{"n":1}\n'
            source.write_bytes(row * (2 * 1024 * 1024 // len(row)))

            tracemalloc.start()
            receipt = freeze.freeze_jsonl(source, output)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            self.assertEqual(receipt["frozen_bytes"], source.stat().st_size)
            self.assertLess(peak, 6 * 1024 * 1024)

    def test_receipt_publish_failure_rolls_back_snapshot_and_staging_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "active.jsonl"
            output = root / "snapshot.jsonl"
            receipt_path = root / "snapshot.receipt.json"
            source.write_text('{"n":1}\n', encoding="utf-8")
            real_link = freeze.os.link
            calls = 0

            def fail_receipt_publish(source_path, target_path):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected receipt publish failure")
                return real_link(source_path, target_path)

            with mock.patch.object(freeze.os, "link", side_effect=fail_receipt_publish):
                with self.assertRaises(OSError):
                    freeze.freeze_jsonl(source, output, receipt_path)

            self.assertFalse(output.exists())
            self.assertFalse(receipt_path.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
