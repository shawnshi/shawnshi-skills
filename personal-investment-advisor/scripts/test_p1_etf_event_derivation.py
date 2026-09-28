"""Contract tests for the ETF packet event derivations (P0-4).

The provider publishes distributions at its own precision while an exchange feed may
carry more decimals, so the factor convention must quantise both sides explicitly —
otherwise every row mismatches. These tests pin that convention, the as-of/window
filtering, the split formatting and the fail-closed paths.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_etf_packet as packet  # noqa: E402


def actions_frame(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [{"Dividends": dividend, "Stock Splits": split} for _, dividend, split in rows],
        index=pd.to_datetime([day for day, _, _ in rows]),
    )
    return frame


class DeriveProviderEventsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = Path(self._tmp.name) / "task"
        (self.task_dir / "raw").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = packet.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_dividends_are_quantised_to_the_provider_precision(self):
        frame = actions_frame([("2026-03-23", 0.73282, 0.0), ("2026-06-22", 0.81349, 0.0)])
        with mock.patch("yfinance.Ticker", return_value=mock.Mock(actions=frame)):
            code, receipt = self.run_cli([
                "derive-provider-events", "--symbol", "QQQ", "--as-of-date", "2026-09-27",
                "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, receipt)
        self.assertEqual([event["factor"] for event in receipt["events"]], ["0.733", "0.813"])
        capture = json.loads(Path(receipt["capture_file"]).read_text(encoding="utf-8"))
        self.assertEqual(capture["derived"][0]["source_amount"], 0.73282)
        self.assertEqual(receipt["capture_sha256"],
                         __import__("hashlib").sha256(
                             Path(receipt["capture_file"]).read_bytes()).hexdigest())

    def test_window_and_as_of_filter_are_applied(self):
        frame = actions_frame([("2024-01-02", 0.5, 0.0), ("2026-03-23", 0.7, 0.0),
                               ("2026-12-22", 0.9, 0.0)])
        with mock.patch("yfinance.Ticker", return_value=mock.Mock(actions=frame)):
            _code, receipt = self.run_cli([
                "derive-provider-events", "--symbol", "QQQ", "--as-of-date", "2026-09-27",
                "--window-days", "400", "--task-dir", str(self.task_dir)])
        self.assertEqual([event["effective_date"] for event in receipt["events"]], ["2026-03-23"])

    def test_splits_use_a_ratio_factor_and_ignore_the_identity_split(self):
        frame = actions_frame([("2026-02-02", 0.0, 4.0), ("2026-03-03", 0.0, 1.0),
                              ("2026-04-04", 0.0, 0.5)])
        with mock.patch("yfinance.Ticker", return_value=mock.Mock(actions=frame)):
            _code, receipt = self.run_cli([
                "derive-provider-events", "--symbol", "QQQ", "--as-of-date", "2026-09-27",
                "--task-dir", str(self.task_dir)])
        self.assertEqual([(event["event_type"], event["factor"]) for event in receipt["events"]],
                         [("split", "4.000000:1"), ("split", "1:2.000000")])

    def test_empty_action_series_yields_zero_events_not_an_error(self):
        with mock.patch("yfinance.Ticker", return_value=mock.Mock(actions=pd.DataFrame())):
            code, receipt = self.run_cli([
                "derive-provider-events", "--symbol", "159072.SZ", "--as-of-date", "2026-09-27",
                "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0)
        self.assertEqual(receipt["event_count"], 0)

    def test_provider_failure_is_reported(self):
        with mock.patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
            code, payload = self.run_cli([
                "derive-provider-events", "--symbol", "QQQ", "--as-of-date", "2026-09-27",
                "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("provider action feed unavailable", payload["errors"][0])


class DeriveOfficialEventsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = Path(self._tmp.name) / "task"
        (self.task_dir / "raw").mkdir(parents=True)
        self.feed = Path(self._tmp.name) / "feed.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_feed(self, rows) -> None:
        self.feed.write_text(json.dumps({"data": {"dividends": {"rows": rows}}}), encoding="utf-8")

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = packet.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_feed_rows_are_parsed_quantised_and_windowed(self):
        self.write_feed([
            {"exOrEffDate": "09/21/2026", "type": "Cash", "amount": "$0.75143"},
            {"exOrEffDate": "03/23/2026", "type": "Cash", "amount": "$0.73282"},
            {"exOrEffDate": "01/02/2024", "type": "Cash", "amount": "$0.50000"},
            {"exOrEffDate": "bad-date", "type": "Cash", "amount": "$0.10"},
        ])
        code, receipt = self.run_cli([
            "derive-official-events", "--symbol", "QQQ", "--feed-file", str(self.feed),
            "--as-of-date", "2026-09-27", "--window-days", "400",
            "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 0, receipt)
        # events are sorted by date, so the feed order does not leak into the packet
        self.assertEqual([event["factor"] for event in receipt["events"]], ["0.733", "0.751"])
        self.assertEqual([event["effective_date"] for event in receipt["events"]],
                         ["2026-03-23", "2026-09-21"])
        self.assertTrue(any("unparsable date" in row for row in receipt["skipped_rows"]))

    def test_malformed_feed_is_refused(self):
        self.feed.write_text(json.dumps({"data": {}}), encoding="utf-8")
        code, payload = self.run_cli([
            "derive-official-events", "--symbol", "QQQ", "--feed-file", str(self.feed),
            "--as-of-date", "2026-09-27", "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 3)
        self.assertIn("data.dividends.rows", payload["errors"][0])

    def test_no_events_in_window_is_insufficient_data(self):
        self.write_feed([{"exOrEffDate": "01/02/2024", "type": "Cash", "amount": "$0.5"}])
        code, payload = self.run_cli([
            "derive-official-events", "--symbol", "QQQ", "--feed-file", str(self.feed),
            "--as-of-date", "2026-09-27", "--task-dir", str(self.task_dir)])
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "no_official_events_in_window")


class DispatchCompatibilityTests(unittest.TestCase):
    def test_flag_only_invocation_still_reaches_assemble(self):
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = packet.main(["--evidence-file", str(Path(tmp) / "absent.json"),
                                    "--task-dir", tmp])
            payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "packet_input_invalid")

    def test_quantize_helper_rounds_half_away_from_zero(self):
        self.assertEqual(packet._quantize(0.73282, 3), "0.733")
        self.assertEqual(packet._quantize(0.59111, 3), "0.591")
        self.assertIsNone(packet._parse_amount("N/A"))


if __name__ == "__main__":
    unittest.main()
