import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import advice_journal  # noqa: E402
import broker_sync  # noqa: E402
import management_claim_tracker  # noqa: E402

TEST_TMPDIR = os.environ.get("PIA_TEST_TMPDIR")


class AtomicPersistenceTests(unittest.TestCase):
    def test_advice_journal_keeps_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMPDIR) as tmpdir:
            destination = Path(tmpdir) / "journal.jsonl"
            destination.write_text('{"state":"old"}\n', encoding="utf-8")

            with (
                patch.object(
                    advice_journal.os,
                    "replace",
                    side_effect=OSError("simulated replace failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated replace failure"),
            ):
                advice_journal._atomic_write_text(
                    destination, '{"state":"new"}\n'
                )

            self.assertEqual(
                destination.read_text(encoding="utf-8"), '{"state":"old"}\n'
            )
            self.assertEqual(list(destination.parent.glob(".journal.jsonl.*.tmp")), [])

    def test_broker_snapshot_keeps_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMPDIR) as tmpdir:
            destination = Path(tmpdir) / "positions.json"
            original = {"base_currency": "USD", "positions": []}
            destination.write_text(json.dumps(original), encoding="utf-8")

            with (
                patch.object(
                    broker_sync.os,
                    "replace",
                    side_effect=OSError("simulated replace failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated replace failure"),
            ):
                broker_sync.save_json(destination, {"positions": [{"symbol": "AAPL"}]})

            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), original)
            self.assertEqual(list(destination.parent.glob(".positions.json.*.tmp")), [])

    def test_claim_tracker_keeps_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMPDIR) as tmpdir:
            destination = Path(tmpdir) / "claims.json"
            destination.write_text('{"state":"old"}\n', encoding="utf-8")

            with (
                patch.object(
                    management_claim_tracker.os,
                    "replace",
                    side_effect=OSError("simulated replace failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated replace failure"),
            ):
                management_claim_tracker._atomic_write_text(
                    destination, '{"state":"new"}\n'
                )

            self.assertEqual(
                destination.read_text(encoding="utf-8"), '{"state":"old"}\n'
            )
            self.assertEqual(list(destination.parent.glob(".claims.json.*.tmp")), [])


class JournalLockTests(unittest.TestCase):
    def test_second_writer_times_out_while_journal_is_locked(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMPDIR) as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            observed = []

            def contend():
                try:
                    with advice_journal._journal_lock(journal, timeout_seconds=0.1):
                        observed.append("acquired")
                except TimeoutError:
                    observed.append("timed_out")

            with advice_journal._journal_lock(journal):
                contender = threading.Thread(target=contend)
                contender.start()
                contender.join(timeout=1.0)

            self.assertFalse(contender.is_alive())
            self.assertEqual(observed, ["timed_out"])


if __name__ == "__main__":
    unittest.main()
