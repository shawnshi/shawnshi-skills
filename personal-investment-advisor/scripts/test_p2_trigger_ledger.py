"""Contract tests for the run-level trigger ledger (P1-5).

The ledger records what a run flagged so a later review has something to check.
Append must be idempotent, a run without boundary evidence must record ``null``
rather than an empty list, and a closed entry must stop appearing as due.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_trigger_ledger as ledger  # noqa: E402

EPOCH = 1790481509.0  # 2026-09-27


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "run-a"
        (self.run_dir / "out").mkdir(parents=True)
        self.ledger_path = self.root / "pia_trigger_ledger.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def write_run(self, *, status="complete", weights=None, watchlist=None,
                  with_summary=True) -> None:
        if with_summary:
            (self.run_dir / "out" / "daily_run_summary.json").write_bytes(json.dumps({
                "status": status, "detail_status": "daily_run_complete",
                "evaluation_epoch": EPOCH, "generated_at": "2026-09-27T02:05:09+00:00",
                "positions_input_sha256": "a" * 64,
                "stages": [{"stage": "weights", "status": "complete"},
                           {"stage": "watchlist", "status": "complete"}],
            }, ensure_ascii=False).encode("utf-8"))
        if weights is not None:
            (self.run_dir / "out" / "weights.json").write_bytes(json.dumps({
                "status": "complete", "evaluation_epoch": EPOCH,
                "current_weights": [{"symbol": symbol, "current_weight": value}
                                    for symbol, value in weights.items()],
            }).encode("utf-8"))
        if watchlist is not None:
            (self.run_dir / "out" / "watchlist_results.json").write_bytes(json.dumps(
                watchlist, ensure_ascii=False).encode("utf-8"))

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ledger.main(argv)
        return code, json.loads(buffer.getvalue())


class AppendTests(LedgerTestCase):
    def test_append_records_weights_boundaries_and_horizon(self):
        self.write_run(weights={"X": 0.6, "Y": 0.4},
                       watchlist={"X": {"status": "ok",
                                        "runtime_quote": {"current_price": 30.01},
                                        "categories": {"downside_boundary_crossed": ["X-down"]}},
                                  "Y": {"status": "ok", "categories": {}}})
        code, payload = self.run_cli(["append", "--run-dir", str(self.run_dir),
                                      "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["detail_status"], "entry_appended")
        entry = ledger.read_entries(self.ledger_path)[0]
        self.assertEqual(entry["weights"], {"X": 0.6, "Y": 0.4})
        self.assertEqual(entry["crossed_boundaries"][0]["symbol"], "X")
        self.assertEqual(entry["crossed_boundaries"][0]["observed_price"], 30.01)
        self.assertEqual(entry["review_horizon_date"], "2026-12-26")
        self.assertTrue(entry["boundaries_evaluated"])

    def test_second_append_of_the_same_run_is_idempotent(self):
        self.write_run(weights={"X": 1.0}, watchlist={})
        first = self.run_cli(["append", "--run-dir", str(self.run_dir),
                              "--ledger", str(self.ledger_path)])[1]
        second = self.run_cli(["append", "--run-dir", str(self.run_dir),
                               "--ledger", str(self.ledger_path)])[1]
        self.assertTrue(first["appended"])
        self.assertFalse(second["appended"])
        self.assertEqual(second["detail_status"], "already_recorded")
        self.assertEqual(len(ledger.read_entries(self.ledger_path)), 1)

    def test_missing_boundary_evidence_records_null_not_empty(self):
        self.write_run(weights={"X": 1.0})
        self.run_cli(["append", "--run-dir", str(self.run_dir),
                      "--ledger", str(self.ledger_path)])
        entry = ledger.read_entries(self.ledger_path)[0]
        self.assertIsNone(entry["crossed_boundaries"])
        self.assertFalse(entry["boundaries_evaluated"])

    def test_run_without_summary_or_weights_is_refused(self):
        code, payload = self.run_cli(["append", "--run-dir", str(self.run_dir),
                                      "--ledger", str(self.ledger_path)])
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "ledger_error")
        self.assertFalse(self.ledger_path.exists())

    def test_task_root_defaults_the_ledger_path(self):
        self.write_run(weights={"X": 1.0}, watchlist={})
        code, payload = self.run_cli(["append", "--run-dir", str(self.run_dir),
                                      "--task-root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ledger.DEFAULT_LEDGER_NAME).is_file())


class DueAndCloseTests(LedgerTestCase):
    def seed(self, *, run_id: str = "run-a", review_days: int = 90) -> None:
        self.write_run(weights={"X": 1.0},
                       watchlist={"X": {"status": "ok",
                                        "categories": {"downside_boundary_crossed": ["X-down"]}}})
        self.run_cli(["append", "--run-dir", str(self.run_dir),
                      "--ledger", str(self.ledger_path), "--review-days", str(review_days)])

    def test_nothing_is_due_before_the_horizon(self):
        self.seed()
        code, payload = self.run_cli(["due", "--ledger", str(self.ledger_path),
                                      "--as-of", "2026-10-01"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "nothing_due")

    def test_entry_becomes_due_after_the_horizon(self):
        self.seed()
        code, payload = self.run_cli(["due", "--ledger", str(self.ledger_path),
                                      "--as-of", "2027-01-05"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["due_count"], 1)
        self.assertEqual(payload["due"][0]["crossed_boundaries"][0]["boundary_id"], "X-down")

    def test_closing_an_entry_removes_it_from_due(self):
        self.seed()
        entry_id = ledger.read_entries(self.ledger_path)[0]["entry_id"]
        code, closed = self.run_cli(["close", "--ledger", str(self.ledger_path),
                                     "--entry-id", entry_id, "--note", "reviewed the drawdown",
                                     "--outcome", "trigger_hit"])
        self.assertEqual(code, 0)
        self.assertEqual(closed["detail_status"], "entry_closed")
        due = self.run_cli(["due", "--ledger", str(self.ledger_path), "--as-of", "2027-01-05"])[1]
        self.assertEqual(due["due_count"], 0)
        listed = self.run_cli(["list", "--ledger", str(self.ledger_path)])[1]
        self.assertEqual(listed["closure_count"], 1)
        self.assertEqual(listed["entries"][0]["review_outcome"], "trigger_hit")

    def test_unknown_entry_id_is_reported(self):
        self.seed()
        code, payload = self.run_cli(["close", "--ledger", str(self.ledger_path),
                                      "--entry-id", "nope", "--note", "x",
                                      "--outcome", "inconclusive"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "entry_not_found")

    def test_ledger_is_separate_from_the_advice_journal(self):
        self.seed()
        entries = ledger.read_entries(self.ledger_path)
        self.assertEqual(entries[0]["schema_version"], "pia_trigger_ledger_v1")
        self.assertNotIn("entry", entries[0])  # no advice-journal payload shape


if __name__ == "__main__":
    unittest.main()
